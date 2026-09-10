"""Small CLI envelopes; authoritative audit history stays in project files."""
from pathlib import Path
import re


def safe_text_payload(value):
    """Never serialize native image blocks or data URLs, including detail mode."""
    if isinstance(value, dict):
        if value.get("type") in {"image", "image_url", "input_image"}:
            return {"type": value["type"], "display": "native_image_only"}
        return {key: safe_text_payload(child) for key, child in value.items()
                if key not in {"b64_json", "base64"}}
    if isinstance(value, (list, tuple)):
        return [safe_text_payload(child) for child in value]
    if isinstance(value, str):
        return re.sub(r"data:image/[^;,\s]+;base64,[A-Za-z0-9+/=\s]+", "[native image omitted]", value)
    return value


def compact_result(value, command, manifest_path=None):
    if not isinstance(value, dict):
        return value
    result = dict(value)
    # Preserve action/packet paths and structured errors for existing callers.
    # Large proof and timing bodies are already persisted by their producer.
    for key in ("metrics", "timing_definitions", "project_contracts", "delivery_result"):
        result.pop(key, None)
    if command == "attempt-event":
        keep = {"id", "status", "prompt_hash", "tool_started_at", "tool_returned_at", "dispatched_at"}
        result = {key: child for key, child in result.items() if key in keep}
    if command in {"deliver", "delivery-check", "compact"} and manifest_path:
        report = "compaction_report.json" if command == "compact" else "delivery_report.json"
        result["report"] = str(Path(manifest_path).parent / report)
    if command == "compact" and isinstance(result.get("removed"), list):
        result["removed_count"] = len(result.pop("removed"))
    return result
