#!/usr/bin/env python3
"""Shared deterministic helpers for LC IPR Risk Screening Free."""

from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import stat
import struct
import subprocess
import tempfile
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "2.3-free"
CURRENT_SCHEMA_VERSION = "2.4-free"
AUTOMATION_POLICY_REVISION = "automation-first-v1"
RECALL_INTEGRITY_REVISION = "recall-integrity-v1"
DECISION_PLAN_META_KEYS = {
    "decision_workflow_revision", "scenario_id", "scenario_sha256", "scenario_bindings",
    "triage_decision_id", "triage_decision_sha256", "triage_jurisdiction",
    "triage_candidate_id", "action_purpose", "evidence_obligation_id", "triage_action_id",
    "workflow_correction_revision", "required_facts", "reading_scope",
}
LEGACY_SCHEMA_VERSIONS = {"2.1-free", "2.2-free"}
SUPPORTED_SCHEMA_VERSIONS = {*LEGACY_SCHEMA_VERSIONS, SCHEMA_VERSION, CURRENT_SCHEMA_VERSION}
FREE_POLICY_REVISION = "optional-discovery-v1"
LEGACY_DEFAULT_DISCOVERY_REVISION = "default-discovery-v1"
WIPO_PROVIDERS = {"wipo_patentscope_browser"}
SERPER_PROVIDERS = {"serper_patents", "serper_web", "serper_images"}
SERPER_PROVIDER_OPERATIONS = {
    "serper_patents": "patents",
    "serper_web": "search",
    "serper_images": "images",
}
SERPER_PROVIDER_QUERY_CAPS = {
    "serper_patents": 4,
    "serper_web": 3,
    "serper_images": 3,
}
SERPER_FREE_ROLE = "discovery_only"
SERPER_FREE_MAX_QUERIES_PER_TASK = 10
SERPAPI_PROVIDER = "serpapi_google_patents"
SERPAPI_OPERATION = "search"
SERPAPI_FREE_ROLE = "discovery_only"
SERPAPI_FREE_MAX_QUERIES_PER_TASK = 3
SIGNA_PROVIDER = "signa"
SIGNA_OPERATION = "trademark_search"
SIGNA_FREE_ROLE = "discovery_only"
SIGNA_FREE_MAX_QUERIES_PER_TASK = 3
AUTHORIZED_FREE_COMMERCIAL_PROVIDERS = {
    *SERPER_PROVIDERS, SERPAPI_PROVIDER, SIGNA_PROVIDER, "serpapi_google_lens",
}
COMMERCIAL_PROVIDERS = {
    "serpapi_google_patents", "serper_patents", "serper_web", "serper_images",
    SIGNA_PROVIDER, "rapidapi_uspto_trademark",
    "serpapi_google_lens",
}
RIGHT_TYPES = {
    "patent", "utility_model", "design", "trademark_word",
    "trademark_figurative", "copyright", "enforcement", "trade_dress", "unregistered_design",
}
SOURCE_STATUSES = {
    "success", "no_result", "not_applicable", "needs_user_action",
    "access_limited", "failed",
}
TASK_STATES = {
    "pending", "preflight_credentials", "awaiting_browser", "preflight_evidence",
    "collecting", "ready_for_assessment", "assessing", "needs_review", "completed",
    "needs_user_action", "incomplete", "failed",
}
RISK_LEVELS = ["极低", "低", "中", "高", "极高"]
CONFIDENCE_LEVELS = ["低", "中", "高"]


def recall_integrity_enabled(task: dict[str, Any]) -> bool:
    """Opt new screening semantics in without reinterpreting frozen tasks."""
    revision = task.get("screening_revision")
    if revision not in (None, "", RECALL_INTEGRITY_REVISION):
        raise ValueError("UNSUPPORTED_SCREENING_REVISION: " + str(revision))
    return task.get("schema_version") == CURRENT_SCHEMA_VERSION and revision == RECALL_INTEGRITY_REVISION


MODULE_IDS = [
    "appearance_patent", "utility_patent", "pending_application", "word_mark",
    "figurative_trade_dress", "copyright_ip", "enforcement",
]
EU_COUNTRIES = {
    "AT", "BE", "BG", "HR", "CY", "CZ", "DE", "DK", "EE", "ES", "FI", "FR",
    "GR", "HU", "IE", "IT", "LT", "LU", "LV", "MT", "NL", "PL", "PT", "RO",
    "SE", "SI", "SK",
}
AMAZON_EU_COUNTRIES = {"BE", "DE", "ES", "FR", "IT", "NL", "PL", "SE"}
EU_UTILITY_MODEL_COUNTRIES = {"DE", "FR", "IT", "ES", "PL"}
MARKETPLACE_BY_HOST = {
    "amazon.com": "US", "amazon.ca": "CA", "amazon.com.mx": "MX",
    "amazon.co.uk": "GB", "amazon.de": "DE", "amazon.fr": "FR",
    "amazon.it": "IT", "amazon.es": "ES", "amazon.nl": "NL",
    "amazon.se": "SE", "amazon.pl": "PL", "amazon.com.be": "BE",
    "amazon.co.jp": "JP", "amazon.com.au": "AU",
}
PROVIDER_MODULES = {
    "epo_ops": ["appearance_patent", "utility_patent", "pending_application"],
    "wipo_patentscope_browser": ["appearance_patent", "utility_patent", "pending_application"],
    "espacenet_browser": ["appearance_patent", "utility_patent", "pending_application"],
    "serpapi_google_patents": ["appearance_patent", "utility_patent", "pending_application"],
    "serpapi_google_lens": ["appearance_patent", "figurative_trade_dress", "copyright_ip"],
    "epo_publication_server": ["utility_patent", "pending_application"],
    "oepm_api": ["utility_patent", "appearance_patent", "word_mark", "figurative_trade_dress"],
    "serper_patents": ["appearance_patent", "utility_patent", "pending_application"],
    "serper_web": ["enforcement", "copyright_ip"],
    "serper_images": ["figurative_trade_dress", "copyright_ip"],
    "signa": ["word_mark"],
    "rapidapi_uspto_trademark": ["word_mark", "figurative_trade_dress"],
    "uspto_tmsearch_browser": ["word_mark", "figurative_trade_dress"],
    "uspto_tsdr": ["word_mark", "figurative_trade_dress"],
    "uspto_patent_browser": ["appearance_patent", "utility_patent", "pending_application"],
    "euipo_trademark": ["word_mark", "figurative_trade_dress"],
    "euipo_design": ["appearance_patent", "figurative_trade_dress"],
    "euipo_esearch_browser": ["figurative_trade_dress"],
    "inpi_api": [
        "appearance_patent", "utility_patent", "pending_application",
        "word_mark", "figurative_trade_dress",
    ],
    "prv_open_data": [
        "appearance_patent", "utility_patent", "pending_application",
        "word_mark", "figurative_trade_dress",
    ],
    "jpo_api": [
        "appearance_patent", "utility_patent", "pending_application",
        "word_mark", "figurative_trade_dress",
    ],
    "jplatpat_browser": [
        "appearance_patent", "utility_patent", "pending_application",
        "word_mark", "figurative_trade_dress",
    ],
    "tmview_browser": ["word_mark", "figurative_trade_dress"],
    "designview_browser": ["appearance_patent", "figurative_trade_dress"],
    "epo_register_browser": ["appearance_patent", "utility_patent", "pending_application"],
    "public_web_browser": ["copyright_ip", "enforcement"],
    "official_registry_browser": MODULE_IDS,
    "amazon_browser": MODULE_IDS,
}


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def parse_iso(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def validate_checked_at(value: str, max_age_hours: int = 48) -> datetime:
    checked = parse_iso(value)
    now = datetime.now(timezone.utc)
    if checked.tzinfo is None:
        raise ValueError("checked_at must include a timezone")
    age = (now - checked.astimezone(timezone.utc)).total_seconds() / 3600
    if age < -0.1 or age > max_age_hours:
        raise ValueError(f"checked_at is outside the allowed {max_age_hours}-hour window")
    return checked


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8-sig") as handle:
        return json.load(handle)


def ensure_object(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object")
    return value


def atomic_write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        os.replace(temp_name, path)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)


def atomic_write_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
        os.replace(temp_name, path)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_json(payload: Any) -> str:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return sha256_bytes(raw)


def stable_id(prefix: str, *parts: str, length: int = 18) -> str:
    digest = hashlib.sha256("\x1f".join(parts).encode()).hexdigest()[:length]
    return f"{prefix}-{digest}"


def slugify(value: str, fallback: str = "task") -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9_-]+", "-", value.strip()).strip("-")
    return cleaned[:64] or fallback


def split_csv(value: str) -> list[str]:
    return [part.strip().upper() for part in value.split(",") if part.strip()]


def normalize_text(value: str) -> str:
    """Normalize identifiers/search text without deleting CJK characters."""
    normalized = unicodedata.normalize("NFKC", str(value or "")).casefold()
    return re.sub(r"[^\w]+", "", normalized, flags=re.UNICODE).replace("_", "")


def intrinsic_patent_right_type(
    jurisdiction: object, document_number: object, kind_code: object = "",
) -> str:
    """Return the right type that is intrinsic to an official document ID."""
    jurisdiction_value = str(jurisdiction or "").upper().strip()
    number = re.sub(r"[^A-Za-z0-9]", "", str(document_number or "")).upper()
    kind = re.sub(r"[^A-Za-z0-9]", "", str(kind_code or "")).upper()
    if not jurisdiction_value and len(number) >= 2:
        jurisdiction_value = number[:2]
    if jurisdiction_value == "WO" or number.startswith("WO"):
        # PCT publications are patent publications. A later national
        # utility-model effect must be established through a family member.
        return "patent"
    if jurisdiction_value == "US" or number.startswith("US"):
        if (
            kind.startswith("S")
            or re.match(r"^(?:USD|D)\d", number)
            or re.match(r"^US\d+S\d?$", number)
        ):
            return "design"
    if jurisdiction_value == "JP" or number.startswith("JP"):
        if kind.startswith(("U", "Y")) or re.search(r"(?:U|Y)\d?$", number):
            return "utility_model"
    return ""


def deep_merge(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    result = dict(base)
    for key, value in overlay.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def skill_root() -> Path:
    return Path(__file__).resolve().parents[1]


def load_skill_config() -> dict[str, Any]:
    """Load non-secret settings only.

    `config.json` and `config.local.json` are never credential sources.  A
    stale secret field may still be detected by preflight for migration and
    rotation, but it is intentionally ignored here.
    """
    config = dict(ensure_object(load_json(skill_root() / "config.json"), "config.json"))
    for name in ENV_CREDENTIALS:
        config.pop(name, None)
    config.pop("credentials", None)
    return config


ENV_CREDENTIALS = {
    "backend_token": "LAOCHEN_BACKEND_TOKEN",
    "epo_consumer_key": "EPO_OPS_CONSUMER_KEY",
    "epo_consumer_secret": "EPO_OPS_CONSUMER_SECRET",
    "signa_api_key": "SIGNA_API_KEY",
    "euipo_client_id": "EUIPO_CLIENT_ID",
    "euipo_client_secret": "EUIPO_CLIENT_SECRET",
    "jpo_api_username": "JPO_API_USERNAME",
    "jpo_api_password": "JPO_API_PASSWORD",
    "serper_api_key": "SERPER_API_KEY",
    "serpapi_api_key": "SERPAPI_API_KEY",
    "rapidapi_key": "RAPIDAPI_KEY",
    "inpi_username": "INPI_USERNAME",
    "inpi_password": "INPI_PASSWORD",
}

KEYCHAIN_SERVICE = "com.laochen.codex.lc-ipr-risk-screening-free"
KEYCHAIN_ACCOUNTS = dict(ENV_CREDENTIALS)
KEYCHAIN_SECURITY_COMMAND = "/usr/bin/security"
LOCAL_ENV_CREDENTIALS = {"signa_api_key", "serpapi_api_key"}
LOCAL_ENV_MAX_BYTES = 16 * 1024


def _keychain_credential(account: str) -> str:
    """Read one fixed-account macOS Keychain value without logging it."""
    if platform.system() != "Darwin" or not account:
        return ""
    try:
        result = subprocess.run(
            [
                KEYCHAIN_SECURITY_COMMAND, "find-generic-password",
                "-s", KEYCHAIN_SERVICE, "-a", account, "-w",
            ],
            text=True,
            capture_output=True,
            check=False,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    if result.returncode != 0:
        return ""
    return result.stdout.rstrip("\r\n")


def _local_env_credential(name: str, env_name: str) -> str:
    """Read explicitly allowed provider keys from a private Skill-root .env file.

    The file is deliberately not a general configuration or shell parser: it
    accepts only exact NAME=value rows for the two opt-in discovery providers,
    rejects symlinks and files readable by group/other users, and never alters
    the process environment. Cloud authorization and all other credentials keep
    their existing environment/Keychain-only policy.
    """
    if name not in LOCAL_ENV_CREDENTIALS or os.environ.get("LC_IPR_TEST_MODE") == "1":
        return ""
    path = skill_root() / ".env"
    try:
        metadata = path.lstat()
        if not stat.S_ISREG(metadata.st_mode) or stat.S_IMODE(metadata.st_mode) & 0o077:
            return ""
        if metadata.st_size > LOCAL_ENV_MAX_BYTES:
            return ""
        contents = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return ""
    pattern = re.compile(r"^([A-Z][A-Z0-9_]*)=(.*)$")
    for raw_line in contents.splitlines():
        match = pattern.fullmatch(raw_line.strip())
        if not match or match.group(1) != env_name:
            continue
        value = match.group(2).strip()
        if len(value) >= 2 and value[:1] == value[-1:] and value[:1] in {"'", '"'}:
            value = value[1:-1]
        return value
    return ""


def credential(config: dict[str, Any], name: str) -> str:
    """Resolve a credential from env, the approved private .env, or Keychain."""
    del config  # Non-secret configuration files are never credential sources.
    env_name = ENV_CREDENTIALS.get(name)
    if not env_name:
        return ""
    if os.environ.get(env_name):
        return os.environ[env_name]
    local_value = _local_env_credential(name, env_name)
    if local_value:
        return local_value
    return _keychain_credential(KEYCHAIN_ACCOUNTS[name])


def schema_of(task_or_schema: dict[str, Any] | str) -> str:
    return (
        str(task_or_schema.get("schema_version") or "")
        if isinstance(task_or_schema, dict)
        else str(task_or_schema or "")
    )


def is_legacy_schema(task_or_schema: dict[str, Any] | str) -> bool:
    return schema_of(task_or_schema) in LEGACY_SCHEMA_VERSIONS


def is_active_schema(task_or_schema: dict[str, Any] | str) -> bool:
    return schema_of(task_or_schema) in {SCHEMA_VERSION, CURRENT_SCHEMA_VERSION}


def is_v24(task_or_schema: dict[str, Any] | str) -> bool:
    return schema_of(task_or_schema) == CURRENT_SCHEMA_VERSION


def active_free_policy() -> dict[str, Any]:
    """Return the immutable zero-cash-cost execution policy for new tasks."""
    return {
        "mode": "official_free_only",
        "allow_registration": True,
        "allow_commercial_freemium": True,
        "commercial_freemium_mode": "explicit_opt_in",
        "commercial_freemium_default_enabled": [],
        "commercial_freemium_opt_in": ["serper", "signa", "serpapi"],
        "commercial_freemium_allowlist": ["serper", "signa", "serpapi"],
        "allow_paid": False,
        "allow_overage": False,
        "on_quota_exhausted": "stop_and_report",
    }


def _legacy_2_3_free_policies() -> tuple[dict[str, Any], ...]:
    """Policies frozen into pre-default-discovery 2.3 development tasks."""
    base = {
        "mode": "official_free_only",
        "allow_registration": True,
        "allow_commercial_freemium": True,
        "commercial_freemium_mode": "explicit_opt_in",
        "allow_paid": False,
        "allow_overage": False,
        "on_quota_exhausted": "stop_and_report",
    }
    return (
        {**base, "commercial_freemium_allowlist": ["serper"]},
        {**base, "commercial_freemium_allowlist": ["serper", "serpapi"]},
    )


def _legacy_default_discovery_policy() -> dict[str, Any]:
    """Policy briefly issued under the frozen default-discovery revision."""
    return {
        "mode": "official_free_only",
        "allow_registration": True,
        "allow_commercial_freemium": True,
        "commercial_freemium_mode": "default_bounded",
        "commercial_freemium_default_enabled": ["serper", "signa"],
        "commercial_freemium_opt_in": ["serpapi"],
        "commercial_freemium_allowlist": ["serper", "signa", "serpapi"],
        "allow_paid": False,
        "allow_overage": False,
        "on_quota_exhausted": "stop_and_report",
    }


def task_free_policy_valid(task: dict[str, Any]) -> bool:
    """Validate the current policy revision while preserving frozen 2.3 tasks."""
    if not is_active_schema(task):
        return False
    revision = str(task.get("free_policy_revision") or "")
    policy = task.get("free_policy")
    if is_v24(task):
        return revision == AUTOMATION_POLICY_REVISION and policy == active_free_policy()
    if revision == FREE_POLICY_REVISION:
        return policy == active_free_policy()
    if revision == LEGACY_DEFAULT_DISCOVERY_REVISION:
        return policy == _legacy_default_discovery_policy()
    if revision:
        return False
    return any(policy == legacy for legacy in _legacy_2_3_free_policies())


def plan_free_policy_matches_task(
    task: dict[str, Any], plan: dict[str, Any],
) -> bool:
    """Bind a plan to its task's frozen policy and policy revision."""
    return (
        task_free_policy_valid(task)
        and plan.get("free_policy") == task.get("free_policy")
        and str(plan.get("free_policy_revision") or "")
        == str(task.get("free_policy_revision") or "")
    )


def uses_default_commercial_discovery(task: dict[str, Any]) -> bool:
    return (
        is_active_schema(task)
        and str(task.get("free_policy_revision") or "") == LEGACY_DEFAULT_DISCOVERY_REVISION
        and task.get("free_policy") == _legacy_default_discovery_policy()
    )


def uses_optional_commercial_discovery(task: dict[str, Any]) -> bool:
    return (
        is_active_schema(task)
        and str(task.get("free_policy_revision") or "") in (
            {AUTOMATION_POLICY_REVISION} if is_v24(task) else {FREE_POLICY_REVISION}
        )
        and task.get("free_policy") == active_free_policy()
    )


def serper_free_enhancement(enabled: bool = False) -> dict[str, Any]:
    """Return the explicit bounded Serper discovery contract."""
    return {
        "enabled": enabled is True,
        "role": SERPER_FREE_ROLE,
        "max_queries_per_task": SERPER_FREE_MAX_QUERIES_PER_TASK,
    }


def signa_free_enhancement(enabled: bool = False) -> dict[str, Any]:
    """Return the explicit bounded Signa trademark-discovery contract."""
    return {
        "enabled": enabled is True,
        "role": SIGNA_FREE_ROLE,
        "max_queries_per_task": SIGNA_FREE_MAX_QUERIES_PER_TASK,
        "authoritative_for_final_rating": False,
    }


def serpapi_free_enhancement(enabled: bool = False) -> dict[str, Any]:
    """Return the bounded task-level SerpApi Google Patents fallback contract."""
    return {
        "enabled": enabled is True,
        "role": SERPAPI_FREE_ROLE,
        "max_queries_per_task": SERPAPI_FREE_MAX_QUERIES_PER_TASK,
        "fallback_only_when_serper_enabled": True,
    }


def serpapi_free_enhancement_error(task: dict[str, Any]) -> str:
    """Validate the explicit SerpApi opt-in without changing formal coverage."""
    value = task.get("serpapi_free_enhancement")
    if (
        uses_optional_commercial_discovery(task)
        or uses_default_commercial_discovery(task)
    ) and value is None:
        return "SERPAPI_FREE_ENHANCEMENT_INVALID"
    if value is None:
        return ""
    if not isinstance(value, dict) or set(value) != {
        "enabled", "role", "max_queries_per_task", "fallback_only_when_serper_enabled",
    }:
        return "SERPAPI_FREE_ENHANCEMENT_INVALID"
    maximum = value.get("max_queries_per_task")
    if (
        not isinstance(value.get("enabled"), bool)
        or value.get("role") != SERPAPI_FREE_ROLE
        or isinstance(maximum, bool)
        or not isinstance(maximum, int)
        or maximum < 1
        or maximum > SERPAPI_FREE_MAX_QUERIES_PER_TASK
        or value.get("fallback_only_when_serper_enabled") is not True
    ):
        return "SERPAPI_FREE_ENHANCEMENT_INVALID"
    return ""


def serpapi_free_enabled(task: dict[str, Any]) -> bool:
    value = task.get("serpapi_free_enhancement")
    return (
        is_active_schema(task)
        and not serpapi_free_enhancement_error(task)
        and isinstance(value, dict)
        and value.get("enabled") is True
    )


def serper_free_enhancement_error(task: dict[str, Any]) -> str:
    """Validate optional/default Serper without expanding formal routes."""
    value = task.get("serper_free_enhancement")
    revised = uses_optional_commercial_discovery(task) or uses_default_commercial_discovery(task)
    if revised and value is None:
        return "SERPER_FREE_ENHANCEMENT_INVALID"
    # Pre-revision 2.3 artifacts retain their frozen optional state.
    if value is None:
        return ""
    if not isinstance(value, dict) or set(value) != {
        "enabled", "role", "max_queries_per_task",
    }:
        return "SERPER_FREE_ENHANCEMENT_INVALID"
    if not isinstance(value.get("enabled"), bool):
        return "SERPER_FREE_ENHANCEMENT_INVALID"
    if uses_default_commercial_discovery(task) and value.get("enabled") is not True:
        return "SERPER_FREE_ENHANCEMENT_INVALID"
    if value.get("role") != SERPER_FREE_ROLE:
        return "SERPER_FREE_ENHANCEMENT_INVALID"
    maximum = value.get("max_queries_per_task")
    if isinstance(maximum, bool) or not isinstance(maximum, int):
        return "SERPER_FREE_ENHANCEMENT_INVALID"
    if maximum < 1 or maximum > SERPER_FREE_MAX_QUERIES_PER_TASK:
        return "SERPER_FREE_ENHANCEMENT_INVALID"
    return ""


def serper_free_enabled(task: dict[str, Any]) -> bool:
    value = task.get("serper_free_enhancement")
    return (
        is_active_schema(task)
        and not serper_free_enhancement_error(task)
        and isinstance(value, dict)
        and value.get("enabled") is True
    )


def signa_free_enhancement_error(task: dict[str, Any]) -> str:
    """Validate the current optional or frozen-default Signa contract."""
    value = task.get("signa_free_enhancement")
    if not (uses_optional_commercial_discovery(task) or uses_default_commercial_discovery(task)):
        return "" if value is None else "SIGNA_FREE_ENHANCEMENT_INVALID"
    if not isinstance(value, dict) or set(value) != {
        "enabled", "role", "max_queries_per_task", "authoritative_for_final_rating",
    }:
        return "SIGNA_FREE_ENHANCEMENT_INVALID"
    maximum = value.get("max_queries_per_task")
    if (
        not isinstance(value.get("enabled"), bool)
        or (uses_default_commercial_discovery(task) and value.get("enabled") is not True)
        or value.get("role") != SIGNA_FREE_ROLE
        or value.get("authoritative_for_final_rating") is not False
        or isinstance(maximum, bool)
        or not isinstance(maximum, int)
        or maximum != SIGNA_FREE_MAX_QUERIES_PER_TASK
    ):
        return "SIGNA_FREE_ENHANCEMENT_INVALID"
    return ""


def signa_free_enabled(task: dict[str, Any]) -> bool:
    value = task.get("signa_free_enhancement")
    return (
        is_active_schema(task)
        and not signa_free_enhancement_error(task)
        and isinstance(value, dict)
        and value.get("enabled") is True
    )


def optional_discovery_provider_groups(task: dict[str, Any]) -> dict[str, set[str]]:
    """Return only the third-party discovery lanes selected by this task."""
    groups: dict[str, set[str]] = {}
    if serper_free_enabled(task):
        groups["serper"] = set(SERPER_PROVIDERS)
    if signa_free_enabled(task):
        groups["signa"] = {SIGNA_PROVIDER}
    if serpapi_free_enabled(task):
        groups["serpapi"] = {SERPAPI_PROVIDER}
    return groups


def optional_discovery_incomplete_queries(
    task: dict[str, Any], evidence: dict[str, Any], plan: dict[str, Any],
) -> dict[str, list[str]]:
    """List selected optional plan rows without a terminal run or satisfied fallback."""
    queries = plan.get("queries") if isinstance(plan, dict) else None
    runs = evidence.get("source_runs") if isinstance(evidence, dict) else None
    if not isinstance(queries, dict) or not isinstance(runs, list):
        return {}
    terminal = {"success", "no_result", "not_applicable"}

    def terminal_run(provider: str, query_id: str) -> bool:
        return any(
            isinstance(run, dict)
            and str(run.get("provider") or "") == provider
            and str(run.get("query_id") or "") == query_id
            and run.get("status") in terminal
            for run in runs
        )

    incomplete: dict[str, list[str]] = {}
    for logical_provider, providers in optional_discovery_provider_groups(task).items():
        rows = [
            (provider, row)
            for provider in sorted(providers)
            for row in queries.get(provider, [])
            if isinstance(row, dict)
        ]
        if not rows:
            incomplete[logical_provider] = ["not_planned"]
            continue
        missing: list[str] = []
        for provider, row in rows:
            query_id = str(row.get("query_id") or "")
            completed = bool(query_id) and terminal_run(provider, query_id)
            if not completed and provider == SERPAPI_PROVIDER:
                fallback_provider = str(row.get("fallback_provider") or "")
                fallback_query_id = str(row.get("fallback_query_id") or "")
                completed = bool(fallback_query_id) and terminal_run(
                    fallback_provider, fallback_query_id,
                )
            if not completed:
                missing.append(query_id or "missing_query_id")
        if missing:
            incomplete[logical_provider] = sorted(set(missing))
    return incomplete


def _serper_expected_query_id(
    provider: str, operation: str, jurisdiction: str, item: dict[str, Any],
) -> str:
    identity_params = {
        "q": str(item.get("q") or ""),
        "num": item.get("num"),
        "right_type": str(item.get("right_type") or ""),
    }
    identity_params.update({key: item[key] for key in DECISION_PLAN_META_KEYS if key in item})
    encoded = json.dumps(
        identity_params, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    )
    return stable_id("QRY", provider, operation, jurisdiction.upper(), encoded)


def authorize_serper_free_plan_entry(
    task: dict[str, Any], plan: dict[str, Any], provider: str,
    operation: str, query_id: str,
) -> dict[str, Any]:
    """Authorize one explicitly selected bounded Serper entry before network/recording."""
    error = provider_execution_error(task, provider, operation)
    if error:
        raise ValueError(f"{error}: {provider}/{operation}")
    if (
        plan.get("schema_version") != task.get("schema_version")
        or plan.get("task_id") != task.get("task_id")
        or not plan_free_policy_matches_task(task, plan)
        or plan.get("serper_free_enhancement") != task.get("serper_free_enhancement")
        or plan.get("signa_free_enhancement") != task.get("signa_free_enhancement")
        or plan.get("serpapi_free_enhancement") != task.get("serpapi_free_enhancement")
    ):
        raise ValueError("SERPER_PLAN_IDENTITY_MISMATCH")
    if not query_id:
        raise ValueError("SERPER_QUERY_ID_REQUIRED")
    queries = plan.get("queries")
    if not isinstance(queries, dict):
        raise ValueError("SERPER_PLAN_IDENTITY_MISMATCH")
    all_entries = [
        item
        for current_provider in SERPER_PROVIDERS
        for item in queries.get(current_provider, [])
        if isinstance(item, dict)
    ]
    maximum = int(task["serper_free_enhancement"]["max_queries_per_task"])
    if len(all_entries) > maximum:
        raise ValueError("SERPER_TASK_QUERY_LIMIT_EXCEEDED")
    if any(
        len([
            item for item in queries.get(current_provider, [])
            if isinstance(item, dict)
        ]) > SERPER_PROVIDER_QUERY_CAPS[current_provider]
        for current_provider in SERPER_PROVIDERS
    ):
        raise ValueError("SERPER_PROVIDER_QUERY_LIMIT_EXCEEDED")
    matches = [
        item for item in queries.get(provider, [])
        if isinstance(item, dict) and str(item.get("query_id") or "") == query_id
    ]
    if len(matches) != 1:
        raise ValueError("SERPER_QUERY_ID_NOT_EXACTLY_PLANNED")
    item = dict(matches[0])
    expected_operation = SERPER_PROVIDER_OPERATIONS.get(provider)
    if operation != expected_operation or item.get("operation") != expected_operation:
        raise ValueError("SERPER_OPERATION_MISMATCH")
    if (
        item.get("required") is not False
        or item.get("requirement_ids") != []
        or item.get("authoritative_for_final_rating") is not False
        or item.get("role") != SERPER_FREE_ROLE
        or item.get("required_for") != SERPER_FREE_ROLE
        or item.get("execute_by_default") is not True
        or item.get("wave") != 2
    ):
        raise ValueError("SERPER_DISCOVERY_ONLY_CONTRACT_INVALID")
    allowed_keys = {
        "q", "num", "query_id", "operation", "jurisdiction", "right_type",
        "required", "required_for", "requirement_ids", "wave", "derived_from",
        "role", "execute_by_default", "authoritative_for_final_rating",
    }
    if is_v24(task):
        allowed_keys |= {"search_dimension", "search_language", "execution_phase", "publication_scope"}
    if task.get("decision_workflow_revision") == "scenario-triage-v1":
        allowed_keys |= DECISION_PLAN_META_KEYS
    if set(item) - allowed_keys:
        raise ValueError("SERPER_PLAN_PARAMETERS_INVALID")
    query = str(item.get("q") or "").strip()
    result_count = item.get("num")
    if (
        not query
        or isinstance(result_count, bool)
        or not isinstance(result_count, int)
        or not 1 <= result_count <= 10
    ):
        raise ValueError("SERPER_REQUEST_BOUNDS_INVALID")
    expected_query_id = _serper_expected_query_id(
        provider, operation, str(item.get("jurisdiction") or ""), item,
    )
    if query_id != expected_query_id:
        raise ValueError("SERPER_QUERY_ID_CONTENT_MISMATCH")
    return item


def _signa_expected_query_id(item: dict[str, Any]) -> str:
    identity_params = {
        "q": str(item.get("q") or ""),
        "strategies": item.get("strategies"),
        "filters": item.get("filters"),
        "limit": item.get("limit"),
        "options": item.get("options"),
        "right_type": str(item.get("right_type") or ""),
    }
    identity_params.update({key: item[key] for key in DECISION_PLAN_META_KEYS if key in item})
    encoded = json.dumps(
        identity_params, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    )
    return stable_id(
        "QRY", SIGNA_PROVIDER, SIGNA_OPERATION,
        str(item.get("jurisdiction") or "").upper(), encoded,
    )


def authorize_signa_free_plan_entry(
    task: dict[str, Any], plan: dict[str, Any], query_id: str,
) -> dict[str, Any]:
    """Authorize one exact bounded Signa word-mark discovery request."""
    error = provider_execution_error(task, SIGNA_PROVIDER, SIGNA_OPERATION)
    if error:
        raise ValueError(f"{error}: {SIGNA_PROVIDER}/{SIGNA_OPERATION}")
    if (
        plan.get("schema_version") != task.get("schema_version")
        or plan.get("task_id") != task.get("task_id")
        or not plan_free_policy_matches_task(task, plan)
        or plan.get("serper_free_enhancement") != task.get("serper_free_enhancement")
        or plan.get("signa_free_enhancement") != task.get("signa_free_enhancement")
        or plan.get("serpapi_free_enhancement") != task.get("serpapi_free_enhancement")
    ):
        raise ValueError("SIGNA_PLAN_IDENTITY_MISMATCH")
    if not query_id:
        raise ValueError("SIGNA_QUERY_ID_REQUIRED")
    queries = plan.get("queries")
    if not isinstance(queries, dict):
        raise ValueError("SIGNA_PLAN_IDENTITY_MISMATCH")
    entries = [
        item for item in queries.get(SIGNA_PROVIDER, []) if isinstance(item, dict)
    ]
    maximum = int(task["signa_free_enhancement"]["max_queries_per_task"])
    if len(entries) > maximum:
        raise ValueError("SIGNA_TASK_QUERY_LIMIT_EXCEEDED")
    matches = [
        item for item in entries if str(item.get("query_id") or "") == query_id
    ]
    if len(matches) != 1:
        raise ValueError("SIGNA_QUERY_ID_NOT_EXACTLY_PLANNED")
    item = dict(matches[0])
    if item.get("operation") != SIGNA_OPERATION:
        raise ValueError("SIGNA_OPERATION_MISMATCH")
    if (
        item.get("required") is not False
        or item.get("requirement_ids") != []
        or item.get("authoritative_for_final_rating") is not False
        or item.get("role") != SIGNA_FREE_ROLE
        or item.get("required_for") != SIGNA_FREE_ROLE
        or item.get("execute_by_default") is not True
        or item.get("wave") != 2
        or item.get("right_type") != "trademark_word"
    ):
        raise ValueError("SIGNA_DISCOVERY_ONLY_CONTRACT_INVALID")
    allowed_keys = {
        "q", "strategies", "filters", "limit", "options", "query_id",
        "operation", "jurisdiction", "right_type", "required", "required_for",
        "requirement_ids", "wave", "derived_from", "role", "execute_by_default",
        "authoritative_for_final_rating",
    }
    if is_v24(task):
        allowed_keys |= {"search_dimension", "search_language", "execution_phase", "publication_scope"}
    if task.get("decision_workflow_revision") == "scenario-triage-v1":
        allowed_keys |= DECISION_PLAN_META_KEYS
    if set(item) - allowed_keys:
        raise ValueError("SIGNA_PLAN_PARAMETERS_INVALID")
    offices = item.get("filters", {}).get("offices") if isinstance(item.get("filters"), dict) else None
    if (
        not str(item.get("q") or "").strip()
        or item.get("strategies") != ["exact", "phonetic", "fuzzy", "prefix"]
        or not isinstance(offices, list)
        or not offices
        or len(offices) > 10
        or any(not re.fullmatch(r"[A-Z]{2}", str(value)) or value == "WO" for value in offices)
        or len(set(offices)) != len(offices)
        or item.get("limit") != 25
        or item.get("options") != {"include_total": False}
        or set(item.get("filters", {})) != {"offices"}
    ):
        raise ValueError("SIGNA_REQUEST_BOUNDS_INVALID")
    if query_id != _signa_expected_query_id(item):
        raise ValueError("SIGNA_QUERY_ID_CONTENT_MISMATCH")
    return item


def _serpapi_expected_query_id(item: dict[str, Any]) -> str:
    identity_params = {
        "q": str(item.get("q") or ""),
        "num": item.get("num"),
        "country": str(item.get("country") or ""),
        "right_type": str(item.get("right_type") or ""),
    }
    identity_params.update({key: item[key] for key in DECISION_PLAN_META_KEYS if key in item})
    encoded = json.dumps(
        identity_params, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    )
    return stable_id(
        "QRY", SERPAPI_PROVIDER, SERPAPI_OPERATION,
        str(item.get("jurisdiction") or "").upper(), encoded,
    )


def authorize_serpapi_free_plan_entry(
    task: dict[str, Any], plan: dict[str, Any], operation: str, query_id: str,
) -> dict[str, Any]:
    """Authorize one exact, free-plan-only SerpApi Google Patents query."""
    error = provider_execution_error(task, SERPAPI_PROVIDER, operation)
    if error:
        raise ValueError(f"{error}: {SERPAPI_PROVIDER}/{operation}")
    if (
        plan.get("schema_version") != task.get("schema_version")
        or plan.get("task_id") != task.get("task_id")
        or not plan_free_policy_matches_task(task, plan)
        or plan.get("serper_free_enhancement") != task.get("serper_free_enhancement")
        or plan.get("signa_free_enhancement") != task.get("signa_free_enhancement")
        or plan.get("serpapi_free_enhancement") != task.get("serpapi_free_enhancement")
    ):
        raise ValueError("SERPAPI_PLAN_IDENTITY_MISMATCH")
    if not query_id:
        raise ValueError("SERPAPI_QUERY_ID_REQUIRED")
    queries = plan.get("queries")
    if not isinstance(queries, dict):
        raise ValueError("SERPAPI_PLAN_IDENTITY_MISMATCH")
    entries = [
        item for item in queries.get(SERPAPI_PROVIDER, []) if isinstance(item, dict)
    ]
    maximum = int(task["serpapi_free_enhancement"]["max_queries_per_task"])
    if len(entries) > maximum:
        raise ValueError("SERPAPI_TASK_QUERY_LIMIT_EXCEEDED")
    if is_v24(task) and len(entries) + len(queries.get("serpapi_google_lens", [])) > maximum:
        raise ValueError("SERPAPI_TASK_QUERY_LIMIT_EXCEEDED")
    matches = [
        item for item in entries if str(item.get("query_id") or "") == query_id
    ]
    if len(matches) != 1:
        raise ValueError("SERPAPI_QUERY_ID_NOT_EXACTLY_PLANNED")
    item = dict(matches[0])
    if operation != SERPAPI_OPERATION or item.get("operation") != SERPAPI_OPERATION:
        raise ValueError("SERPAPI_OPERATION_MISMATCH")
    if (
        item.get("required") is not False
        or item.get("requirement_ids") != []
        or item.get("authoritative_for_final_rating") is not False
        or item.get("role") != SERPAPI_FREE_ROLE
        or item.get("required_for") != SERPAPI_FREE_ROLE
    ):
        raise ValueError("SERPAPI_DISCOVERY_ONLY_CONTRACT_INVALID")
    allowed_keys = {
        "q", "num", "country", "query_id", "operation", "jurisdiction",
        "right_type", "required", "required_for", "requirement_ids", "wave",
        "derived_from", "role", "execute_by_default",
        "authoritative_for_final_rating", "execute_when", "fallback_provider",
        "fallback_query_id",
    }
    if is_v24(task):
        allowed_keys |= {"search_dimension", "search_language", "execution_phase", "publication_scope"}
    if task.get("decision_workflow_revision") == "scenario-triage-v1":
        allowed_keys |= DECISION_PLAN_META_KEYS
    if set(item) - allowed_keys:
        raise ValueError("SERPAPI_PLAN_PARAMETERS_INVALID")
    query = str(item.get("q") or "").strip()
    result_count = item.get("num")
    country = str(item.get("country") or "").upper()
    if (
        not query
        or isinstance(result_count, bool)
        or not isinstance(result_count, int)
        or not 1 <= result_count <= 100
        or not re.fullmatch(r"[A-Z]{2}", country)
        or str(item.get("right_type") or "") not in {"patent", "design"}
    ):
        raise ValueError("SERPAPI_REQUEST_BOUNDS_INVALID")
    if query_id != _serpapi_expected_query_id(item):
        raise ValueError("SERPAPI_QUERY_ID_CONTENT_MISMATCH")
    fallback_provider = str(item.get("fallback_provider") or "")
    fallback_query_id = str(item.get("fallback_query_id") or "")
    matching_serper_rows = [
        row for row in queries.get("serper_patents", [])
        if isinstance(row, dict)
        and normalize_text(str(row.get("q") or "")) == normalize_text(query)
        and str(row.get("right_type") or "") == str(item.get("right_type") or "")
    ]
    if serper_free_enabled(task) and matching_serper_rows and not (
        fallback_provider and fallback_query_id
    ):
        raise ValueError("SERPAPI_FALLBACK_BINDING_REQUIRED")
    if fallback_provider or fallback_query_id:
        if (
            fallback_provider != "serper_patents"
            or not fallback_query_id
            or item.get("execute_when") != "serper_unavailable_or_exhausted"
        ):
            raise ValueError("SERPAPI_FALLBACK_BINDING_INVALID")
        fallback_matches = [
            row for row in matching_serper_rows
            if str(row.get("query_id") or "") == fallback_query_id
        ]
        if len(fallback_matches) != 1:
            raise ValueError("SERPAPI_FALLBACK_BINDING_INVALID")
        authorize_serper_free_plan_entry(
            task, plan, "serper_patents", "patents", fallback_query_id,
        )
    return item


def default_discovery_plan_error(
    task: dict[str, Any], plan: dict[str, Any],
) -> str:
    """Validate frozen default and current explicit optional discovery plans."""
    if not (
        uses_optional_commercial_discovery(task)
        or uses_default_commercial_discovery(task)
    ):
        return ""
    if (
        not plan_free_policy_matches_task(task, plan)
        or plan.get("serper_free_enhancement") != task.get("serper_free_enhancement")
        or plan.get("signa_free_enhancement") != task.get("signa_free_enhancement")
        or plan.get("serpapi_free_enhancement") != task.get("serpapi_free_enhancement")
    ):
        return "COMMERCIAL_DISCOVERY_PLAN_IDENTITY_MISMATCH"
    queries = plan.get("queries")
    if not isinstance(queries, dict):
        return "COMMERCIAL_DISCOVERY_PLAN_INVALID"
    serper_enabled = serper_free_enabled(task)
    signa_enabled = signa_free_enabled(task)
    serpapi_enabled = serpapi_free_enabled(task)
    try:
        for provider in sorted(SERPER_PROVIDERS):
            rows = [item for item in queries.get(provider, []) if isinstance(item, dict)]
            if serper_enabled and not rows and not is_v24(task):
                return "OPTIONAL_SERPER_PLAN_MISSING"
            if not serper_enabled and rows:
                return "SERPER_FREE_NOT_ENABLED"
            for item in rows:
                authorize_serper_free_plan_entry(
                    task, plan, provider, SERPER_PROVIDER_OPERATIONS[provider],
                    str(item.get("query_id") or ""),
                )
        config = load_skill_config()
        office_map = config.get("providers", {}).get(SIGNA_PROVIDER, {}).get("office_map", {})
        has_office = any(
            str(office_map.get(str(value).upper()) or "").strip()
            for value in task.get("target_jurisdictions", [])
        )
        has_mark_term = any(
            isinstance(item, dict)
            and item.get("kind") in {"brand", "owner", "ocr"}
            and str(item.get("value") or "").strip()
            for item in plan.get("terms", [])
        )
        signa_rows = [
            item for item in queries.get(SIGNA_PROVIDER, []) if isinstance(item, dict)
        ]
        if signa_enabled and has_office and has_mark_term and not signa_rows and not is_v24(task):
            return "OPTIONAL_SIGNA_PLAN_MISSING"
        if not signa_enabled and signa_rows:
            return "SIGNA_FREE_NOT_ENABLED"
        for item in signa_rows:
            authorize_signa_free_plan_entry(task, plan, str(item.get("query_id") or ""))
        serpapi_rows = [
            item for item in queries.get(SERPAPI_PROVIDER, []) if isinstance(item, dict)
        ]
        if serpapi_enabled and not serpapi_rows and not is_v24(task):
            return "OPTIONAL_SERPAPI_PLAN_MISSING"
        if not serpapi_enabled and serpapi_rows:
            return "SERPAPI_FREE_NOT_ENABLED"
        for item in serpapi_rows:
            authorize_serpapi_free_plan_entry(
                task, plan, str(item.get("operation") or ""),
                str(item.get("query_id") or ""),
            )
    except (KeyError, TypeError, ValueError) as exc:
        return str(exc).split(":", 1)[0] or "COMMERCIAL_DISCOVERY_PLAN_INVALID"
    expected_allowlist = [
        name for name, enabled in (
            ("serper", serper_enabled), ("signa", signa_enabled),
            ("serpapi", serpapi_enabled),
        ) if enabled
    ]
    execution_policy = plan.get("execution_policy")
    if (
        not isinstance(execution_policy, dict)
        or execution_policy.get("commercial_freemium_allowlist") != expected_allowlist
        or execution_policy.get("commercial_providers_enabled") is not bool(expected_allowlist)
        or execution_policy.get("paid_execution_enabled") is not False
    ):
        return "COMMERCIAL_DISCOVERY_EXECUTION_POLICY_INVALID"
    return ""


def assert_default_discovery_plan_contract(
    task: dict[str, Any], plan: dict[str, Any],
) -> None:
    error = default_discovery_plan_error(task, plan)
    if error:
        raise ValueError(error)


def assert_active_free_policy(task: dict[str, Any]) -> None:
    """Reject a mutated 2.3 execution/coverage contract before task work."""
    if is_active_schema(task) and not task_free_policy_valid(task):
        raise ValueError(
            "FREE_POLICY_INVALID: 2.3-free tasks must use their immutable recognized free policy"
        )
    if is_active_schema(task):
        serper_error = serper_free_enhancement_error(task)
        if serper_error:
            raise ValueError(f"{serper_error}: invalid task-level Serper discovery contract")
        signa_error = signa_free_enhancement_error(task)
        if signa_error:
            raise ValueError(f"{signa_error}: invalid task-level Signa discovery contract")
        serpapi_error = serpapi_free_enhancement_error(task)
        if serpapi_error:
            raise ValueError(f"{serpapi_error}: invalid task-level SerpApi opt-in contract")
    if is_active_schema(task) and not canonical_coverage_requirements_match(task):
        raise ValueError(
            "COVERAGE_REQUIREMENTS_INVALID: 2.3-free coverage requirements must match the canonical jurisdiction routes"
        )


def coverage_routes(task: dict[str, Any]) -> list[dict[str, Any]]:
    routes: list[dict[str, Any]] = []
    for requirement in task.get("coverage_requirements", []):
        if not isinstance(requirement, dict):
            continue
        for route in requirement.get("routes", []):
            if isinstance(route, dict):
                routes.append({
                    **route,
                    "requirement_id": requirement.get("requirement_id", ""),
                    "jurisdiction": requirement.get("jurisdiction", ""),
                    "right_type": requirement.get("right_type", ""),
                })
    return routes


def coverage_route_configured(
    task: dict[str, Any], provider: str, operation: str = "",
    *, jurisdiction: str = "", right_type: str = "",
) -> bool:
    if is_legacy_schema(task):
        configured = (
            set(task.get("required_sources", []))
            | set(task.get("low_risk_gate_sources", []))
            | set(task.get("optional_sources", []))
        )
        return provider in configured
    return any(
        route.get("provider") == provider
        and (not operation or route.get("operation") == operation)
        and (not jurisdiction or str(route.get("jurisdiction") or "").upper() == jurisdiction.upper())
        and (not right_type or route.get("right_type") == right_type)
        for route in coverage_routes(task)
    )


def provider_execution_error(
    task: dict[str, Any], provider: str, operation: str = "",
    *, jurisdiction: str = "", right_type: str = "",
) -> str:
    """Return a stable pre-network rejection code for disallowed 2.3 sources."""
    if not is_active_schema(task):
        return "LEGACY_TASK_READ_ONLY"
    if not task_free_policy_valid(task):
        return "FREE_POLICY_INVALID"
    if provider in WIPO_PROVIDERS:
        return "WIPO_PROVIDER_DISABLED"
    if not canonical_coverage_requirements_match(task):
        return "COVERAGE_REQUIREMENTS_INVALID"
    if is_v24(task):
        if provider == "serpapi_google_lens":
            return ("SERPAPI_FREE_NOT_ENABLED" if not serpapi_free_enabled(task) else
                    "PROVIDER_OPERATION_NOT_CONFIGURED" if operation != "image_search" else "")
        if provider == "epo_publication_server" and operation == "document_retrieval":
            return "" if right_type in {"", "patent"} else "PROVIDER_OPERATION_NOT_CONFIGURED"
    if provider in SERPER_PROVIDERS:
        if not serper_free_enabled(task):
            return "SERPER_FREE_NOT_ENABLED"
        if SERPER_PROVIDER_OPERATIONS.get(provider) != operation:
            return "PROVIDER_OPERATION_NOT_CONFIGURED"
        return ""
    if provider == SERPAPI_PROVIDER:
        if not serpapi_free_enabled(task):
            return "SERPAPI_FREE_NOT_ENABLED"
        if operation != SERPAPI_OPERATION:
            return "PROVIDER_OPERATION_NOT_CONFIGURED"
        return ""
    if provider == SIGNA_PROVIDER:
        if not signa_free_enabled(task):
            return "SIGNA_FREE_NOT_ENABLED"
        if operation != SIGNA_OPERATION:
            return "PROVIDER_OPERATION_NOT_CONFIGURED"
        return ""
    if provider in COMMERCIAL_PROVIDERS:
        return "COMMERCIAL_PROVIDER_DISABLED"
    if not coverage_route_configured(
        task, provider, operation, jurisdiction=jurisdiction, right_type=right_type,
    ):
        return (
            "PROVIDER_OPERATION_NOT_CONFIGURED"
            if operation else "PROVIDER_NOT_IN_COVERAGE_PLAN"
        )
    return ""


def assert_provider_execution_allowed(
    task: dict[str, Any], provider: str, operation: str = "",
    *, jurisdiction: str = "", right_type: str = "",
) -> None:
    code = provider_execution_error(
        task, provider, operation, jurisdiction=jurisdiction, right_type=right_type,
    )
    if code:
        suffix = f"/{operation}" if operation else ""
        raise ValueError(f"{code}: {provider}{suffix}")


def _route(
    provider: str, operation: str, method: str, priority: int = 1, *,
    required: bool = True,
) -> dict[str, Any]:
    route = {
        "provider": provider,
        "operation": operation,
        "method": method,
        "priority": priority,
    }
    if not required:
        route["required"] = False
    return route


def _requirement(
    requirement_id: str, jurisdiction: str, right_type: str, phase: str,
    required_for: str, completion_policy: str, routes: list[dict[str, Any]],
) -> dict[str, Any]:
    if right_type not in RIGHT_TYPES:
        raise ValueError(f"Unsupported right_type: {right_type}")
    return {
        "requirement_id": requirement_id,
        "jurisdiction": jurisdiction,
        "right_type": right_type,
        "phase": phase,
        "required_for": required_for,
        "completion_policy": completion_policy,
        "routes": routes,
    }


def build_coverage_requirements(jurisdictions: list[str]) -> list[dict[str, Any]]:
    """Build operation-level official/free coverage for a new 2.3 task."""
    targets = list(dict.fromkeys(str(value).upper() for value in jurisdictions if str(value).strip()))
    requirements: list[dict[str, Any]] = []

    if "US" in targets:
        patent_routes = [
            _route("epo_ops", "search", "api"),
            _route("epo_ops", "candidate_detail", "api", 2, required=False),
            _route("uspto_patent_browser", "patent_recall", "cdp_assisted"),
        ]
        for right_type in ("patent", "design"):
            requirements.append(_requirement(
                f"COV-US-{right_type.upper()}-RECALL", "US", right_type,
                "official_recall", "low_risk", "all", patent_routes,
            ))
            requirements.append(_requirement(
                f"COV-US-{right_type.upper()}-VERIFY", "US", right_type,
                "candidate_verification", "formal", "all", [
                    _route("uspto_patent_browser", "candidate_verification", "cdp_assisted"),
                ],
            ))
        for right_type in ("trademark_word", "trademark_figurative"):
            requirements.append(_requirement(
                f"COV-US-{right_type.upper()}-RECALL", "US", right_type,
                "official_recall", "low_risk", "all", [
                    _route("uspto_tmsearch_browser", "trademark_recall", "cdp_assisted"),
                ],
            ))
            requirements.append(_requirement(
                f"COV-US-{right_type.upper()}-VERIFY", "US", right_type,
                "candidate_verification", "formal", "all", [
                    _route("uspto_tsdr", "candidate_verification", "cdp_assisted"),
                ],
            ))

    eu_target = "EU" in targets or any(value in EU_COUNTRIES for value in targets)
    european_scope = eu_target or "GB" in targets
    if european_scope:
        if eu_target:
            requirements.extend([
                _requirement("COV-EU-PATENT-RECALL", "EU", "patent", "official_recall", "low_risk", "all", [
                    _route("epo_ops", "search", "api"),
                    _route("epo_ops", "candidate_detail", "api", 2, required=False),
                ]),
                _requirement("COV-EU-PATENT-VERIFY", "EU", "patent", "candidate_verification", "formal", "all", [
                    _route("epo_register_browser", "candidate_verification", "cdp_assisted"),
                ]),
                _requirement("COV-EU-DESIGN-RECALL", "EU", "design", "official_recall", "low_risk", "all", [
                    _route("euipo_design", "search", "api"),
                ]),
                _requirement("COV-EU-DESIGN-VERIFY", "EU", "design", "candidate_verification", "formal", "all", [
                    _route("euipo_design", "candidate_verification", "api"),
                ]),
                _requirement("COV-EU-TRADEMARK-WORD-RECALL", "EU", "trademark_word", "official_recall", "low_risk", "all", [
                    _route("euipo_trademark", "search", "api"),
                ]),
                _requirement("COV-EU-TRADEMARK-WORD-VERIFY", "EU", "trademark_word", "candidate_verification", "formal", "all", [
                    _route("euipo_trademark", "candidate_verification", "api"),
                ]),
                _requirement("COV-EU-TRADEMARK-FIGURATIVE-RECALL", "EU", "trademark_figurative", "official_recall", "low_risk", "all", [
                    _route("euipo_esearch_browser", "trademark_recall", "cdp_assisted"),
                ]),
                _requirement("COV-EU-TRADEMARK-FIGURATIVE-VERIFY", "EU", "trademark_figurative", "candidate_verification", "formal", "all", [
                    _route("euipo_trademark", "candidate_verification", "api"),
                ]),
            ])
        for country in (value for value in targets if value in AMAZON_EU_COUNTRIES or value == "GB"):
            free_index_provider = "inpi_api" if country == "FR" else "prv_open_data" if country == "SE" else ""
            free_index_method = "api" if country == "FR" else "local_index"
            patent_recall_routes = (
                [
                    _route(free_index_provider, "search", free_index_method, 1),
                    _route("official_registry_browser", "patent_recall", "cdp_assisted", 2),
                ]
                if free_index_provider else
                [_route("official_registry_browser", "patent_recall", "cdp_assisted")]
            )
            # TMview/DesignView are broad discovery indexes, not the legally
            # controlling national register.  Keep their recall contribution
            # explicit and require an official national API/register pass as a
            # separate low-risk condition.
            design_recall_routes = (
                [
                    _route(free_index_provider, "search", free_index_method, 1),
                    _route("official_registry_browser", "design_recall", "cdp_assisted", 2),
                ]
                if free_index_provider else
                [_route("official_registry_browser", "design_recall", "cdp_assisted")]
            )
            trademark_recall_routes = (
                [
                    _route(free_index_provider, "search", free_index_method, 1),
                    _route("official_registry_browser", "trademark_recall", "cdp_assisted", 2),
                ]
                if free_index_provider else
                [_route("official_registry_browser", "trademark_recall", "cdp_assisted")]
            )
            verification_routes = (
                [
                    _route("inpi_api", "candidate_verification", "api", 1),
                    _route("official_registry_browser", "candidate_verification", "cdp_assisted", 2),
                ]
                if country == "FR" else
                [_route("official_registry_browser", "candidate_verification", "cdp_assisted")]
            )
            recall_policy = "any" if free_index_provider else "all"
            verification_policy = "any" if country == "FR" else "all"
            requirements.extend([
                _requirement(f"COV-{country}-PATENT-RECALL", country, "patent", "official_recall", "low_risk", recall_policy, patent_recall_routes),
                _requirement(f"COV-{country}-PATENT-VERIFY", country, "patent", "candidate_verification", "formal", verification_policy, verification_routes),
                _requirement(f"COV-{country}-DESIGN-DISCOVERY", country, "design", "discovery", "low_risk", "all", [
                    _route("designview_browser", "design_recall", "cdp_assisted"),
                ]),
                _requirement(f"COV-{country}-DESIGN-RECALL", country, "design", "official_recall", "low_risk", recall_policy, design_recall_routes),
                _requirement(f"COV-{country}-DESIGN-VERIFY", country, "design", "candidate_verification", "formal", verification_policy, verification_routes),
                _requirement(f"COV-{country}-TRADEMARK-WORD-DISCOVERY", country, "trademark_word", "discovery", "low_risk", "all", [
                    _route("tmview_browser", "trademark_recall", "cdp_assisted"),
                ]),
                _requirement(f"COV-{country}-TRADEMARK-WORD-RECALL", country, "trademark_word", "official_recall", "low_risk", recall_policy, trademark_recall_routes),
                _requirement(f"COV-{country}-TRADEMARK-WORD-VERIFY", country, "trademark_word", "candidate_verification", "formal", verification_policy, verification_routes),
                _requirement(f"COV-{country}-TRADEMARK-FIGURATIVE-DISCOVERY", country, "trademark_figurative", "discovery", "low_risk", "all", [
                    _route("tmview_browser", "trademark_recall", "cdp_assisted"),
                ]),
                _requirement(f"COV-{country}-TRADEMARK-FIGURATIVE-RECALL", country, "trademark_figurative", "official_recall", "low_risk", recall_policy, trademark_recall_routes),
                _requirement(f"COV-{country}-TRADEMARK-FIGURATIVE-VERIFY", country, "trademark_figurative", "candidate_verification", "formal", verification_policy, verification_routes),
            ])
            if country in EU_UTILITY_MODEL_COUNTRIES:
                utility_recall_routes = (
                    [
                        _route("inpi_api", "search", "api", 1),
                        _route("official_registry_browser", "utility_model_recall", "cdp_assisted", 2),
                    ]
                    if country == "FR" else
                    [_route("official_registry_browser", "utility_model_recall", "cdp_assisted")]
                )
                requirements.extend([
                    _requirement(
                        f"COV-{country}-UTILITY-MODEL-RECALL", country, "utility_model",
                        "official_recall", "low_risk", "any" if country == "FR" else "all",
                        utility_recall_routes,
                    ),
                    _requirement(
                        f"COV-{country}-UTILITY-MODEL-VERIFY", country, "utility_model",
                        "candidate_verification", "formal", verification_policy,
                        verification_routes,
                    ),
                ])
        # Non-marketplace EU member states are discovery-only until a national
        # official-register adapter passes its positive/negative smoke tests.
        for country in (
            value for value in targets
            if value in EU_COUNTRIES and value not in AMAZON_EU_COUNTRIES
        ):
            requirements.extend([
                _requirement(
                    f"COV-{country}-DESIGN-DISCOVERY", country, "design",
                    "discovery", "low_risk", "all", [
                        _route("designview_browser", "design_recall", "cdp_assisted"),
                    ],
                ),
                _requirement(
                    f"COV-{country}-TRADEMARK-WORD-DISCOVERY", country, "trademark_word",
                    "discovery", "low_risk", "all", [
                        _route("tmview_browser", "trademark_recall", "cdp_assisted"),
                    ],
                ),
                _requirement(
                    f"COV-{country}-TRADEMARK-FIGURATIVE-DISCOVERY", country, "trademark_figurative",
                    "discovery", "low_risk", "all", [
                        _route("tmview_browser", "trademark_recall", "cdp_assisted"),
                    ],
                ),
            ])

    if "JP" in targets:
        for right_type, recall_routes in (
            ("patent", [
                _route("epo_ops", "search", "api"),
                _route("epo_ops", "candidate_detail", "api", 2, required=False),
                _route("jplatpat_browser", "patent_recall", "cdp_assisted"),
            ]),
            ("utility_model", [
                _route("epo_ops", "search", "api"),
                _route("epo_ops", "candidate_detail", "api", 2, required=False),
                _route("jplatpat_browser", "utility_model_recall", "cdp_assisted"),
            ]),
            ("design", [_route("jplatpat_browser", "design_recall", "cdp_assisted")]),
            ("trademark_word", [_route("jplatpat_browser", "trademark_recall", "cdp_assisted")]),
            ("trademark_figurative", [_route("jplatpat_browser", "trademark_recall", "cdp_assisted")]),
        ):
            requirements.append(_requirement(
                f"COV-JP-{right_type.upper()}-RECALL", "JP", right_type,
                "official_recall", "low_risk", "all", recall_routes,
            ))
            verification_routes = [
                _route("jplatpat_browser", "candidate_verification", "cdp_assisted", 2),
            ]
            if right_type != "utility_model":
                verification_routes.insert(0, _route("jpo_api", "candidate_verification", "api", 1))
            requirements.append(_requirement(
                f"COV-JP-{right_type.upper()}-VERIFY", "JP", right_type,
                "candidate_verification", "formal", "any", verification_routes,
            ))

    public_supported = {"US", "JP", "GB", *AMAZON_EU_COUNTRIES}
    substantive_targets = [value for value in targets if value in public_supported]
    if not substantive_targets and targets == ["EU"]:
        substantive_targets = ["EU"]
    for jurisdiction in substantive_targets:
        for right_type, operation in (("copyright", "copyright_recall"), ("enforcement", "enforcement_recall")):
            requirements.append(_requirement(
                f"COV-{jurisdiction}-{right_type.upper()}-RECALL", jurisdiction, right_type,
                "discovery", "low_risk", "all", [
                    _route("public_web_browser", operation, "manual_capture"),
                ],
            ))
            requirements.append(_requirement(
                f"COV-{jurisdiction}-{right_type.upper()}-VERIFY", jurisdiction, right_type,
                "candidate_verification", "formal", "all", [
                    _route("public_web_browser", "candidate_verification", "manual_capture"),
                ],
            ))
    return requirements


def canonical_coverage_requirements_match(task: dict[str, Any]) -> bool:
    """Require the immutable 2.3 route matrix for the task's exact scope."""
    if not is_active_schema(task):
        return True
    jurisdictions = task.get("target_jurisdictions")
    if not isinstance(jurisdictions, list) or not jurisdictions:
        return False
    if is_v24(task):
        from workflow_v24 import build_coverage_requirements_v24
        return task.get("coverage_requirements") == build_coverage_requirements_v24(
            jurisdictions, screening_revision=task.get("screening_revision"), specialty_workflow_revision=task.get("specialty_workflow_revision"))
    return task.get("coverage_requirements") == build_coverage_requirements(jurisdictions)


def default_jurisdictions(marketplace: str) -> list[str]:
    market = marketplace.upper()
    if market in EU_COUNTRIES:
        return ["EU", market]
    return [market] if market else []


def required_providers(jurisdictions: list[str]) -> list[str]:
    """Compatibility projection of the active operation-level requirements."""
    return list(dict.fromkeys([
        "amazon_browser",
        *(
            str(route["provider"])
            for requirement in build_coverage_requirements(jurisdictions)
            for route in requirement["routes"]
        ),
    ]))


def low_risk_gate_providers(jurisdictions: list[str]) -> list[str]:
    """Legacy projection; 2.3 tasks use coverage_requirements directly."""
    return list(dict.fromkeys(
        str(route["provider"])
        for requirement in build_coverage_requirements(jurisdictions)
        if requirement["required_for"] == "low_risk"
        for route in requirement["routes"]
    ))


def capture_provenance(
    capture: dict[str, Any], task: dict[str, Any], *,
    allowed_transports: set[str],
) -> dict[str, Any]:
    """Validate browser provenance without persisting CDP connection details."""
    if str(capture.get("browser") or "").strip() != "chrome_desktop":
        raise ValueError("browser must be chrome_desktop")
    schema_version = str(task.get("schema_version") or "")
    if schema_version not in SUPPORTED_SCHEMA_VERSIONS:
        raise ValueError(f"unsupported task schema_version: {schema_version!r}")
    if schema_version == "2.1-free":
        return {"browser": "chrome_desktop", "capture_transport": "legacy"}

    forbidden = {
        "cdp_endpoint", "endpoint", "websocket", "websocket_url",
        "remote_debugging_port", "profile_dir", "user_data_dir",
        "cookies", "local_storage", "localstorage",
    }
    present = sorted(key for key in forbidden if key in capture)
    if present:
        raise ValueError("capture contains forbidden CDP/session fields: " + ", ".join(present))

    transport = str(capture.get("capture_transport") or "").strip()
    if transport not in allowed_transports:
        raise ValueError(
            "capture_transport must be one of: " + ", ".join(sorted(allowed_transports))
        )
    provenance: dict[str, Any] = {
        "browser": "chrome_desktop",
        "capture_transport": transport,
    }
    if transport == "cdp":
        browser_version = str(capture.get("browser_version") or "").strip()
        protocol_version = str(capture.get("protocol_version") or "").strip()
        session_id = str(capture.get("cdp_session_id") or "").strip()
        if not browser_version or not protocol_version:
            raise ValueError("CDP captures require browser_version and protocol_version")
        if not re.fullmatch(r"[A-Za-z0-9_-]{8,64}", session_id):
            raise ValueError("CDP captures require a sanitized cdp_session_id")
        provenance.update({
            "browser_version": browser_version,
            "protocol_version": protocol_version,
            "cdp_session_id": session_id,
        })
    elif capture.get("operator_confirmed") is not True:
        raise ValueError("manual captures require operator_confirmed=true")
    else:
        provenance["operator_confirmed"] = True
    return provenance


def add_history(task: dict[str, Any], state: str, note: str = "") -> None:
    if state not in TASK_STATES:
        raise ValueError(f"Unsupported task state: {state}")
    task["state"] = state
    task.setdefault("history", []).append({"state": state, "at": now_iso(), "note": note})
    task["updated_at"] = now_iso()


def add_gap(
    task: dict[str, Any], provider: str, jurisdiction: str, status: str,
    error_code: str, detail: str, mandatory: bool = True, query_id: str = "",
) -> None:
    if status not in SOURCE_STATUSES:
        raise ValueError(f"Unsupported source status: {status}")
    key = (provider, jurisdiction.upper(), error_code, query_id)
    task.setdefault("coverage_gaps", [])[:] = [
        gap for gap in task.get("coverage_gaps", [])
        if (
            gap.get("provider"), gap.get("jurisdiction"), gap.get("error_code"),
            str(gap.get("query_id") or ""),
        ) != key
    ]
    task["coverage_gaps"].append({
        "provider": provider,
        "jurisdiction": jurisdiction.upper(),
        "status": status,
        "error_code": error_code,
        "affected_modules": PROVIDER_MODULES.get(provider, []),
        "detail": detail,
        "mandatory": mandatory,
        "query_id": query_id,
        "at": now_iso(),
    })


def clear_gaps(task: dict[str, Any], provider: str, query_id: str = "") -> None:
    """Clear only the completed logical query; never hide sibling-query failures."""
    task["coverage_gaps"] = [
        gap for gap in task.get("coverage_gaps", [])
        if not (
            gap.get("provider") == provider
            and (not query_id or str(gap.get("query_id") or "") == query_id)
        )
    ]


def clear_optional_discovery_access_gaps(task: dict[str, Any], provider: str) -> None:
    """Clear recovered credential/preflight failures without hiding query or quota failures."""
    task["coverage_gaps"] = [
        gap for gap in task.get("coverage_gaps", [])
        if not (
            gap.get("provider") == provider
            and gap.get("mandatory") is False
            and gap.get("error_code") in {
                "AUTH_MISSING", "AUTH_FAILED", "FREE_SOURCE_UNAVAILABLE",
                "SIGNA_OFFICE_UNSUPPORTED",
            }
        )
    ]


def upsert_source_run(evidence: dict[str, Any], run: dict[str, Any]) -> None:
    if run.get("status") not in SOURCE_STATUSES:
        raise ValueError(f"Unsupported source status: {run.get('status')}")
    runs = evidence.setdefault("source_runs", [])
    for index, current in enumerate(runs):
        if current.get("run_id") == run.get("run_id"):
            runs[index] = run
            break
    else:
        runs.append(run)
    evidence["updated_at"] = now_iso()


def image_info(path: Path) -> tuple[str, int, int]:
    data = path.read_bytes()
    if data.startswith(b"\x89PNG\r\n\x1a\n") and len(data) >= 24:
        width, height = struct.unpack(">II", data[16:24])
        return "image/png", width, height
    if data.startswith(b"\xff\xd8\xff"):
        index = 2
        while index + 9 < len(data):
            if data[index] != 0xFF:
                index += 1
                continue
            marker = data[index + 1]
            index += 2
            if marker in {0xD8, 0xD9}:
                continue
            if index + 2 > len(data):
                break
            length = int.from_bytes(data[index:index + 2], "big")
            if marker in {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}:
                height = int.from_bytes(data[index + 3:index + 5], "big")
                width = int.from_bytes(data[index + 5:index + 7], "big")
                return "image/jpeg", width, height
            index += max(length, 2)
    if data[:6] in {b"GIF87a", b"GIF89a"} and len(data) >= 10:
        width, height = struct.unpack("<HH", data[6:10])
        return "image/gif", width, height
    if data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        return "image/webp", 0, 0
    raise ValueError(f"Unsupported or unreadable image format: {path}")


def path_within(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def run_dir_from_task(task_path: Path) -> Path:
    return task_path.resolve().parent
