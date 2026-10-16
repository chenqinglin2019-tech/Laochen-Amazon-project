"""New-task execution policy; never a risk, coverage or authorization policy."""
from contextlib import contextmanager
from contextvars import ContextVar
from copy import deepcopy
from pathlib import Path
from common import sha256_json

LEGACY_REVISION = 'execution-efficiency-v1'
REVISION = 'execution-efficiency-v2'
DEFAULTS = {'review_text_chars': 60000, 'review_images': 12,
            'review_units': 24, 'review_json_chars': 120000,
            'media_workers': 4, 'media_timeout_seconds': 15, 'media_max_bytes': 8388608,
            'vision_batch_candidates': 6, 'vision_product_images': 2,
            'vision_parallel': 2, 'vision_timeout_seconds': 180}
_VIEWS = ContextVar('ipr_validated_work_views', default=None)


def enabled(task):
    revision = task.get('execution_efficiency_revision')
    if revision not in (None, LEGACY_REVISION, REVISION):
        raise ValueError('EXECUTION_EFFICIENCY_REVISION_INVALID')
    return revision is not None


def revised(task):
    """Second-round execution semantics apply only to explicitly frozen new tasks."""
    enabled(task)
    return task.get('execution_efficiency_revision') == REVISION


def policy(task):
    if not enabled(task):
        return None
    values = task.get('execution_efficiency')
    if (not isinstance(values, dict) or set(values) != set(DEFAULTS)
            or any(type(v) is not int or v <= 0 for v in values.values())):
        raise ValueError('EXECUTION_EFFICIENCY_POLICY_INVALID')
    return values


def view_key(task_dir, options):
    return (str(Path(task_dir).resolve()), sha256_json(options))


@contextmanager
def collect_work_views():
    """Only the independent validator creates this in-memory collection."""
    values = {}
    token = _VIEWS.set(values)
    try:
        yield values
    finally:
        _VIEWS.reset(token)


def capture_work_view(task_dir, options, view):
    values = _VIEWS.get()
    if values is not None:
        values[view_key(task_dir, options)] = deepcopy(view)
