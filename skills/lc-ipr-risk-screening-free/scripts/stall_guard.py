"""r5d22: a model session that has said nothing for far longer than its peers took is a stalled connection.

Run B0H16FDSD8 (r5d21, behind a fake-IP proxy): 3 of 29 sessions never produced a single event - two query reviews
were cut only at their 240 s limit, and the second chain's appearance module of the final review at its 900 s limit,
although the first chain had finished the same material in 392 s; the review then failed. A silent session is now
stopped as soon as its peers prove it is overdue, and the caller's existing retry runs it again:

* batch sessions (a 64-hex session folder under a host folder): after three times the slowest finished peer of the
  same folder, at least ``MIN_SECONDS``, once ``PEER_MIN_COUNT`` peers have finished;
* final-review slots (``<review>/<chain>/<module>``): after 1.6 times the other chain's finished session of the same
  module (at least that time plus ``TWIN_MARGIN``).

A session that has started its answer is never stopped by this rule; without finished peers nothing changes.

r5d23: the other way a connection behind the proxy dies. Run B0GLNPC6K8 (r5d21): a query review delivered its whole
answer at 72 s, then the closing event of the turn never came and the session was cut at its 240 s limit. Across 82
finished sessions of both r5d21 runs that closing event followed the completed answer within 3 s. A session whose
answer is complete and that stays silent for ``ANSWERED_GRACE`` seconds without closing its turn is stopped the same
way (``answered_stalled``); its answer is not used (an unclosed turn is not a review) and the usual retry runs it again.
"""
import json
import re
from pathlib import Path

HASH_DIR = re.compile(r'^[0-9a-f]{64}(\.attempt-\d+)?$')
CHAINS = ('1', '2')
MIN_SECONDS = 120
PEER_FACTOR = 3.0
PEER_MIN_COUNT = 2
TWIN_FACTOR = 1.6
TWIN_MARGIN = 180
CHECK_SECONDS = 5
ANSWERED_GRACE = 30
EXECUTION = 'events.execution.json'


def answered_stalled(answer_completed, turn_completed, last_event, elapsed):
    """Whether a session whose answer is complete has waited ``ANSWERED_GRACE`` seconds in silence for its turn to close."""
    return (answer_completed is not None and turn_completed is None and last_event is not None
            and elapsed - last_event >= ANSWERED_GRACE)


def finished_seconds(path):
    """Seconds a successfully finished session took (its host execution record), else None."""
    try:
        data = json.loads(Path(path).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or data.get('status') != 'process_exited' or data.get('exit_code') != 0:
        return None
    value = data.get('turn_completed_seconds') or data.get('elapsed_seconds')
    return float(value) if isinstance(value, (int, float)) and value > 0 else None


def twin_seconds(directory):
    """Seconds the other chain took for the same final-review slot, else None."""
    directory = Path(directory)
    chain = directory.parent.name
    if chain not in CHAINS:
        return None
    other = directory.parent.parent / ('2' if chain == '1' else '1') / directory.name.split('.attempt-')[0]
    return finished_seconds(other / EXECUTION)


def peer_seconds(directory):
    """Seconds of the finished sessions beside a batch session (its own earlier attempts excluded)."""
    directory = Path(directory)
    own = directory.name.split('.')[0]
    values = []
    try:
        folders = list(directory.parent.iterdir())
    except OSError:
        return values
    for folder in folders:
        if folder.is_dir() and HASH_DIR.match(folder.name) and folder.name.split('.')[0] != own:
            value = finished_seconds(folder / EXECUTION)
            if value is not None:
                values.append(value)
    return values


def limit(trace_path):
    """Seconds after which a still-silent session at ``trace_path`` counts as stalled, or None (no rule applies)."""
    directory = Path(trace_path).parent
    if HASH_DIR.match(directory.name):
        peers = peer_seconds(directory)
        if len(peers) < PEER_MIN_COUNT:
            return None
        return max(MIN_SECONDS, PEER_FACTOR * max(peers))
    twin = twin_seconds(directory)
    if twin is None:
        return None
    return max(MIN_SECONDS, TWIN_FACTOR * twin, twin + TWIN_MARGIN)


def stalled(directory):
    """Whether the session last run in ``directory`` was stopped by this rule."""
    try:
        data = json.loads((Path(directory) / EXECUTION).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return False
    return isinstance(data, dict) and data.get('status') == 'stalled'
