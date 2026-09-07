"""Conservative, cross-task pre-request reservations for free search accounts.

Only hashes and counters are stored. An uncertain request stays charged locally;
increasing remote balances never refill the ledger without a proved later cycle.
"""
from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import tempfile
from datetime import date
from pathlib import Path

from common import atomic_write_json
from provider_utils import ProviderError, file_lock, redact_sensitive_text


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _root(base: str) -> Path:
    if os.environ.get("LC_IPR_TEST_MODE") == "1":
        override = os.environ.get("LC_IPR_FREE_SEARCH_LEDGER_DIR")
        return Path(override) if override else Path(tempfile.gettempdir()) / ("lc-ipr-free-search-test-" + _digest(base)[:24])
    home = Path.home()
    if platform.system() == "Darwin":
        return home / "Library/Application Support/lc-ipr-risk-screening-free/free-search-quota"
    if platform.system() == "Windows":
        return home / "AppData/Local/lc-ipr-risk-screening-free/free-search-quota"
    return home / ".local/state/lc-ipr-risk-screening-free/free-search-quota"


def attempt_context(attempt_id: str, retry_reason: str) -> dict:
    if not isinstance(attempt_id, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,95}', attempt_id):
        raise ProviderError('FREE_SEARCH_ATTEMPT_INVALID', 'failed', 'Free search attempt id must be a bounded identifier')
    if not isinstance(retry_reason, str) or len(retry_reason) > 600 or (attempt_id != 'initial' and not retry_reason.strip()):
        raise ProviderError('FREE_SEARCH_RETRY_REASON_REQUIRED', 'failed', 'A new retry attempt needs a concrete changed condition or evidence-repair reason')
    return {'attempt_id': attempt_id, 'retry_reason': redact_sensitive_text(retry_reason.strip())}


def reserve_search(provider: str, credential: str, base: str, *, remaining: int,
                   task_dir: Path, query_id: str, renewal_date: str = "",
                   plan_entry_sha256: str = "", attempt_id: str = 'initial', retry_reason: str = '',
                   max_queries_per_task: int = 3,
                   ledger_dir: Path | None = None) -> dict:
    """Atomically debit one query before sending it; never automatically refund.

    SerpApi Patents and Lens must both pass provider='serpapi'. The date is an
    actual account response field, never a locally guessed billing boundary.
    Missing cycle evidence preserves the conservative running balance.
    """
    if not credential or not provider or not query_id:
        raise ProviderError("FREE_SEARCH_IDENTITY_MISSING", "access_limited", "A free search reservation requires account and query identity")
    if isinstance(remaining, bool) or not isinstance(remaining, int) or remaining <= 0:
        raise ProviderError("FREE_QUOTA_EXHAUSTED", "access_limited", "No confirmed free search allowance remains")
    if isinstance(max_queries_per_task, bool) or not isinstance(max_queries_per_task, int) or not 1 <= max_queries_per_task <= 100:
        raise ProviderError('FREE_SEARCH_TASK_LIMIT_INVALID', 'failed', 'Free search reservation needs a bounded per-task attempt limit')
    cycle = ""
    if renewal_date:
        try:
            cycle = date.fromisoformat(renewal_date).isoformat()
        except (TypeError, ValueError):
            pass  # Do not infer a reset from an unrecognized server date.
    attempt = attempt_context(attempt_id, retry_reason)
    if plan_entry_sha256 and not re.fullmatch(r'[0-9a-f]{64}', plan_entry_sha256):
        raise ProviderError('FREE_SEARCH_PLAN_HASH_INVALID', 'failed', 'Free search reservation plan hash is invalid')
    account = _digest("lc-ipr-free-search\0" + provider + "\0" + base + "\0" + credential)
    task_fingerprint = _digest(str(task_dir.resolve()))
    reservation = _digest(str(task_dir.resolve()) + "\0" + query_id + "\0" + plan_entry_sha256 + "\0" + attempt_id)
    root = (ledger_dir or _root(base)).expanduser()
    try:
        if root.is_symlink():
            raise ValueError("linked ledger directory")
        root.mkdir(parents=True, exist_ok=True, mode=0o700)
        root.chmod(0o700)
        path = root / (account + ".json")
        with file_lock(root / (account + ".lock")):
            if path.is_symlink():
                raise ValueError("linked ledger")
            state = None
            if path.exists():
                if path.stat().st_size > 1024 * 1024:
                    raise ValueError("oversized ledger")
                state = json.loads(path.read_text())
                if (not isinstance(state, dict) or state.get("schema") != "FREE-SEARCH-BUDGET/1.0"
                    or state.get("account") != account or not isinstance(state.get("reservations"), list)
                    or not isinstance(state.get("task_usage"), dict)
                    or isinstance(state.get("remaining"), bool) or not isinstance(state.get("remaining"), int)
                    or state["remaining"] < 0 or not isinstance(state.get("cycle"), str)):
                    raise ValueError("invalid ledger")
                if (any(not isinstance(value, int) or isinstance(value, bool) or value < 0 for value in state['task_usage'].values())
                    or sum(state['task_usage'].values()) != len(state['reservations'])):
                    raise ValueError('inconsistent task reservations')
            # A later remote renewal date can reset only after the old date has
            # arrived. Missing/earlier/unchanged date evidence cannot refill it.
            reset = bool(state and cycle and state["cycle"] and cycle > state["cycle"]
                         and date.today().isoformat() >= state["cycle"]
                         and cycle > date.today().isoformat())
            if state is None or reset:
                state = {"schema": "FREE-SEARCH-BUDGET/1.0", "account": account,
                         "cycle": cycle, "remaining": remaining, "reservations": [], 'task_usage': {}}
            if reservation in state["reservations"]:
                raise ProviderError("FREE_SEARCH_ALREADY_RESERVED", "access_limited", "This exact attempt already reserved account allowance; another explicit attempt must reserve additional free quota")
            task_used = state['task_usage'].get(task_fingerprint, 0)
            if task_used >= max_queries_per_task:
                raise ProviderError('FREE_SEARCH_TASK_RESERVATIONS_EXHAUSTED', 'access_limited', 'This task already reserved its maximum attempts, including attempts whose result record was lost')
            available = min(state["remaining"], remaining)
            if available <= 0:
                raise ProviderError("FREE_QUOTA_EXHAUSTED", "access_limited", "Shared local free allowance is exhausted; a higher remote balance alone cannot release uncertain consumption")
            if len(state["reservations"]) >= 10000:
                raise ProviderError("FREE_SEARCH_LEDGER_FULL", "access_limited", "Free search ledger requires a verified cycle before accepting more reservations")
            state["remaining"] = available - 1
            state["reservations"].append(reservation)
            state['task_usage'][task_fingerprint] = task_used + 1
            atomic_write_json(path, state)
            path.chmod(0o600)
            with path.open('rb') as handle:
                os.fsync(handle.fileno())
            if os.name == 'posix':
                descriptor = os.open(root, os.O_RDONLY)
                try:
                    os.fsync(descriptor)
                finally:
                    os.close(descriptor)
            return {**attempt, "local_account_reservation": reservation, "local_free_searches_left": state["remaining"],
                    'local_task_attempts_reserved': task_used + 1,
                    "local_cycle_verified": bool(state["cycle"]), "uncertain_request_refunded": False}
    except (OSError, ValueError, TypeError) as exc:
        raise ProviderError("FREE_SEARCH_LEDGER_INVALID", "access_limited", "Shared free-search ledger is unreadable or invalid; no search was authorized") from exc
