"""Versioned account-capacity and frozen source settings for new tasks.

Existing free-policy tasks retain their original account and quota contracts.
No policy in this module authorizes purchasing, recharging or upgrading.
"""
from __future__ import annotations

import math

REVISION = "existing-account-capacity-v1"
CONFIG_REVISION = "frozen-source-settings-v1"


def account_policy():
    from common import active_free_policy
    return {**active_free_policy(), "mode": "existing_account_capacity",
            "allow_paid": True, "allow_new_purchase": False,
            "allow_recharge": False, "allow_upgrade": False}


def enabled(task):
    return (isinstance(task, dict) and task.get("free_policy_revision") == REVISION
            and task.get("free_policy") == account_policy())


def cost_ceiling(task):
    return None if enabled(task) else 0


def dynamic_max_age_hours(task, config=None):
    retrieval = task.get("retrieval_policy") or {}
    if not isinstance(retrieval, dict):
        raise ValueError("SOURCE_FRESHNESS_POLICY_INVALID")
    if task.get("source_settings_revision") == CONFIG_REVISION:
        value = retrieval.get("dynamic_evidence_max_age_hours")
    elif config is not None:
        value = config.get("performance", {}).get("dynamic_evidence_max_age_hours", 48)
    else:
        value = retrieval.get("dynamic_evidence_max_age_hours", 48)
    if isinstance(value, bool):
        raise ValueError("SOURCE_FRESHNESS_POLICY_INVALID")
    try:
        hours = float(value)
    except (TypeError, ValueError):
        raise ValueError("SOURCE_FRESHNESS_POLICY_INVALID") from None
    if not math.isfinite(hours) or hours <= 0:
        raise ValueError("SOURCE_FRESHNESS_POLICY_INVALID")
    return hours


def signa_limit(task):
    value = task.get("signa_free_enhancement", {}).get("max_queries_per_task", 3)
    if type(value) is not int or not 1 <= value <= 3:
        raise ValueError("SIGNA_FREE_ENHANCEMENT_INVALID")
    return value
