"""r10 (eu-scope-v1, owner decisions 2026-11-17): the EU marketplace runs of 2026-11-12 and 2026-11-17.

Both German marketplace runs (targets EU + DE) ended without a report. The EU patent scope is searched with
``country:EP`` (``api_first_planning``), so every patent candidate is an EP publication; the positioned triage
(``candidate-triage-scope-v1``) compared that office with the task countries, found ``EP`` in neither and put all of
them in ``UNLOCATED`` (11-17: 698 EP cards, the 8 selected candidates all EP). From there the comparison host's
feedback request was refused (``jurisdiction=UNLOCATED``), the final review had no row for them and the publication
gate refused the run; the review packet was also over the host limit because every rule that keeps the deep checks
small (expired, lapsed, foreign publication, the cap of six) only knew US documents.

New tasks carry ``eu_scope_revision`` and get:

* ``scope_origin``: the task scope a candidate's own office belongs to. An EP publication belongs to the EU scope (the
  convention the older layers already follow: ``merge_candidates``, ``finalize_assessment``, ``workflow_v24``); in a
  task without EU and exactly one EPC country (a UK or a single-country task) it belongs to that country. The
  candidate record itself keeps ``EP`` (its publication identity is checked against its own number). Whether the
  patent is in force in a member state stays a fact to verify (``trusted_api.DYNAMIC`` is never taken from an EP
  record for another territory).
* the deep-check rules for European documents (``focus_rule``, ``inactive_status``): an EP publication filed more than
  21 years ago, an EP card whose own Google Patents status reads NOT_ACTIVE, and a publication of an office outside
  the task scope (WO, CN, US ... in an EU task) are recorded not selected by the ordinary triage recorder, reopenable.
* ``unlocated_selected_limitation``: a selected candidate the run could not place in any target scope is disclosed as
  a limitation of the report ("selected, not assessed") instead of refusing the publication.
* ``looks_german``: listing text in German is not offered to the planner as an English search term.

US-only tasks are unaffected by every rule here except the review packet budget (``review_budget``), which only acts
on a packet that would otherwise exceed the review host limit.
"""
from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path

REVISION = 'eu-scope-v1'
TASK_FIELD = 'eu_scope_revision'
EPC_TARGETS = ('GB', 'FR', 'DE', 'IT', 'ES')
PATENT_RIGHTS = frozenset({'patent', 'utility_model', 'design'})
EP_TERM_YEARS, EP_MARGIN_YEARS = 20, 1      # 20 years from filing (Art. 63 EPC); SPCs do not concern consumer goods
UNLOCATED_REASON = 'SELECTED_CANDIDATE_UNLOCATED'


def enabled(task) -> bool:
    return isinstance(task, dict) and task.get(TASK_FIELD) == REVISION


def non_us(task) -> bool:
    """A marked task with a target other than the US alone (US-only tasks keep every earlier rule)."""
    countries = targets(task)
    return enabled(task) and bool(countries) and countries != ['US']


def targets(task) -> list:
    return [str(value).upper() for value in (task or {}).get('target_jurisdictions') or []]


def ep_scope(task) -> str:
    """The target scope EP publications belong to in this task, or '' (none, or ambiguous)."""
    if not enabled(task):
        return ''
    countries = targets(task)
    if 'EU' in countries:
        return 'EU'
    national = [country for country in countries if country in EPC_TARGETS]
    return national[0] if len(national) == 1 else ''


def office(candidate) -> str:
    return str((candidate or {}).get('jurisdiction') or (candidate or {}).get('office') or '').upper()


def scope_origin(task, candidate=None, origin=None) -> str:
    """The scope country of a candidate's own office (``origin`` overrides the candidate's office field)."""
    value = str(office(candidate) if origin is None else origin or '').upper()
    if value == 'EP':
        mapped = ep_scope(task)
        if mapped:
            return mapped
    return value


def same_scope(task, candidate, country) -> bool:
    return scope_origin(task, candidate) == str(country or '').upper()


# ----- deep-check rules for European documents ------------------------------------------------------------------------
def _number(value) -> str:
    return re.sub(r'[^A-Za-z0-9]', '', str(value or '')).upper()


def _number_office(candidate) -> str:
    number = _number(candidate.get('publication_number'))
    return number[:2] if re.match(r'^[A-Z]{2}\d', number) else ''


def _in_scope_office(task, code) -> bool:
    return bool(code) and scope_origin(task, None, code) in targets(task)


def _filing_year(candidate):
    for key in ('filing_date', 'application_date', 'priority_date'):
        text = str(candidate.get(key) or '')
        if re.match(r'^(?:19|20)\d{2}-', text):
            return int(text[:4]), key
    return None, None


def ep_expired(candidate, *, today=None):
    """A short reason when an EP patent's own filing date proves its 20-year term is over, else None."""
    if candidate.get('right_type') not in {'patent', 'utility_model'} or _number_office(candidate) != 'EP':
        return None
    year, key = _filing_year(candidate)
    if key != 'filing_date' or not year:
        return None     # a priority date may precede the EP filing that starts the term
    current = (today or date.today()).year
    if year + EP_TERM_YEARS + EP_MARGIN_YEARS < current:
        return ('%s 的欧洲专利申请日为 %d 年；欧洲专利保护期自申请日起 %d 年（留 %d 年余量）已届满'
                % (_number(candidate.get('publication_number')), year, EP_TERM_YEARS, EP_MARGIN_YEARS))
    return None


def foreign_publication(candidate, task, others):
    """(rule, reason) for a patent publication of an office outside a non-US task's scope, else None."""
    countries = targets(task)
    if not enabled(task) or not countries or countries == ['US']:
        return None
    if candidate.get('right_type') not in PATENT_RIGHTS:
        return None
    code = _number_office(candidate)
    if not code or _in_scope_office(task, code):
        return None
    names = '、'.join(countries)
    family = candidate.get('family_id')
    sibling = next((row.get('publication_number') for row in others if family and row.get('family_id') == family
                    and _in_scope_office(task, _number_office(row))
                    and row.get('candidate_id') != candidate.get('candidate_id')), None)
    number = _number(candidate.get('publication_number'))
    if sibling:
        return 'family_duplicate_eu', ('%s 是 %s 的同族文献，在本次目标范围（%s）的效力由该同族文献承担核验'
                                       % (number, _number(sibling), names))
    return 'foreign_publication_eu', ('%s 是国际申请或目标范围（%s）以外的公开文献，本身在目标范围内没有专利效力；'
                                      '若其进入欧洲或目标国，会以欧洲（EP）或该国号码另行出现' % (number, names))


def focus_rule(candidate, task, others, *, today=None):
    """(rule, detail) of the European deep-check defaults, or None (``triage_defaults.focus_rule``)."""
    if not enabled(task) or targets(task) == ['US']:
        return None
    reason = ep_expired(candidate, today=today)
    if reason:
        return 'expired_ep', reason
    return foreign_publication(candidate, task, others)


def card_statuses(task_dir) -> dict:
    """{publication number: {country: status}} from the task's own SerpApi Google Patents search receipts."""
    found = {}
    folder = Path(task_dir) / 'raw' / 'serpapi_google_patents'
    for path in sorted(folder.glob('*.json')) if folder.is_dir() else []:
        try:
            data = json.loads(path.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            continue
        payload = data.get('payload', data) if isinstance(data, dict) else {}
        rows = payload.get('organic_results') if isinstance(payload, dict) else None
        for row in rows if isinstance(rows, list) else []:
            statuses = row.get('country_status') if isinstance(row, dict) else None
            number = _number(row.get('publication_number')) if isinstance(row, dict) else ''
            if number and isinstance(statuses, dict):
                found.setdefault(number, {'status': {}, 'receipt': path.name})['status'].update(
                    {str(key).upper(): value for key, value in statuses.items() if isinstance(value, str)})
    return found


def inactive_status(candidate, statuses, task):
    """A reason when an EP card's own search record reports the EP status NOT_ACTIVE (EU-scope tasks), else None."""
    if not enabled(task) or ep_scope(task) == '' or candidate.get('right_type') not in {'patent', 'utility_model'}:
        return None
    number = _number(candidate.get('publication_number'))
    if not number.startswith('EP'):
        return None
    row = statuses.get(number)
    if not row or row['status'].get('EP') != 'NOT_ACTIVE':
        return None
    return ('检索记录（Google Patents，SerpApi 检索回执 %s）显示 %s 的欧洲专利状态为已失效（NOT_ACTIVE）'
            % (row['receipt'], number))


TEXTS = {
    'expired_ep': ('按候选自身申请日计算，欧洲专利保护期已届满，不能对本商品构成现时专利风险',
                   '候选的保护期已届满，不再能对拟售产品主张专利权；技术内容与产品的关系不再影响本次决策。',
                   ['取得该文献存在更晚申请日或期限延长的官方记录时重新分流', '候选身份或日期信息被更正时重新分流'],
                   '欧洲专利保护期已届满'),
    'inactive_ep_status': ('检索记录显示该欧洲专利已失效，不能对本商品构成现时专利风险',
                           '检索记录显示该欧洲专利已不再有效，不能对拟售产品主张专利权；技术内容与产品的关系不再影响本次决策。',
                           ['取得该欧洲专利在目标国仍然有效（含恢复、异议后维持）的官方记录时重新分流',
                            '出现以该文献主张权利的投诉或诉讼时重新分流'],
                           '检索记录显示欧洲专利已失效'),
    'foreign_publication_eu': ('国际申请或目标范围以外的公开文献本身在目标范围内没有专利效力',
                               '该文献不是目标范围（欧洲专利或目标国）的文献，不能在目标范围内对拟售产品主张权利。',
                               ['发现该文献的欧洲或目标国同族时，以该同族文献重新分流',
                                '任务目标国家增加该文献所属国家或地区时重新分流'],
                               '目标范围以外的公开文献'),
    'family_duplicate_eu': ('同族文献已在目标范围内另行出现，本件不重复深查',
                            '目标范围内的效力由同族的欧洲或目标国文献承担核验，本件不重复比较。',
                            ['同族的目标范围文献被排除或身份被更正时重新分流',
                             '任务目标国家增加该文献所属国家或地区时重新分流'],
                            '目标范围以外的同族文献'),
}


# ----- publication gate --------------------------------------------------------------------------------------------
def unlocated_selected_limitation(task, row):
    """The disclosed limitation for a selected candidate left in the UNLOCATED scope, or None."""
    if not enabled(task) or str(row.get('jurisdiction') or '') != 'UNLOCATED':
        return None
    annotation = row.get('annotation') if isinstance(row.get('annotation'), dict) else {}
    refs = [ref for ref in annotation.get('evidence_refs') or [] if isinstance(ref, str)]
    return {'scenario_id': row.get('scenario_id'), 'jurisdiction': 'UNLOCATED', 'right_type': row.get('right_type'),
            'candidate_id': row.get('candidate_id'), 'state': 'blocked', 'reason': UNLOCATED_REASON,
            'evidence_refs': sorted(set(refs)), 'official_verification': 'not_verified',
            'reasoning': ('该候选在分流中被选为相关，但本轮未能把它定位到任一目标国家或地区（来源国或权利类型未知），'
                          '因此没有进入终审评级；本项风险待定，不代表无风险，需人工核实其权利地域和效力。')}


# ----- product understanding -----------------------------------------------------------------------------------------
# 'die' and 'den' are left out: they are English words too (die-cast housing, den)
_GERMAN_WORDS = frozenset({'und', 'mit', 'fur', 'für', 'der', 'das', 'dem', 'des', 'ein', 'eine',
                           'einer', 'einem', 'einen', 'zum', 'zur', 'aus', 'oder', 'bei', 'von', 'auf', 'im', 'ist',
                           'nicht', 'ohne', 'inkl', 'fuer', 'mehrfach', 'steckdose', 'steckdosenleiste',
                           'schalter', 'nachtlicht', 'kabel', 'stecker'})


def looks_german(text) -> bool:
    """True when a term is German listing text (umlaut/sharp s, or a German function word)."""
    value = str(text or '').casefold()
    if re.search(r'[äöüß]', value):
        return True
    return any(word in _GERMAN_WORDS for word in re.findall(r"[a-zäöüß]+", value))
