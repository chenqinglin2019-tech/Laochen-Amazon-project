#!/usr/bin/env python3
"""Cross-process, account-scoped EPO OPS registered-free quota ledger."""

from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import secrets
import tempfile
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterator

try:
    import fcntl
except ImportError:  # pragma: no cover - Windows uses msvcrt.
    fcntl = None

try:
    import msvcrt
except ImportError:  # pragma: no cover - POSIX uses fcntl.
    msvcrt = None

from provider_utils import ProviderError


LEDGER_SCHEMA_VERSION = 1
WINDOW_KIND = "iso_week_utc"
STATE_DIRECTORY_NAME = "lc-ipr-risk-screening-free/epo-quota"


def account_fingerprint(consumer_key: str) -> str:
    """Return a one-way account identifier; never persist the consumer key."""
    if not isinstance(consumer_key, str) or not consumer_key:
        raise ProviderError(
            "AUTH_FAILED", "access_limited", "EPO OPS consumer key is missing",
        )
    return hashlib.sha256(
        b"lc-ipr-risk-screening-free\x00epo-ops-account\x00"
        + consumer_key.encode("utf-8")
    ).hexdigest()


def default_ledger_dir() -> Path:
    test_override = os.environ.get("LC_IPR_EPO_LEDGER_DIR", "")
    if os.environ.get("LC_IPR_TEST_MODE") == "1" and test_override:
        return Path(test_override)
    home = Path.home()
    if platform.system() == "Darwin":
        return home / "Library" / "Application Support" / STATE_DIRECTORY_NAME
    if platform.system() == "Windows":
        return home / "AppData" / "Local" / STATE_DIRECTORY_NAME
    return home / ".local" / "state" / STATE_DIRECTORY_NAME


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ProviderError(
            "EPO_QUOTA_WINDOW_UNCERTAIN", "access_limited",
            "EPO quota clock must include a timezone",
        )
    return value.astimezone(timezone.utc)


def iso_week_window(value: datetime) -> dict[str, str]:
    now = _utc(value)
    start = (now - timedelta(days=now.weekday())).replace(
        hour=0, minute=0, second=0, microsecond=0,
    )
    end = start + timedelta(days=7)
    iso_year, iso_week, _ = start.isocalendar()
    return {
        "kind": WINDOW_KIND,
        "id": f"{iso_year:04d}-W{iso_week:02d}",
        "start": start.isoformat().replace("+00:00", "Z"),
        "end": end.isoformat().replace("+00:00", "Z"),
    }


def _parse_timestamp(value: Any) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise ProviderError(
            "EPO_QUOTA_WINDOW_UNCERTAIN", "access_limited",
            "Persisted EPO quota window is invalid; automatic reset is disabled",
        ) from exc
    return _utc(parsed)


def _header_int(headers: dict[str, Any], name: str) -> int | None:
    raw = next(
        (value for key, value in headers.items() if str(key).casefold() == name.casefold()),
        None,
    )
    if raw is None:
        return None
    digits = re.sub(r"[^0-9]", "", str(raw))
    return int(digits) if digits else None


def _now_iso(value: datetime) -> str:
    return _utc(value).replace(microsecond=0).isoformat().replace("+00:00", "Z")


class EpoQuotaLedger:
    """Reserve and settle EPO quota atomically across tasks and processes."""

    def __init__(
        self,
        config: dict[str, Any],
        consumer_key: str,
        *,
        ledger_dir: Path | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        provider = config.get("providers", {}).get("epo_ops", {})
        policy = config.get("free_policy", {})
        if provider.get("allow_overage") is not False or policy.get("allow_overage") is not False:
            raise ProviderError(
                "EPO_OVERAGE_POLICY_INVALID", "failed",
                "EPO OPS paid/overage access must remain disabled",
            )
        try:
            free_limit = int(provider["documented_free_bytes_per_week"])
            stop_margin = max(int(provider.get("free_stop_margin_bytes", 0)), 0)
            estimate = int(provider["estimated_max_response_bytes_per_query"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ProviderError(
                "EPO_FREE_QUOTA_CONFIGURATION_MISSING", "failed",
                "EPO OPS free quota configuration is incomplete",
            ) from exc
        stop_at = free_limit - stop_margin
        if free_limit <= 0 or estimate <= 0 or stop_at <= estimate:
            raise ProviderError(
                "EPO_FREE_QUOTA_CONFIGURATION_MISSING", "failed",
                "EPO OPS free quota configuration is unsafe",
            )
        self.free_limit = free_limit
        self.stop_margin = stop_margin
        self.stop_at = stop_at
        self.estimate = estimate
        self.fingerprint = account_fingerprint(consumer_key)
        self.root = (ledger_dir or default_ledger_dir()).expanduser().resolve()
        self.path = self.root / f"epo-ops-{self.fingerprint}.json"
        self.lock_path = self.root / f"epo-ops-{self.fingerprint}.lock"
        self._now = now or (lambda: datetime.now(timezone.utc))

    def _ensure_directory(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        try:
            self.root.chmod(0o700)
        except OSError:
            pass

    @contextmanager
    def _locked(self) -> Iterator[None]:
        self._ensure_directory()
        with self.lock_path.open("a+b") as handle:
            try:
                self.lock_path.chmod(0o600)
            except OSError:
                pass
            if fcntl is not None:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            elif msvcrt is not None:  # pragma: no cover - Windows only.
                handle.seek(0)
                if handle.read(1) == b"":
                    handle.write(b"0")
                    handle.flush()
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
            else:  # pragma: no cover - unsupported platform fails closed.
                raise ProviderError(
                    "EPO_QUOTA_LOCK_UNAVAILABLE", "access_limited",
                    "No cross-process file lock is available for EPO quota enforcement",
                )
            try:
                yield
            finally:
                if fcntl is not None:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
                elif msvcrt is not None:  # pragma: no cover - Windows only.
                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)

    def _fresh_state(self, now: datetime) -> dict[str, Any]:
        timestamp = _now_iso(now)
        return {
            "schema_version": LEDGER_SCHEMA_VERSION,
            "provider": "epo_ops",
            "account_fingerprint": self.fingerprint,
            "window": iso_week_window(now),
            "free_limit_bytes": self.free_limit,
            "stop_margin_bytes": self.stop_margin,
            "stop_at_bytes": self.stop_at,
            "reservation_bytes": self.estimate,
            "registered_usage_observed": False,
            "registered_used_bytes": 0,
            "unconfirmed_consumed_bytes": 0,
            "paying_used_bytes": 0,
            "stop_required": False,
            "stop_code": "",
            "reservations": {},
            "created_at": timestamp,
            "updated_at": timestamp,
        }

    def _validate_state(self, state: Any) -> dict[str, Any]:
        if not isinstance(state, dict):
            raise ProviderError(
                "EPO_QUOTA_LEDGER_INVALID", "access_limited",
                "EPO quota ledger is not a JSON object",
            )
        if (
            state.get("schema_version") != LEDGER_SCHEMA_VERSION
            or state.get("provider") != "epo_ops"
            or state.get("account_fingerprint") != self.fingerprint
            or not isinstance(state.get("window"), dict)
            or not isinstance(state.get("reservations"), dict)
        ):
            raise ProviderError(
                "EPO_QUOTA_LEDGER_INVALID", "access_limited",
                "EPO quota ledger identity or schema is invalid",
            )
        for name in (
            "free_limit_bytes", "stop_margin_bytes", "stop_at_bytes",
            "reservation_bytes", "registered_used_bytes",
            "unconfirmed_consumed_bytes", "paying_used_bytes",
        ):
            value = state.get(name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ProviderError(
                    "EPO_QUOTA_LEDGER_INVALID", "access_limited",
                    "EPO quota ledger contains an invalid counter",
                )
        if any(
            not isinstance(value, dict)
            or isinstance(value.get("bytes"), bool)
            or not isinstance(value.get("bytes"), int)
            or value.get("bytes") <= 0
            for value in state["reservations"].values()
        ):
            raise ProviderError(
                "EPO_QUOTA_LEDGER_INVALID", "access_limited",
                "EPO quota ledger contains an invalid reservation",
            )
        return state

    def _load_locked(self, now: datetime) -> dict[str, Any]:
        if not self.path.is_file():
            return self._fresh_state(now)
        try:
            state = self._validate_state(json.loads(self.path.read_text(encoding="utf-8")))
        except ProviderError:
            raise
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise ProviderError(
                "EPO_QUOTA_LEDGER_INVALID", "access_limited",
                "EPO quota ledger cannot be read safely",
            ) from exc

        current_window = iso_week_window(now)
        stored_window = state["window"]
        stored_start = _parse_timestamp(stored_window.get("start"))
        stored_end = _parse_timestamp(stored_window.get("end"))
        if (
            stored_window.get("kind") != WINDOW_KIND
            or stored_end - stored_start != timedelta(days=7)
            or stored_window.get("id") == ""
        ):
            raise ProviderError(
                "EPO_QUOTA_WINDOW_UNCERTAIN", "access_limited",
                "Persisted EPO weekly window is ambiguous; automatic reset is disabled",
            )
        if stored_window.get("id") != current_window["id"]:
            current_start = _parse_timestamp(current_window["start"])
            if _utc(now) >= stored_end and current_start >= stored_end:
                return self._fresh_state(now)
            raise ProviderError(
                "EPO_QUOTA_WINDOW_UNCERTAIN", "access_limited",
                "EPO weekly quota window cannot be reset with the available clock evidence",
            )
        if (
            stored_start != _parse_timestamp(current_window["start"])
            or stored_end != _parse_timestamp(current_window["end"])
        ):
            raise ProviderError(
                "EPO_QUOTA_WINDOW_UNCERTAIN", "access_limited",
                "Persisted EPO weekly window does not match the deterministic UTC boundary",
            )

        # A stricter runtime config takes effect immediately.  A looser config
        # never expands an already-open weekly allowance.
        state["free_limit_bytes"] = min(state["free_limit_bytes"], self.free_limit)
        state["stop_margin_bytes"] = max(state["stop_margin_bytes"], self.stop_margin)
        state["stop_at_bytes"] = min(
            state["stop_at_bytes"],
            state["free_limit_bytes"] - state["stop_margin_bytes"],
            self.stop_at,
        )
        state["reservation_bytes"] = max(state["reservation_bytes"], self.estimate)
        return state

    def _write_locked(self, state: dict[str, Any], now: datetime) -> None:
        state["updated_at"] = _now_iso(now)
        fd, temporary = tempfile.mkstemp(prefix=".epo-quota.", dir=str(self.root))
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                # Windows has no fchmod; mkstemp inherits the user's directory
                # ACL there. Keep the descriptor owned by the context on errors.
                if hasattr(os, "fchmod"):
                    os.fchmod(handle.fileno(), 0o600)
                json.dump(state, handle, sort_keys=True, separators=(",", ":"))
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.path)
            try:
                self.path.chmod(0o600)
            except OSError:
                pass
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    @staticmethod
    def _reserved_bytes(state: dict[str, Any]) -> int:
        return sum(int(item["bytes"]) for item in state["reservations"].values())

    @classmethod
    def _effective_bytes(cls, state: dict[str, Any]) -> int:
        return (
            int(state["registered_used_bytes"])
            + int(state["unconfirmed_consumed_bytes"])
            + cls._reserved_bytes(state)
        )

    def reserve(self, request_identity: str = "") -> str:
        """Atomically reserve the configured worst-case response before HTTP."""
        now = _utc(self._now())
        with self._locked():
            state = self._load_locked(now)
            if state.get("stop_required") is True:
                raise ProviderError(
                    str(state.get("stop_code") or "FREE_QUOTA_STOP_THRESHOLD"),
                    "access_limited",
                    "EPO OPS account is stopped by the shared registered-free quota ledger",
                )
            if int(state.get("paying_used_bytes") or 0) > 0:
                raise ProviderError(
                    "PAID_QUOTA_USAGE_DETECTED", "access_limited",
                    "EPO OPS reported paying-quota usage; further requests are disabled",
                )
            reservation_bytes = max(int(state["reservation_bytes"]), self.estimate)
            projected = self._effective_bytes(state) + reservation_bytes
            if projected >= int(state["stop_at_bytes"]):
                state["stop_required"] = True
                state["stop_code"] = "FREE_QUOTA_STOP_THRESHOLD"
                self._write_locked(state, now)
                raise ProviderError(
                    "FREE_QUOTA_STOP_THRESHOLD", "access_limited",
                    "EPO OPS request was stopped before the shared free weekly threshold",
                )
            reservation_id = secrets.token_hex(16)
            state["reservations"][reservation_id] = {
                "bytes": reservation_bytes,
                "created_at": _now_iso(now),
                "pid": os.getpid(),
                "request_fingerprint": hashlib.sha256(
                    ("epo-request\x00" + str(request_identity or "")).encode("utf-8")
                ).hexdigest(),
            }
            self._write_locked(state, now)
            return reservation_id

    def settle(
        self,
        reservation_id: str,
        *,
        headers: dict[str, Any] | None = None,
        response_bytes: int = 0,
        error_code: str = "",
    ) -> dict[str, Any]:
        """Release a reservation into authoritative or conservative usage state."""
        now = _utc(self._now())
        headers = headers or {}
        hard_error = ""
        with self._locked():
            state = self._load_locked(now)
            reservation = state["reservations"].pop(reservation_id, None)
            if not isinstance(reservation, dict):
                raise ProviderError(
                    "EPO_QUOTA_RESERVATION_UNKNOWN", "access_limited",
                    "EPO quota reservation is missing; further accounting is unsafe",
                )
            reserved = int(reservation["bytes"])
            registered_used = _header_int(headers, "X-RegisteredQuotaPerWeek-Used")
            paying_used = _header_int(headers, "X-RegisteredPayingQuotaPerWeek-Used")
            rejection = next(
                (
                    str(value) for key, value in headers.items()
                    if str(key).casefold() == "x-rejection-reason"
                ),
                "",
            )

            if registered_used is not None:
                conservative_baseline = (
                    int(state["registered_used_bytes"])
                    + int(state["unconfirmed_consumed_bytes"])
                )
                state["registered_usage_observed"] = True
                state["registered_used_bytes"] = max(conservative_baseline, registered_used)
                state["unconfirmed_consumed_bytes"] = 0
            else:
                # Without an authoritative header, assume the entire worst-case
                # reservation was consumed, even on a failed/ambiguous request.
                state["unconfirmed_consumed_bytes"] += max(
                    reserved, max(int(response_bytes), 0),
                )

            if paying_used is not None:
                state["paying_used_bytes"] = max(
                    int(state["paying_used_bytes"]), paying_used,
                )
                if paying_used > 0:
                    hard_error = "PAID_QUOTA_USAGE_DETECTED"
            if "quota" in rejection.casefold() or error_code in {
                "FREE_QUOTA_EXHAUSTED", "PAID_PLAN_REQUIRED",
            }:
                hard_error = (
                    "PAID_QUOTA_USAGE_DETECTED"
                    if error_code == "PAID_PLAN_REQUIRED"
                    else "FREE_QUOTA_EXHAUSTED"
                )
            if hard_error:
                state["stop_required"] = True
                state["stop_code"] = hard_error
            elif (
                int(state["registered_used_bytes"])
                + int(state["unconfirmed_consumed_bytes"])
                + max(int(state["reservation_bytes"]), self.estimate)
                >= int(state["stop_at_bytes"])
            ):
                state["stop_required"] = True
                state["stop_code"] = "FREE_QUOTA_STOP_THRESHOLD"

            self._write_locked(state, now)
            safe_state = json.loads(json.dumps(state))

        if hard_error:
            detail = (
                "EPO OPS reported paying-quota usage; all further requests are disabled"
                if hard_error == "PAID_QUOTA_USAGE_DETECTED"
                else "EPO OPS reported that its registered free quota is exhausted"
            )
            raise ProviderError(hard_error, "access_limited", detail)
        return safe_state

    def snapshot(self) -> dict[str, Any]:
        """Read the current safe state and perform only a provable week rollover."""
        now = _utc(self._now())
        with self._locked():
            state = self._load_locked(now)
            if not self.path.is_file() or state["window"]["id"] == iso_week_window(now)["id"]:
                self._write_locked(state, now)
            return json.loads(json.dumps(state))
