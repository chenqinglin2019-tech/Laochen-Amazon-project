import test from "node:test";
import assert from "node:assert/strict";
import path from "node:path";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";

const TOOL_DIR = path.dirname(fileURLToPath(import.meta.url));
const SKILL_ROOT = path.resolve(TOOL_DIR, "..", "..");
const SCRIPTS_DIR = path.join(SKILL_ROOT, "scripts");

const PYTHON_TEST = String.raw`
import io
import json
import subprocess
import sys
import tempfile
import threading
import time
import urllib.parse
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

import jpo_api_client as jpo
import run_api_plan as runner
from common import build_coverage_requirements
from provider_utils import ProviderError


# Credential fixtures stay inside this offline child; production readers are
# never pointed at a test credential path or enabled through environment values.
credential_fixture = patch.object(jpo, "credential", side_effect=lambda config, name: {
    "jpo_api_username": "test-user", "jpo_api_password": "test-password",
}.get(name, ""))
credential_fixture.start()


def response(result):
    body = json.dumps({"result": result}).encode("utf-8")
    return {"result": result}, {}, body


fixed = {"URL": "https://www.j-platpat.inpit.go.jp/c1801/PU/JP-2020008423/15/ja"}
assert jpo.CASE_NUMBER_KINDS == {
    "patent": {"application", "publication", "registration"},
    "design": {"application", "registration"},
    "trademark": {"application", "registration"},
}
assert jpo.normalize_case_number("JP2021-022359A1", "publication") == "2021022359"
assert jpo.normalize_case_number("特許第6691280号", "registration") == "6691280"
patent_progress = {"applicationNumber": "2020-008423", "inventionTitle": "Test invention"}
patent_registration = {
    "registrationNumber": "7654321",
    "rightPersonInformation": [{"rightPersonName": "Test owner"}],
    "updateDate": "20260903",
}
normalized, complete, missing = jpo.normalize_verification(
    "patent", "2020008423", patent_progress, patent_registration, fixed,
)
assert complete and not missing
assert normalized["updated_date"] == "2026-09-03"
assert normalized["official_verification"]["url"].startswith("https://www.j-platpat.inpit.go.jp/")

pending_progress = {
    "applicationNumber": "2020008423", "inventionTitle": "Pending invention",
    "updateDate": "20260903",
    "applicantAttorney": [
        {"applicantAttorneyClass": "2", "name": "Attorney must not become owner"},
        {"applicantAttorneyClass": "1", "name": "Actual applicant"},
    ],
}
pending, complete, missing = jpo.normalize_verification(
    "patent", "2020008423", pending_progress, {}, fixed,
)
assert not complete and "legal_status" in missing
assert pending["owners"] == ["Actual applicant"]
assert "Attorney must not become owner" not in pending["owners"]

registered_without_owner, complete, missing = jpo.normalize_verification(
    "patent", "2020008423", pending_progress,
    {"registrationNumber": "7654321", "updateDate": "20260903"}, fixed,
)
assert not complete and "registered_right_person" in missing
assert registered_without_owner["official_verification"]["owner_basis"] == "application_party"

without_update = dict(patent_registration)
without_update.pop("updateDate")
_, complete, missing = jpo.normalize_verification(
    "patent", "2020008423", patent_progress, without_update, fixed,
)
assert not complete and "updated_date" in missing

design_progress = {"applicationNumber": "2020008423", "designArticle": "Test design"}
design_registration = {**patent_registration, "designClass": "C3-123"}
_, complete, missing = jpo.normalize_verification(
    "design", "2020008423", design_progress, design_registration, fixed,
)
assert not complete and "official_media" in missing and "design_class" not in missing
without_design_class = dict(patent_registration)
_, complete, missing = jpo.normalize_verification(
    "design", "2020008423", design_progress, without_design_class, fixed,
)
assert not complete and "design_class" in missing

trademark_progress = {"applicationNumber": "2020008423", "trademarkForDisplay": "TEST MARK"}
trademark_registration = {
    **patent_registration,
    "goodsServiceInformation": [{"goodsServiceClass": "21", "goodsServiceName": "Containers"}],
}
_, complete, missing = jpo.normalize_verification(
    "trademark_word", "2020008423", trademark_progress, trademark_registration, fixed,
)
assert complete and not missing
without_class = dict(patent_registration)
_, complete, missing = jpo.normalize_verification(
    "trademark_word", "2020008423", trademark_progress, without_class, fixed,
)
assert not complete and "goods_service_class" in missing

jpo._TOKEN_CACHE = None
jpo._EXHAUSTED_ENDPOINTS.clear()
network_calls = []
def no_network(*args, **kwargs):
    network_calls.append(args[0])
    raise AssertionError("utility models must not touch auth or HTTP")
client = jpo.JpoApiClient(config={"providers": {"jpo_api": {}}}, transport=no_network)
try:
    client.verify("utility_model", "2020008423")
    raise AssertionError("utility model should be rejected")
except ProviderError as exc:
    assert exc.code == "JPO_API_UNSUPPORTED_RIGHT_TYPE"
assert network_calls == []

jpo._TOKEN_CACHE = None
jpo._EXHAUSTED_ENDPOINTS.clear()
no_data_calls = []
def no_data_transport(url, **kwargs):
    no_data_calls.append(url)
    if url == jpo.DEFAULT_AUTH_URL:
        return {"access_token": "token", "refresh_token": "refresh", "expires_in": 3600}, {}, b"{}"
    return response({"statusCode": "107", "remainAccessCount": "99"})
client = jpo.JpoApiClient(config={"providers": {"jpo_api": {}}}, transport=no_data_transport)
value, quota, raw, complete, reason = client.verify("patent", "2020008423")
assert value is None and not complete and reason == "no_applicable_data"
assert len([url for url in no_data_calls if url != jpo.DEFAULT_AUTH_URL]) == 1

jpo._TOKEN_CACHE = None
jpo._EXHAUSTED_ENDPOINTS.clear()
conversion_calls = []
def conversion_transport(url, **kwargs):
    conversion_calls.append(url)
    if url == jpo.DEFAULT_AUTH_URL:
        return {"access_token": "token", "refresh_token": "refresh", "expires_in": 3600}, {}, b"{}"
    if "/case_number_reference/publication/2021022359" in url:
        return response({
            "statusCode": "100", "remainAccessCount": 0,
            "data": {
                "applicationNumber": "2020-008423",
                "publicationNumber": "JP2021-022359A1",
                "nationalPublicationNumber": "",
                "registrationNumber": "7654321",
            },
        })
    if "/app_progress/2020008423" in url:
        return response({"statusCode": "100", "remainAccessCount": "799", "data": patent_progress})
    if "/registration_info/2020008423" in url:
        return response({"statusCode": "100", "remainAccessCount": "399", "data": patent_registration})
    if "/jpp_fixed_address/2020008423" in url:
        return response({"statusCode": "100", "remainAccessCount": "399", "data": fixed})
    raise AssertionError(url)
client = jpo.JpoApiClient(
    config={"providers": {"jpo_api": {"daily_limits": {"number_reference": 100}}}},
    transport=conversion_transport,
)
converted, quota, raw, complete, missing = client.verify(
    "patent", "JP2021-022359A1", number_kind="publication",
)
assert complete and not missing
assert converted["application_number"] == "2020008423"
assert converted["publication_number"] == "2021022359"
assert converted["requested_number"] == "2021022359"
assert converted["requested_number_kind"] == "publication"
assert converted["number_reference"]["publicationNumber"] == "JP2021-022359A1"
assert quota["case_number_reference"]["remaining"] == "0"
assert json.loads(raw)["endpoints"]["case_number_reference"]["result"]["statusCode"] == "100"

jpo._TOKEN_CACHE = None
jpo._EXHAUSTED_ENDPOINTS.clear()
quota_calls = []
def quota_transport(url, **kwargs):
    quota_calls.append(url)
    if url == jpo.DEFAULT_AUTH_URL:
        return {"access_token": "token", "refresh_token": "refresh", "expires_in": 3600}, {}, b"{}"
    return response({
        "statusCode": "100", "remainAccessCount": "0",
        "data": {"applicationNumber": "2020008423"},
    })
client = jpo.JpoApiClient(config={"providers": {"jpo_api": {}}}, transport=quota_transport)
client._get("patent", "app_progress", "2020008423")
calls_before_stop = len(quota_calls)
try:
    client._get("patent", "app_progress", "2020008423")
    raise AssertionError("exhausted endpoint should stop")
except ProviderError as exc:
    assert exc.code == "FREE_QUOTA_EXHAUSTED"
assert len(quota_calls) == calls_before_stop

jpo._TOKEN_CACHE = None
jpo._EXHAUSTED_ENDPOINTS.clear()
with tempfile.TemporaryDirectory() as temporary:
    task_dir = Path(temporary)
    (task_dir / "evidence.json").write_text(json.dumps({
        "source_runs": [{
            "provider": "jpo_api", "finished_at": jpo._jpo_today() + "T01:02:03+09:00",
            "status": "success", "quota": {"app_progress": {"remaining": 0}},
        }],
    }), encoding="utf-8")
    persisted_calls = []
    def persisted_transport(*args, **kwargs):
        persisted_calls.append(args[0])
        raise AssertionError("persisted remaining=0 must stop before authentication")
    client = jpo.JpoApiClient(
        config={"providers": {"jpo_api": {"daily_limits": {"progress": 800}}}},
        transport=persisted_transport,
    )
    try:
        client.verify("patent", "2020008423", task_dir=task_dir)
        raise AssertionError("persisted quota exhaustion should stop")
    except ProviderError as exc:
        assert exc.code == "FREE_QUOTA_EXHAUSTED"
    assert persisted_calls == []

jpo._TOKEN_CACHE = None
jpo._EXHAUSTED_ENDPOINTS.clear()
generic_calls = []
def generic_transport(*args, **kwargs):
    generic_calls.append(args[0])
    raise AssertionError("generic trademark must stop before authentication")
client = jpo.JpoApiClient(config={"providers": {"jpo_api": {}}}, transport=generic_transport)
try:
    client.verify("trademark", "2020008423")
    raise AssertionError("generic trademark should be rejected")
except ProviderError as exc:
    assert exc.code == "JPO_RIGHT_TYPE_INVALID"
assert generic_calls == []

try:
    client.verify("design", "2021022359", number_kind="publication")
    raise AssertionError("design publication-number conversion should be rejected")
except ProviderError as exc:
    assert exc.code == "JPO_NUMBER_KIND_INVALID"
assert generic_calls == []

jpo._TOKEN_CACHE = None
jpo._EXHAUSTED_ENDPOINTS.clear()
auth_grants = []
def refresh_transport(url, **kwargs):
    if url == jpo.DEFAULT_AUTH_URL:
        form = urllib.parse.parse_qs(kwargs["data"].decode("utf-8"))
        grant = form["grant_type"][0]
        auth_grants.append(grant)
        token = "token-1" if grant == "password" else "token-2"
        return {"access_token": token, "refresh_token": "refresh", "expires_in": 3600}, {}, b"{}"
    endpoint = url.rsplit("/", 2)[-2]
    token = kwargs.get("headers", {}).get("Authorization")
    if endpoint == "app_progress" and token == "Bearer token-1":
        raise ProviderError("AUTH_FAILED", "access_limited", "expired")
    if endpoint == "app_progress":
        return response({
            "statusCode": "100", "remainAccessCount": "99",
            "data": patent_progress,
        })
    if endpoint == "registration_info":
        raise ProviderError("AUTH_FAILED", "access_limited", "expired again")
    raise AssertionError(endpoint)
client = jpo.JpoApiClient(config={"providers": {"jpo_api": {}}}, transport=refresh_transport)
try:
    client.verify("patent", "2020008423")
    raise AssertionError("a second endpoint 401 must not trigger another refresh")
except ProviderError as exc:
    assert exc.code == "AUTH_FAILED"
assert auth_grants == ["password", "refresh_token"]

scripts = Path(jpo.__file__).resolve().parent
euipo_command = runner.command_for(scripts, Path("/tmp/task"), "euipo_trademark", {
    "q": "猫工房", "query": "wordMarkSpecification.verbalElement==*猫工房*",
    "right_type": "trademark_word", "operation": "search", "query_id": "Q-EU-1",
})
assert euipo_command[euipo_command.index("--right-type") + 1] == "trademark_word"
assert euipo_command[euipo_command.index("--rsql") + 1] == "wordMarkSpecification.verbalElement==*猫工房*"
assert euipo_command[euipo_command.index("--query-id") + 1] == "Q-EU-1"
epo_command = runner.command_for(scripts, Path("/tmp/task"), "epo_ops", {
    "q": "mouse pad", "right_type": "design", "operation": "search", "jurisdiction": "JP",
})
assert epo_command[epo_command.index("--right-type") + 1] == "design"
jpo_command = runner.command_for(scripts, Path("/tmp/task"), "jpo_api", {
    "operation": "candidate_verification", "right_type": "patent",
    "number": "2021022359", "number_kind": "publication",
    "candidate_id": "CAN-JP-1", "query_id": "Q-JP-1",
})
assert jpo_command[jpo_command.index("--number") + 1] == "2021022359"
assert jpo_command[jpo_command.index("--number-kind") + 1] == "publication"
assert jpo_command[jpo_command.index("--query-id") + 1] == "Q-JP-1"

with tempfile.TemporaryDirectory() as temporary:
    task_dir = Path(temporary)
    policy = {
        "mode": "official_free_only", "allow_registration": True,
        "allow_commercial_freemium": True,
        "commercial_freemium_mode": "explicit_opt_in",
        "commercial_freemium_allowlist": ["serper"],
        "allow_paid": False, "allow_overage": False,
        "on_quota_exhausted": "stop_and_report",
    }
    (task_dir / "task.json").write_text(json.dumps({
        "schema_version": "2.3-free", "task_id": "TASK-JPO-SEQUENTIAL",
        "free_policy": policy, "target_jurisdictions": ["JP", "EU"],
        "coverage_requirements": build_coverage_requirements(["JP", "EU"]),
    }), encoding="utf-8")
    (task_dir / "evidence.json").write_text(json.dumps({"source_runs": []}), encoding="utf-8")
    (task_dir / "search-plan.json").write_text(json.dumps({
        "schema_version": "2.3-free", "task_id": "TASK-JPO-SEQUENTIAL",
        "free_policy": policy,
        "queries": {
            "euipo_trademark": [{
                "query_id": "Q-EU-1", "q": "mark", "operation": "search",
                "jurisdiction": "EU", "right_type": "trademark_word",
                "wave": 1, "required": True,
            }],
            "jpo_api": [
                {
                    "query_id": "Q-JP-1", "q": "2020008423", "number": "2020008423",
                    "number_kind": "application", "candidate_id": "CAN-1",
                    "jurisdiction": "JP", "right_type": "patent",
                    "operation": "candidate_verification",
                    "wave": 1, "required": False, "execute_by_default": True,
                },
                {
                    "query_id": "Q-JP-2", "q": "2020008424", "number": "2020008424",
                    "number_kind": "application", "candidate_id": "CAN-2",
                    "jurisdiction": "JP", "right_type": "patent",
                    "operation": "candidate_verification",
                    "wave": 1, "required": False, "execute_by_default": True,
                },
            ],
        },
    }), encoding="utf-8")
    seen_commands = []
    active_jpo = 0
    max_active_jpo = 0
    state_lock = threading.Lock()
    original_run = runner.subprocess.run
    original_argv = sys.argv
    def fake_run(command, **kwargs):
        global active_jpo, max_active_jpo
        is_jpo = any(str(part).endswith("jpo_api_client.py") for part in command)
        seen_commands.append(list(command))
        if is_jpo:
            with state_lock:
                active_jpo += 1
                max_active_jpo = max(max_active_jpo, active_jpo)
            time.sleep(0.01)
            with state_lock:
                active_jpo -= 1
        return subprocess.CompletedProcess(command, 0, '{"status":"success"}\n', "")
    try:
        runner.subprocess.run = fake_run
        sys.argv = ["run_api_plan.py", "--task-dir", str(task_dir), "--wave", "1"]
        with redirect_stdout(io.StringIO()):
            runner.main()
    finally:
        runner.subprocess.run = original_run
        sys.argv = original_argv
    jpo_commands = [
        command for command in seen_commands
        if any(str(part).endswith("jpo_api_client.py") for part in command)
    ]
    assert len(jpo_commands) == 2, "execute_by_default optional JPO actions must be scheduled"
    assert max_active_jpo == 1, "JPO subprocesses must be sequential"
credential_fixture.stop()
print("ok")
`;

test("JPO client enforces completeness, no-data fallback, quota stop, and one refresh", () => {
  const result = spawnSync("python3", ["-c", PYTHON_TEST], {
    cwd: SKILL_ROOT,
    encoding: "utf8",
    env: {
      ...process.env,
      PYTHONPATH: SCRIPTS_DIR,
      LC_IPR_OFFLINE_TESTS: "1",
      PYTHONDONTWRITEBYTECODE: "1",
    },
  });
  assert.equal(result.status, 0, result.stderr || result.stdout);
  assert.equal(result.stdout.trim(), "ok");
});
