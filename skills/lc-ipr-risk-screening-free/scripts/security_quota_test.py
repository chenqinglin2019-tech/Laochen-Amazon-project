#!/usr/bin/env python3
"""Offline credential-source and shared EPO quota-ledger tests."""

from __future__ import annotations

import json
import multiprocessing
import os
import re
import stat
import subprocess
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import common
import epo_ops_client
import run_api_plan
from epo_quota_ledger import EpoQuotaLedger, account_fingerprint
from offline_test_support import isolated_test_environment
from provider_utils import ProviderError


def quota_config(*, limit: int = 1000, margin: int = 100, estimate: int = 500) -> dict:
    return {
        "free_policy": {"allow_overage": False},
        "providers": {
            "epo_ops": {
                "allow_overage": False,
                "documented_free_bytes_per_week": limit,
                "free_stop_margin_bytes": margin,
                "estimated_max_response_bytes_per_query": estimate,
            },
        },
    }


def expect_error(call, code: str) -> None:
    try:
        call()
    except ProviderError as exc:
        assert exc.code == code, (exc.code, exc.detail)
    else:
        raise AssertionError(f"Expected ProviderError {code}")


def _reserve_worker(
    root: str, config: dict, key: str, identity: str,
    start: multiprocessing.synchronize.Event, queue: multiprocessing.queues.Queue,
) -> None:
    start.wait(10)
    try:
        reservation = EpoQuotaLedger(
            config, key, ledger_dir=Path(root),
        ).reserve(identity)
    except ProviderError as exc:
        queue.put(("blocked", exc.code))
    else:
        queue.put(("reserved", reservation))


def test_credentials() -> None:
    """Use only temporary local credentials, never the installed Skill files."""
    with tempfile.TemporaryDirectory(prefix="ipr-local-credentials-") as raw:
        root = Path(raw)
        (root / "config.json").write_text(
            json.dumps({"backend_url": "https://backend.example.test", "backend_token": "local-backend-fixture"}),
            encoding="utf-8",
        )
        (root / "config.json").chmod(0o600)
        (root / ".env").write_text("EPO_OPS_CONSUMER_KEY=local-epo-fixture\n", encoding="utf-8")
        (root / ".env").chmod(0o600)
        environment = {
            "LC_IPR_TEST_MODE": "", "LC_IPR_OFFLINE_TESTS": "",
            "LAOCHEN_BACKEND_TOKEN": "ignored-environment-fixture",
            "EPO_OPS_CONSUMER_KEY": "ignored-environment-fixture",
        }
        with (
            patch.object(common, "skill_root", return_value=root),
            patch.dict(os.environ, environment),
            patch.object(subprocess, "run", side_effect=AssertionError("Credential lookup must not run Keychain")),
        ):
            assert common.credential({}, "backend_token") == "local-backend-fixture"
            assert common.credential({}, "epo_consumer_key") == "local-epo-fixture"
            (root / "config.json").unlink()
            (root / ".env").unlink()
            assert common.credential({}, "backend_token") == ""
            assert common.credential({}, "epo_consumer_key") == ""
        for marker in ("LC_IPR_TEST_MODE", "LC_IPR_OFFLINE_TESTS"):
            with (
                patch.dict(os.environ, {marker: "1"}),
                patch.object(common, "skill_root", side_effect=AssertionError("Offline lookup must not open local files")),
            ):
                assert common.credential({}, "backend_token") == ""
                assert common.credential({}, "epo_consumer_key") == ""


def test_cross_process_reservation_and_restart() -> None:
    config = quota_config()
    key = "offline-account-one"
    with tempfile.TemporaryDirectory(prefix="ipr-epo-ledger-race-") as raw:
        root = Path(raw)
        context = multiprocessing.get_context("fork" if os.name == "posix" else "spawn")
        start = context.Event()
        queue = context.Queue()
        workers = [
            context.Process(
                target=_reserve_worker,
                args=(str(root), config, key, f"task-{index}", start, queue),
            )
            for index in range(2)
        ]
        for worker in workers:
            worker.start()
        start.set()
        results = [queue.get(timeout=10) for _ in workers]
        for worker in workers:
            worker.join(10)
            assert worker.exitcode == 0
        assert [status for status, _ in results].count("reserved") == 1, results
        assert [status for status, _ in results].count("blocked") == 1, results
        assert next(value for status, value in results if status == "blocked") == "FREE_QUOTA_STOP_THRESHOLD"

        # A new object represents a restarted task/process.  The persisted
        # reservation/stop remains authoritative until a provable week reset.
        restarted = EpoQuotaLedger(config, key, ledger_dir=root)
        expect_error(lambda: restarted.reserve("task-after-restart"), "FREE_QUOTA_STOP_THRESHOLD")

        ledger_paths = list(root.glob("*.json"))
        assert len(ledger_paths) == 1
        assert key not in ledger_paths[0].name
        assert stat.S_IMODE(ledger_paths[0].stat().st_mode) == 0o600
        assert all(stat.S_IMODE(path.stat().st_mode) == 0o600 for path in root.glob("*.lock"))
        content = ledger_paths[0].read_text(encoding="utf-8")
        assert key not in content
        assert "offline-account" not in content
        state = json.loads(content)
        assert state["account_fingerprint"] == account_fingerprint(key)
        assert re.fullmatch(r"[0-9a-f]{64}", state["account_fingerprint"])
        assert not any(
            marker in name.casefold()
            for name in state
            for marker in ("consumer_key", "consumer_secret", "credential")
        )


def test_paid_header_and_week_window() -> None:
    config = quota_config(limit=5000, margin=500, estimate=500)
    key = "offline-account-two"
    monday = datetime(2026, 9, 7, 12, tzinfo=timezone.utc)
    clock = {"value": monday}
    with tempfile.TemporaryDirectory(prefix="ipr-epo-ledger-paid-") as raw:
        root = Path(raw)
        manager = EpoQuotaLedger(
            config, key, ledger_dir=root, now=lambda: clock["value"],
        )
        failed_reservation = manager.reserve("ambiguous-network-failure")
        failed_state = manager.settle(
            failed_reservation, error_code="PROVIDER_NETWORK_ERROR",
        )
        assert failed_state["reservations"] == {}
        assert failed_state["unconfirmed_consumed_bytes"] == config["providers"]["epo_ops"]["estimated_max_response_bytes_per_query"]
        reservation = manager.reserve("paid-header")
        expect_error(
            lambda: manager.settle(
                reservation,
                headers={
                    "X-RegisteredQuotaPerWeek-Used": "100",
                    "X-RegisteredPayingQuotaPerWeek-Used": "1",
                },
                response_bytes=100,
            ),
            "PAID_QUOTA_USAGE_DETECTED",
        )
        expect_error(lambda: manager.reserve("same-week"), "PAID_QUOTA_USAGE_DETECTED")

        # A clearly later ISO week resets the registered allowance.  A clock
        # that cannot prove a non-overlapping week is rejected instead.
        clock["value"] = monday + timedelta(days=7)
        next_week = manager.reserve("next-week")
        assert next_week
        ledger_path = next(root.glob("*.json"))
        state = json.loads(ledger_path.read_text(encoding="utf-8"))
        state["window"]["id"] = "ambiguous"
        ledger_path.write_text(json.dumps(state), encoding="utf-8")
        expect_error(lambda: manager.snapshot(), "EPO_QUOTA_WINDOW_UNCERTAIN")


def test_ops_client_reserves_before_offline_http() -> None:
    config = quota_config(limit=5000, margin=500, estimate=500)
    config["http"] = {"timeout_seconds": 1, "retries": 9}
    key = "offline-account-client"
    calls: list[dict[str, object]] = []
    with tempfile.TemporaryDirectory(prefix="ipr-epo-client-ledger-") as raw:
        root = Path(raw)

        def manager_factory(selected_config: dict, selected_key: str) -> EpoQuotaLedger:
            assert selected_config is config and selected_key == key
            return EpoQuotaLedger(config, key, ledger_dir=root)

        def offline_http(url: str, **kwargs: object) -> tuple[int, dict[str, str], bytes]:
            calls.append({"url": url, **kwargs})
            # The reservation must already be durable before the HTTP attempt.
            state = json.loads(next(root.glob("*.json")).read_text(encoding="utf-8"))
            assert len(state["reservations"]) == 1
            return 200, {
                "X-RegisteredQuotaPerWeek-Used": "700",
                "X-RegisteredPayingQuotaPerWeek-Used": "0",
            }, b"<world-patent-data/>"

        with (
            patch.object(
                epo_ops_client, "settings",
                return_value=(config, "https://ops.epo.org/3.2/rest-services", "unused", key, "unused"),
            ),
            patch.object(epo_ops_client, "access_token", return_value=("memory-token", {})),
            patch.object(epo_ops_client, "EpoQuotaLedger", side_effect=manager_factory),
            patch.object(epo_ops_client, "http_request", side_effect=offline_http),
        ):
            body, headers = epo_ops_client.ops_get("published-data/test", "1-2")
        assert body == b"<world-patent-data/>"
        assert headers["X-RegisteredQuotaPerWeek-Used"] == "700"
        assert len(calls) == 1 and calls[0]["retries"] == 0
        state = json.loads(next(root.glob("*.json")).read_text(encoding="utf-8"))
        assert state["reservations"] == {}
        assert state["registered_used_bytes"] == 700
        assert "memory-token" not in json.dumps(state)


def test_plan_runner_reads_shared_account_state() -> None:
    config = quota_config()
    key = "offline-account-runner"
    with tempfile.TemporaryDirectory(prefix="ipr-epo-runner-ledger-") as raw:
        root = Path(raw)
        EpoQuotaLedger(config, key, ledger_dir=root).reserve("other-task")
        with (
            patch.dict(os.environ, {
                "LC_IPR_TEST_MODE": "1",
                "LC_IPR_EPO_LEDGER_DIR": str(root),
            }),
            patch.object(run_api_plan, "credential", return_value=key),
        ):
            reason = run_api_plan.epo_free_quota_block_reason(
                root, {"source_runs": []}, config, 2,
            )
        assert reason == "EPO_SHARED_FREE_QUOTA_NEAR_LIMIT"


def main() -> None:
    with isolated_test_environment():
        test_credentials()
        test_cross_process_reservation_and_restart()
        test_paid_header_and_week_window()
        test_ops_client_reserves_before_offline_http()
        test_plan_runner_reads_shared_account_state()
    print("security/quota offline tests passed")


if __name__ == "__main__":
    main()
