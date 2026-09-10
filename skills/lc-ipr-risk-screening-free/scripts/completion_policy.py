"""Version predicates shared by the existing execution and publication paths.

No credentials, mutable state, or source authority is interpreted here.
"""

LEGACY_REVISION = "necessary-work-v1"
CURRENT_REVISION = "necessary-work-v2"
SUPPORTED_REVISIONS = frozenset({LEGACY_REVISION, CURRENT_REVISION})


def supported(task):
    return isinstance(task, dict) and task.get("completion_policy_revision") in SUPPORTED_REVISIONS


def evidence_delivery_enabled(task):
    return isinstance(task, dict) and task.get("completion_policy_revision") == CURRENT_REVISION
