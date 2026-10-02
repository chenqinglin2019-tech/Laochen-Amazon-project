"""Version predicates shared by the existing execution and publication paths.

No credentials, mutable state, or source authority is interpreted here.
"""

LEGACY_REVISION = "necessary-work-v1"
CURRENT_REVISION = "necessary-work-v3"
LEGACY_CURRENT_REVISION = "necessary-work-v2"
SUPPORTED_REVISIONS = frozenset({LEGACY_REVISION, LEGACY_CURRENT_REVISION, CURRENT_REVISION})


def supported(task):
    return isinstance(task, dict) and task.get("completion_policy_revision") in SUPPORTED_REVISIONS


FAILURE_LIMITS_REVISION = "failure-limits-v1"


def failure_limits_enabled(task):
    """New tasks may deliver a limited report when a failed/stopped action has no further route.

    Absent on every existing task, so their stopping and publication behavior is unchanged.
    """
    value = task.get("limited_delivery_revision") if isinstance(task, dict) else None
    if value is None:
        return False
    if value != FAILURE_LIMITS_REVISION:
        raise ValueError("LIMITED_DELIVERY_REVISION_INVALID")
    return True


def evidence_delivery_enabled(task):
    return isinstance(task, dict) and task.get("completion_policy_revision") in {LEGACY_CURRENT_REVISION, CURRENT_REVISION}
