"""Stage selection for the existing API and browser dispatchers."""
from __future__ import annotations


def selected_phase(task: dict, phase: str, transport: str) -> str:
    if task.get("retrieval_workflow_revision") != "api-first-v1":
        if phase:
            raise ValueError("RETRIEVAL_PHASE_REQUIRES_API_FIRST_TASK")
        return ""
    allowed = {"discovery", "verification"} if transport == "api" else {"verification", "fallback"}
    chosen = phase or ("discovery" if transport == "api" else "verification")
    if chosen not in allowed:
        raise ValueError("RETRIEVAL_PHASE_INVALID")
    return chosen


def in_phase(row: dict, phase: str) -> bool:
    if not phase:
        return True
    current = row.get("execution_phase")
    if phase == "fallback":
        return current == "discovery_fallback"
    if phase == "verification":
        return current in {"verification", "enrichment", "needs_info"}
    return current in {"discovery", "expansion"} and row.get("action_purpose") not in {"verification", "needs_info"}
