"""Machine-wide model-session slots and the shared rate-limit cool-down (r5d21, every task).

Two real runs (B0H16FDSD8, B0GLNPC6K8, 2026-10-14) ran side by side on one ChatGPT account: up to 13 Codex sessions at
once, about half of them ended with "429 Too Many Requests" a few seconds after starting (sessions that failed started
at a median of 8 concurrent sessions, sessions that worked at 5), and every failed batch waited for the next pipeline
round. Native sessions run with Codex's own retries switched off (``report_review_host.native_review_command``).

* ``slot()``: every native session holds one of ``SLOTS`` lock files in a per-user directory shared by all tasks and
  processes of this user (``tempfile.gettempdir()``, where the skill already keeps its review workspaces), so a second
  task waits for a free slot instead of adding to the load. A crashed process releases its slot with its file handle.
* ``rate_limited(trace)``: a session that ended on a 429 / "Too Many Requests" error before any model output.
* ``note_rate_limit(attempt)``: writes a shared cool-down; no process starts a new session before it ends.

Nothing here judges, records or changes a review; it only decides when a session starts.
"""
from __future__ import annotations

from contextlib import contextmanager
import json
import os
from pathlib import Path
import random
import tempfile
import time

# r5d25: six, so the final review's six module sessions start together (run B0GLNPC6K8: with four, the expression
# sessions waited about five minutes for a slot); the 429 cool-down and retries below still guard the account
SLOTS = 6
BACKOFF_SECONDS = (30, 60, 120, 120)
MAX_RATE_LIMIT_RETRIES = len(BACKOFF_SECONDS)
MAX_SLOT_WAIT_SECONDS = 1800
RATE_MARKERS = ('429', 'too many requests', 'rate limit', 'rate_limit', 'ratelimit')
# a spent plan or account quota does not clear within minutes: such a failure is reported, not retried
QUOTA_MARKERS = ('usage limit', 'quota', 'insufficient_quota', 'billing')


def directory() -> Path:
    override = os.environ.get('LC_IPR_MODEL_SLOT_DIR')
    path = Path(override) if override else Path(tempfile.gettempdir()) / 'lc-ipr-model-slots'
    path.mkdir(parents=True, exist_ok=True)
    return path


def slot_count() -> int:
    try:
        value = int(os.environ.get('LC_IPR_MODEL_SLOTS') or SLOTS)
    except ValueError:
        value = SLOTS
    return max(1, min(8, value))


def backoff(attempt: int) -> float:
    override = os.environ.get('LC_IPR_RATE_LIMIT_BACKOFF')
    if override:
        try:
            values = [float(part) for part in override.split(',') if part.strip()]
        except ValueError:
            values = []
        if values:
            return values[min(attempt, len(values) - 1)]
    base = BACKOFF_SECONDS[min(attempt, len(BACKOFF_SECONDS) - 1)]
    return base + random.uniform(0, base / 6)


def _try_lock(handle) -> bool:
    try:
        if os.name == 'nt':
            import msvcrt
            handle.seek(0, 2)
            if handle.tell() == 0:
                handle.write(b'0')
                handle.flush()
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        return True
    except OSError:
        return False


def _unlock(handle) -> None:
    try:
        if os.name == 'nt':
            import msvcrt
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    except OSError:
        pass


def cooldown_remaining() -> float:
    path = directory() / 'cooldown.json'
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
        return max(0.0, float(data.get('until') or 0) - time.time())
    except (OSError, ValueError, TypeError, AttributeError):
        return 0.0


def note_rate_limit(attempt: int, reason: str = 'rate_limited') -> float:
    """Extend the shared cool-down for this attempt; returns the seconds this caller should wait."""
    wait = backoff(attempt)
    path = directory() / 'cooldown.json'
    until = time.time() + wait
    try:
        current = json.loads(path.read_text(encoding='utf-8')).get('until') or 0
    except (OSError, ValueError, TypeError, AttributeError):
        current = 0
    if float(current) < until:
        temporary = path.with_name('cooldown.%d.%d.tmp' % (os.getpid(), int(time.time() * 1000)))
        try:
            temporary.write_text(json.dumps({'until': until, 'reason': reason, 'pid': os.getpid(),
                                             'set_at': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}),
                                 encoding='utf-8')
            os.replace(temporary, path)
        except OSError:
            try:
                temporary.unlink()
            except OSError:
                pass
    return wait


def wait_cooldown(sleep=time.sleep) -> float:
    waited = 0.0
    while True:
        left = cooldown_remaining()
        if left <= 0:
            return waited
        step = min(left, 5.0)
        sleep(step)
        waited += step


@contextmanager
def slot(*, poll: float = 1.0, max_wait: float | None = None, sleep=time.sleep):
    """Hold one machine-wide model slot; yields a dict with the seconds spent waiting for the slot and cool-down."""
    record = {'slot': None, 'waited_seconds': 0.0}
    limit = MAX_SLOT_WAIT_SECONDS if max_wait is None else max_wait
    started = time.monotonic()
    held = None
    while held is None:
        record['waited_seconds'] += wait_cooldown(sleep)
        folder = directory()
        for number in range(slot_count()):
            handle = (folder / ('slot-%d.lock' % number)).open('a+b')
            if _try_lock(handle):
                held, record['slot'] = handle, number
                break
            handle.close()
        if held is None:
            if time.monotonic() - started >= limit:
                raise ValueError('MODEL_SLOT_WAIT_TIMEOUT')
            sleep(poll)
            record['waited_seconds'] += poll
    try:
        yield record
    finally:
        _unlock(held)
        held.close()


def _events(trace: str):
    for line in (trace or '').splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if isinstance(event, dict):
            yield event


def _failure_messages(trace: str):
    messages, output = [], False
    for event in _events(trace):
        kind = event.get('type')
        item = event.get('item') if isinstance(event.get('item'), dict) else {}
        if kind == 'item.completed' and item.get('type') == 'agent_message':
            output = True
        if kind in {'error', 'turn.failed'}:
            error = event.get('error') if isinstance(event.get('error'), dict) else {}
            messages.append(str(event.get('message') or error.get('message') or ''))
    return messages, output


def rate_limited(trace: str) -> bool:
    """A session that failed on a transient rate limit before producing any model output."""
    messages, output = _failure_messages(trace)
    if output or not messages:
        return False
    text = ' '.join(messages).lower()
    return any(marker in text for marker in RATE_MARKERS) and not any(marker in text for marker in QUOTA_MARKERS)


def quota_exhausted(trace: str) -> bool:
    messages, _ = _failure_messages(trace)
    text = ' '.join(messages).lower()
    return bool(messages) and any(marker in text for marker in QUOTA_MARKERS)
