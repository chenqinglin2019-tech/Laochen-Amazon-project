#!/usr/bin/env python3
"""Shared deterministic helpers for LC IPR Risk Screening Free."""

from __future__ import annotations

import hashlib
import json
import os
import re
import struct
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "2.2-free"
SUPPORTED_SCHEMA_VERSIONS = {"2.1-free", SCHEMA_VERSION}
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
MODULE_IDS = [
    "appearance_patent", "utility_patent", "pending_application", "word_mark",
    "figurative_trade_dress", "copyright_ip", "enforcement",
]
EU_COUNTRIES = {
    "AT", "BE", "BG", "HR", "CY", "CZ", "DE", "DK", "EE", "ES", "FI", "FR",
    "GR", "HU", "IE", "IT", "LT", "LU", "LV", "MT", "NL", "PL", "PT", "RO",
    "SE", "SI", "SK",
}
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
    "serper_patents": ["appearance_patent", "utility_patent", "pending_application"],
    "serper_web": ["enforcement", "copyright_ip"],
    "serper_images": ["figurative_trade_dress", "copyright_ip"],
    "signa": ["word_mark", "figurative_trade_dress"],
    "rapidapi_uspto_trademark": ["word_mark", "figurative_trade_dress"],
    "uspto_tmsearch_browser": ["word_mark", "figurative_trade_dress"],
    "uspto_tsdr": ["word_mark", "figurative_trade_dress"],
    "uspto_patent_browser": ["appearance_patent", "utility_patent", "pending_application"],
    "euipo_trademark": ["word_mark", "figurative_trade_dress"],
    "euipo_design": ["appearance_patent", "figurative_trade_dress"],
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
    return re.sub(r"[^a-z0-9]+", "", value.casefold())


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
    base = ensure_object(load_json(skill_root() / "config.json"), "config.json")
    local_path = skill_root() / "config.local.json"
    if local_path.exists():
        base = deep_merge(base, ensure_object(load_json(local_path), "config.local.json"))
    return base


ENV_CREDENTIALS = {
    "backend_token": "LAOCHEN_BACKEND_TOKEN",
    "epo_consumer_key": "EPO_OPS_CONSUMER_KEY",
    "epo_consumer_secret": "EPO_OPS_CONSUMER_SECRET",
    "signa_api_key": "SIGNA_API_KEY",
    "euipo_client_id": "EUIPO_CLIENT_ID",
    "euipo_client_secret": "EUIPO_CLIENT_SECRET",
    "serper_api_key": "SERPER_API_KEY",
    "serpapi_api_key": "SERPAPI_API_KEY",
    "rapidapi_key": "RAPIDAPI_KEY",
}


def credential(config: dict[str, Any], name: str) -> str:
    env_name = ENV_CREDENTIALS.get(name, name.upper())
    if os.environ.get(env_name):
        return os.environ[env_name]
    if name == "backend_token":
        return str(config.get("backend_token", ""))
    top_level_value = config.get(name)
    if isinstance(top_level_value, str) and top_level_value:
        return top_level_value
    creds = config.get("credentials", {})
    return str(creds.get(name, "")) if isinstance(creds, dict) else ""


def default_jurisdictions(marketplace: str) -> list[str]:
    market = marketplace.upper()
    if market in EU_COUNTRIES:
        return ["EU", market]
    return [market] if market else []


def required_providers(jurisdictions: list[str]) -> list[str]:
    jurisdictions = [value.upper() for value in jurisdictions]
    providers = [
        "amazon_browser", "serpapi_google_patents", "serper_patents",
        "serper_web", "serper_images",
    ]
    if "US" in jurisdictions:
        providers += ["uspto_tmsearch_browser", "uspto_tsdr"]
    if any(value != "US" for value in jurisdictions):
        providers += ["epo_ops", "signa"]
    if "EU" in jurisdictions or any(value in EU_COUNTRIES for value in jurisdictions):
        providers += ["euipo_trademark", "euipo_design"]
    if any(value not in {"US", "EU", *EU_COUNTRIES} for value in jurisdictions):
        providers.append("official_registry_browser")
    return list(dict.fromkeys(providers))


def low_risk_gate_providers(jurisdictions: list[str]) -> list[str]:
    """Sources that must complete before a US task can clear as low risk.

    They are deliberately distinct from ``required_sources``: a detected high
    risk must still be reportable when one browser registry is temporarily
    unavailable, but a negative clearance conclusion cannot rely on that gap.
    """
    if "US" not in {value.upper() for value in jurisdictions}:
        return []
    return [
        "wipo_patentscope_browser",
        "epo_ops",
        "uspto_patent_browser",
    ]


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
