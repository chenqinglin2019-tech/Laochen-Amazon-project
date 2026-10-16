"""Candidate precision for new tasks (``candidate_precision_revision='precision-v1'``, r5d21).

Two real runs of 2026-10-14 spent most of their time on candidates that could not matter: half of the utility cards a
search returned were no longer in force in the US (the SerpApi card says so), the triage bar "same kind of article or
same use" selected a trailer patent whose snippet mentioned a grill basket, US designs nobody had seen were selected
by rule, and the list screen kept "anything possibly related" for a second, per-candidate triage. The owner decided
(2026-10-15): deep checks are capped at 8 designs and 6 utility patents, unseen designs are deep-checked only when
their title is the product's own specific article name, and the screen's decision is the triage decision.

This module holds the shared, deterministic parts; the recorders still validate every decision.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

REVISION = 'precision-v1'
DESIGN_CAP, UTILITY_CAP = 8, 6
SCREEN_DRAWINGS = 2         # drawing pages the design screen looks at (screen_pictures); r5d24 retrieves only these
DESIGN_TIERS = ('same', 'similar')
UTILITY_TIERS = ('core', 'related')


def enabled(task) -> bool:
    return isinstance(task, dict) and task.get('candidate_precision_revision') == REVISION


# ----- US status from the search card -------------------------------------------------------------------------------
def _number(value) -> str:
    return re.sub(r'[^A-Za-z0-9]', '', str(value or '')).upper()


def card_statuses(task_dir) -> dict:
    """{publication number: US status} from the retained SerpApi Google Patents search receipts of this task.

    Every organic result carries Google's ``country_status`` (e.g. {"US": "NOT_ACTIVE"}); only search receipts of the
    task's own runs are read (raw/serpapi_google_patents/*.json)."""
    statuses = {}
    folder = Path(task_dir) / 'raw' / 'serpapi_google_patents'
    for path in sorted(folder.glob('*.json')) if folder.is_dir() else []:
        try:
            data = json.loads(path.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            continue
        for row in data.get('organic_results') or [] if isinstance(data, dict) else []:
            if not isinstance(row, dict):
                continue
            number = _number(row.get('publication_number'))
            status = (row.get('country_status') or {}).get('US') if isinstance(row.get('country_status'), dict) else None
            if number and isinstance(status, str):
                statuses.setdefault(number, {'status': status, 'grant_date': row.get('grant_date') or '',
                                             'priority_date': row.get('priority_date') or '',
                                             'receipt': path.name})
    return statuses


def inactive_us_status(candidate: dict, statuses: dict):
    """A short reason when the candidate's own search card says it is no longer in force in the US, else None."""
    number = _number(candidate.get('publication_number'))
    if not number.startswith('US') or candidate.get('right_type') not in {'patent', 'utility_model', 'design'}:
        return None
    row = statuses.get(number)
    if not row or row.get('status') != 'NOT_ACTIVE':
        return None
    return ('检索记录（Google Patents，SerpApi 检索回执 %s）显示 %s 在美国的状态为已失效（NOT_ACTIVE），'
            '本身不构成现行有效的美国权利；如日后有新的有效记录可重新分流' % (row.get('receipt') or '', number))


# ----- design pictures and specific article names ------------------------------------------------------------------
PICTURE_SUFFIXES = {'.png', '.jpg', '.jpeg', '.webp'}


def candidate_pictures(registry: dict, candidate_id: str, auto_ref=None) -> list:
    """Retained pictures of one candidate, best first: the search card's own thumbnail (``auto_ref``), then the
    retained drawings (Google page drawings, USPTO grant PDF pages) in page order. Drawings retained by
    ``pipeline_robust.retain_design_pictures`` carry the candidate only inside their payload."""
    rows = []
    for row in registry.values():
        if not isinstance(row, dict) or not row.get('path') or not row.get('sha256'):
            continue
        payload = row.get('payload') if isinstance(row.get('payload'), dict) else {}
        owner = row.get('candidate_id') or payload.get('candidate_id')
        if owner != candidate_id or Path(str(row['path'])).suffix.lower() not in PICTURE_SUFFIXES:
            continue
        identifier = str(row.get('evidence_id') or '')
        if identifier.startswith('MEDIA-') and identifier != auto_ref:
            continue
        rows.append(row)

    def order(row):
        thumbnail = str(row.get('evidence_id') or '') == auto_ref
        return (0 if thumbnail else 1, str(row.get('figure_label') or ''), str(row.get('path')))
    return sorted(rows, key=order)


def screen_pictures(pictures: list) -> list:
    """The card thumbnail alone when there is one (the representative view), else the first two drawing pages."""
    if not pictures:
        return []
    return pictures[:1] if str(pictures[0].get('evidence_id') or '').startswith('MEDIA-') else pictures[:SCREEN_DRAWINGS]


_SUFFIX = re.compile(r'(ing|ed|es|s)$')


def _stems(text: str) -> tuple:
    words = re.findall(r'[a-z]+', str(text or '').lower())
    return tuple(sorted({_SUFFIX.sub('', word) if len(word) > 4 else word for word in words}))


def specific_names(task: dict) -> list:
    """The product's specific article names: the quoted phrases of its design-names group (recall-v1 D1, which the
    understanding keeps free of broad category names)."""
    import recall
    levels = recall.recorded_levels(task)
    if levels is not None:
        # r5d25 title-phrases tasks: the design query also carries the category names; the term records which are which
        return list(dict.fromkeys(levels['specific']))
    names = []
    for row in task.get('query_terms') or []:
        if isinstance(row, dict) and row.get('discovery_problem_id') == 'recall-v1:design-names':
            names += re.findall(r'"([^"]+)"', str(row.get('value') or ''))
    return list(dict.fromkeys(name.strip().lower() for name in names if name.strip()))


def title_matches(title: str, names: list):
    """The specific name an (unseen) design's title is, word for word up to plural / -ing / -ed endings, or None."""
    own = _stems(title)
    for name in names:
        if own and own == _stems(name):
            return name
    return None


def broad_names(task: dict) -> set:
    """Category names the understanding marked broad: the names its utility groups carry but its design-names group
    (D1, specific names only) leaves out - e.g. "pet toy", "cat toy", "grill basket"."""
    import recall
    levels = recall.recorded_levels(task)
    if levels is not None:
        # r7: a name the design query left out (search-guard-v1) is broad as well
        return set(levels['category']) | set(levels['upper']) | set(levels.get('design_excluded') or [])
    specific = set(specific_names(task))
    broad = set()
    for row in task.get('query_terms') or []:
        if isinstance(row, dict) and str(row.get('discovery_problem_id') or '').startswith(
                ('recall-v1:function-', 'recall-v1:article-names')):
            names = str(row.get('value') or '').split(' AND ')[0]
            broad.update(name.strip().lower() for name in re.findall(r'"([^"]+)"', names))
    return broad - specific
