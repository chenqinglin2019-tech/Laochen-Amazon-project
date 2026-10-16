"""r6 (report-always-v1): one definition of the evidence that belongs to a candidate.

Run B0GFNWR8FW: a reviewer's 低 row for US8894311B2 cited the patent's own Google Patents page (retained by the core
dossier) and one of its drawings. Neither counted as the candidate's evidence - not for the module check
(``candidate_counter_refs``) and not at publication (``bound_actual`` reads only a top-level ``candidate_id``, and
``_substantive_refs`` admits only search-shaped payloads) - although they are the most specific material there is.
The module was refused twice and the run ended without a report.

Marked tasks use ``evidence_roles`` everywhere a candidate's own evidence is decided: the review packet lists it per
candidate, the module check and publication accept a rating that cites it. It is a superset of the earlier list:

* discovery     the search receipt whose results list the candidate (the existing rule);
* detail_record the exact API detail record of the candidate;
* api_fact      a trusted API record whose accepted facts belong to the candidate;
* document      a retained public document of the candidate (Google Patents page, grant PDF, design document);
* drawing       a retained drawing of the candidate;
* record        any other successful, retained registry entry the frozen input binds to the candidate.

A record of another country or right, a failed request, product material and an unreadable binding never count.
"""
import re

from report_always import enabled

ROLE_LABELS = {'discovery': '检索结果卡片', 'detail_record': '准确详情记录（权利要求、状态）',
               'api_fact': '可信 API 记录', 'document': '留存公开文本', 'drawing': '留存附图', 'record': '其他留存记录'}
_DRAWING_KINDS = {'patent_drawing_image', 'design_drawing_image', 'design_drawings', 'drawing_image'}
_DOCUMENT_KINDS = {'patent_document', 'design_document', 'official_record', 'rights_record'}
_PRODUCT_PROVIDERS = {'amazon_browser', 'product', 'seller_sprite'}


def _number(value):
    return re.sub(r'[^A-Z0-9]', '', str(value or '').upper())


def _numbers_match(left, right):
    """US8894311B2 = US8894311; USD1035381S = USD1035381S1 (a publication's kind code is not part of its identity)."""
    def stem(value):
        match = re.match(r'^([A-Z]{2}D?)0*(\d+)', _number(value))
        return (match.group(1) + match.group(2)) if match else None
    a, b = stem(left), stem(right)
    return bool(a and a == b)


def _payload(entry):
    payload = entry.get('payload')
    return payload if isinstance(payload, dict) else {}


def _owner(entry):
    return entry.get('candidate_id') or _payload(entry).get('candidate_id')


def evidence_roles(task, evidence, candidates, registry, candidate_id, jurisdiction, right_type):
    """{evidence id: role} for one candidate, country and right (empty when the candidate is unknown)."""
    from annotate_materiality import iter_candidates
    from assessment_estimate import _substantive_refs
    candidate = next((item for _, item in iter_candidates(candidates) if item.get('candidate_id') == candidate_id), None)
    if not candidate:
        return {}
    country = str(jurisdiction or '').upper()
    runs = {run['run_id']: run for run in (evidence or {}).get('source_runs', [])
            if isinstance(run, dict) and run.get('run_id')}
    row = {'jurisdiction': country, 'right_type': right_type, 'candidate_id': candidate_id}
    listed = set(candidate.get('evidence_refs') or []) | set(candidate.get('verification_refs') or [])
    accepted = set()
    from trusted_api import enabled as trusted_enabled, accepted_candidate_facts
    if trusted_enabled(task):
        facts = accepted_candidate_facts(task, evidence, candidate, country, right_type)
        accepted = {ref for fact in facts.values() for ref in fact.get('evidence_refs', [])}
    roles = {}
    for ref, entry in registry.items():
        if not isinstance(entry, dict) or entry.get('provider') in _PRODUCT_PROVIDERS:
            continue
        owned = _owner(entry) == candidate_id
        if not (ref in listed or ref in accepted or owned):
            continue
        run = runs.get(entry.get('source_run_id'))
        if entry.get('source_run_id') and (not run or run.get('status') != 'success'):
            continue
        if (str(entry.get('jurisdiction') or (run or {}).get('jurisdiction') or '').upper() != country
                or (entry.get('right_type') or (run or {}).get('right_type')) != right_type):
            continue
        payload = _payload(entry)
        kind = entry.get('kind') or payload.get('kind')
        if entry.get('provider') == 'public_source' and entry.get('operation') == 'retained_document':
            if (run is None or run.get('provider') != entry.get('provider') or run.get('operation') != entry.get('operation')
                    or run.get('query_id') != entry.get('query_id')):
                continue
            if not (entry.get('path') or payload.get('path')) or not (entry.get('sha256') or payload.get('sha256')):
                continue
            if not str(entry.get('source_url') or payload.get('source_url') or '').startswith(('http://', 'https://')):
                continue
            number = entry.get('publication_number') or payload.get('publication_number')
            if not (owned or (number and _numbers_match(number, candidate.get('publication_number')))):
                continue
            roles[ref] = 'drawing' if kind in _DRAWING_KINDS else 'document' if kind in _DOCUMENT_KINDS else 'record'
            continue
        if ref in accepted:
            roles[ref] = 'detail_record' if entry.get('operation') == 'candidate_detail' else 'api_fact'
            continue
        if not _substantive_refs([ref], registry, runs, row=row):
            continue
        if entry.get('operation') == 'search' or isinstance(payload.get('candidates'), list):
            roles[ref] = 'discovery'
        elif entry.get('operation') == 'candidate_detail':
            roles[ref] = 'detail_record'
        elif kind in _DRAWING_KINDS:
            roles[ref] = 'drawing'
        else:
            roles[ref] = 'record'
    return dict(sorted(roles.items()))


def bindable(task, evidence, candidates, registry, candidate_id, jurisdiction, right_type):
    """Sorted evidence ids a rating of this candidate may cite (``assessment_estimate.bindable_candidate_refs``)."""
    return sorted(evidence_roles(task, evidence, candidates, registry, candidate_id, jurisdiction, right_type))


def selected_candidates(frozen, rights):
    """[(candidate id, jurisdiction, right type)] currently selected for the module's rights and target countries."""
    from decision_workflow import triage_summary
    task, evidence, candidates = frozen['task'], frozen['evidence'], frozen['candidates']
    targets = {str(value).upper() for value in task.get('target_jurisdictions') or []}
    try:
        records = triage_summary(task, candidates, frozen.get('materiality_ledger') or {}, evidence=evidence,
                                 supplement=frozen.get('supplement')).get('records', [])
    except (ValueError, KeyError, TypeError):
        return []
    found = []
    for row in records:
        if (row.get('decision') == 'selected' and row.get('right_type') in rights and row.get('candidate_id')
                and str(row.get('jurisdiction') or '').upper() in targets):
            key = (row['candidate_id'], str(row['jurisdiction']).upper(), row['right_type'])
            if key not in found:
                found.append(key)
    return found


def packet_index(frozen, rights, registry=None):
    """{candidate id: {'jurisdiction', 'right_type', 'publication_number', 'title', 'evidence': [{ref, role, label}]}}
    for the module packet: what each selected candidate's rating can cite, by role."""
    from annotate_materiality import iter_candidates
    from assessment_v24 import evidence_index
    registry = registry if registry is not None else evidence_index(frozen['evidence'])
    cards = {item.get('candidate_id'): item for _, item in iter_candidates(frozen['candidates'])}
    result = {}
    for cid, country, right in selected_candidates(frozen, rights):
        roles = evidence_roles(frozen['task'], frozen['evidence'], frozen['candidates'], registry, cid, country, right)
        card = cards.get(cid) or {}
        result[cid] = {'jurisdiction': country, 'right_type': right,
                       'publication_number': card.get('publication_number') or card.get('registration_number'),
                       'title': card.get('title'),
                       'evidence': [{'ref': ref, 'role': role, 'label': ROLE_LABELS[role]} for ref, role in roles.items()]}
    return dict(sorted(result.items()))


def binding_refs(index):
    """{candidate id: [evidence ids]} from a packet index (the shape ``candidate_counter_refs`` had)."""
    return {cid: [item['ref'] for item in info.get('evidence', [])] for cid, info in (index or {}).items()}


def rating_binding(row, refs):
    """The publication's own condition for a candidate rating, checked on the module answer (marked tasks).

    * a rated row names a currently selected candidate of the module;
    * 极低 (or decisive_exclusion): the exclusion cites one of the candidate's evidence ids;
    * 中 / 高 / 极高: one supporting argument cites one of them;
    * 低: comparison.criteria is present and the counter arguments together cite one of them (publication moves
      counter arguments without such a citation aside instead of refusing the row).
    Returns a problem code or None. A candidate without any evidence of its own is left to publication."""
    from assessment_estimate import RISKS
    cid, risk = row.get('candidate_id'), row.get('risk')
    if not cid or risk not in RISKS:
        return None
    if cid not in refs:
        return 'ASSESSMENT_REQUIRES_CURRENT_SELECTED_TRIAGE'
    own = set(refs.get(cid) or [])
    if not own:
        return None
    decisive = row.get('decisive_exclusion') if isinstance(row.get('decisive_exclusion'), dict) else None
    if risk == '极低' or decisive:
        return None if set((decisive or {}).get('evidence_refs') or []) & own else 'CANDIDATE_RATING_BINDING_REQUIRED'
    if risk in {'中', '高', '极高'}:
        cited = {ref for arg in row.get('supporting_evidence') or [] if isinstance(arg, dict)
                 for ref in arg.get('evidence_refs') or []}
        return None if cited & own else 'CANDIDATE_RATING_BINDING_REQUIRED'
    criteria = (row.get('comparison') or {}).get('criteria') if isinstance(row.get('comparison'), dict) else None
    if not isinstance(criteria, list) or not criteria:
        return 'CANDIDATE_RATING_CRITERIA_REQUIRED'
    cited = {ref for arg in row.get('counter_evidence') or [] if isinstance(arg, dict)
             for ref in arg.get('evidence_refs') or []}
    return None if cited & own else 'CANDIDATE_RATING_BINDING_REQUIRED'


__all__ = ['enabled', 'evidence_roles', 'bindable', 'selected_candidates', 'packet_index', 'binding_refs',
           'rating_binding', 'ROLE_LABELS']
