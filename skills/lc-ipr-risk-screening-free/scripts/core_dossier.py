#!/usr/bin/env python3
"""Program-built specialty dossier for every selected patent/design candidate that has an exact SerpApi detail record.

best-estimate-risk-v2 only. For each such candidate this step

1. retains the record's own drawings (up to four ``payload.images[]``, ten for a design) and its publication PDF from the public
   addresses the record names, through the public-address rules of ``candidate_media`` (a refusal, e.g. a local
   fake-IP proxy, is recorded in ``core-dossier.json`` and the step continues), and registers each file through
   ``record_public_source.py`` bound to the exact candidate (drawings: ``visual_role=patent_drawings``);
2. records, in one specialty transaction with reviewer ``program:core_dossier``, what the Agent used to type by
   hand: the intake of the current selected handoff, the trusted-API material (exact payload fields read), the
   product material, the identity/territory/status/protection/product/rights-holder facts (an assignee field
   that does not name a current holder stays ``unknown``), the classification of combined handoff gaps and the
   accounting batches of every received source;
3. when the planner already lists the remaining unknown record facts as ``API_RECORD_FACT_GAP``, records the
   bounded limitation (gap + limited follow-up) exactly as the validators require.

Nothing here compares the product with the claims, grades a risk or excludes a candidate: the inventory and the
element comparison come from ``comparison_host.py``. Every recorder re-validates its own input, so a candidate
whose records do not satisfy the contract is reported and left for the Agent. Re-running is idempotent.
"""
from __future__ import annotations

import argparse
import contextlib
import io
import json
import re
import sys
from datetime import datetime
from pathlib import Path

from common import atomic_write_bytes, atomic_write_json, load_json, now_iso, sha256_bytes, sha256_json

REVIEWER = 'program:core_dossier'
OUTPUT = 'core-dossier.json'
RIGHTS = {'patent', 'utility_model', 'design'}
MAX_DRAWINGS = 4
# A design patent's drawings are its protected subject matter; every view is retained for the view comparison.
MAX_DESIGN_DRAWINGS = 10
API_FACTS = ('identity', 'territory', 'status', 'protection', 'rights_holder')
REQUIRED_FACT_BLOCKERS = {'identity', 'territory', 'status', 'protection', 'product'}
# The selected-handoff step writes these exact sentences (mechanical_ledger._GAPS_BY_RIGHT); other texts fall back
# to keyword mapping, and a text that maps to nothing is left for the Agent.
GAP_KINDS = {
    '完整权利要求与保护范围尚未读取': ['protection'],
    '完整视图与保护范围尚未读取': ['protection'],
    '当前法律状态与权利人尚未核验': ['status', 'rights_holder'],
    '来源原件与权利事实尚未核验': ['identity', 'status'],
    'target_jurisdiction': ['territory'],
    'right_type': ['identity'],
}
KEYWORDS = (('protection', r'权利要求|保护范围|视图|claim|protection'),
            ('status', r'状态|有效|status'),
            ('rights_holder', r'权利人|权属|权利主体|owner|assignee|holder'),
            ('territory', r'地域|国家|jurisdiction|territor'),
            ('identity', r'身份|编号|号码|identity|right_type'))


def enabled(task):
    from assessment_estimate import best_estimate_v2
    return best_estimate_v2(task)


def gap_kinds(text):
    """Fact kinds a handoff verification gap names; [] when the text cannot be mapped."""
    if text in GAP_KINDS:
        return list(GAP_KINDS[text])
    value = str(text or '')
    return [kind for kind, pattern in KEYWORDS if re.search(pattern, value, re.I)]


def _identifier(value):
    from trusted_api import identifier
    return identifier(value)


def detail_entry(evidence, candidate):
    """Newest exact SerpApi candidate_detail record of the candidate (by candidate id or exact publication number)."""
    best = None
    number = _identifier(candidate.get('publication_number'))
    for group in (evidence.get('collections') or {}).values():
        for entry in group if isinstance(group, list) else []:
            payload = entry.get('payload') if isinstance(entry, dict) else None
            if (not isinstance(payload, dict) or entry.get('provider') != 'serpapi_google_patents'
                    or entry.get('operation') != 'candidate_detail'):
                continue
            if payload.get('candidate_id') != candidate.get('candidate_id') and not (
                    number and _identifier(payload.get('publication_number')) == number):
                continue
            if best is None or str(entry.get('collected_at') or '') >= str(best.get('collected_at') or ''):
                best = entry
    return best


def _day(value):
    text = str(value or '')
    return text[:10] if re.match(r'^\d{4}-\d{2}-\d{2}', text) else None


def _today():
    return datetime.now().astimezone().date().isoformat()


# ----- retained public files ------------------------------------------------------------------------------------
def _fetch_page(url, *, timeout=30):
    """A public HTML page (Google Patents) through the same public-address rules; (bytes, final_url)."""
    return _fetch_document(url, timeout=timeout, max_bytes=8 * 1024 * 1024, page=True)


def _fetch_document(url, *, timeout=30, max_bytes=25 * 1024 * 1024, page=False, browser=False):
    """A publication PDF from its public address (same address rules as candidate media); (bytes, final_url).
    ``browser`` sends the browser-style agent the page requests use (the USPTO file server)."""
    import time
    from urllib.parse import urljoin
    from candidate_media import PublicConnection, public_address
    current = url
    stop = time.monotonic() + timeout
    for _ in range(4):
        parsed, address = public_address(current, timeout=max(1, stop - time.monotonic()))
        connection = PublicConnection(parsed.hostname, address, max(1, stop - time.monotonic()))
        try:
            connection.request('GET', parsed.path + ('?' + parsed.query if parsed.query else ''),
                               headers={'Accept': 'text/html' if page else 'application/pdf',
                                        'User-Agent': 'Mozilla/5.0 (IPR-Public-Media/1.0)' if page or browser
                                        else 'IPR-Public-Media/1.0'})
            response = connection.getresponse()
            if response.status in (301, 302, 303, 307, 308):
                location = response.getheader('Location')
                if not location:
                    raise ValueError('DOCUMENT_REDIRECT_LOCATION_REQUIRED')
                current = urljoin(current, location)
                continue
            if response.status != 200:
                raise ValueError('DOCUMENT_HTTP_' + str(response.status))
            body = response.read(max_bytes + 1)
            if len(body) > max_bytes:
                raise ValueError('DOCUMENT_SIZE_LIMIT')
            if page:
                if b'<html' not in body[:4096].lower():
                    raise ValueError('DOCUMENT_NOT_HTML')
            elif not body.startswith(b'%PDF'):
                raise ValueError('DOCUMENT_NOT_PDF')
            return body, current
        finally:
            connection.close()
    raise ValueError('DOCUMENT_REDIRECT_LIMIT')


def _fetch_image(url):
    from candidate_media import download
    body, suffix, _, final = download(url, timeout=20)
    return body, suffix, final


def _register(task_dir, payload):
    """Register one retained file through record_public_source (in-process, so the caller's environment holds)."""
    import record_public_source
    inputs = Path(task_dir) / 'raw' / 'core-dossier' / 'inputs'
    inputs.mkdir(parents=True, exist_ok=True)
    path = inputs / (sha256_json(payload)[:24] + '.json')
    atomic_write_json(path, payload)
    argv = sys.argv
    sys.argv = ['record_public_source.py', '--task-dir', str(task_dir), '--input', str(path)]
    try:
        with contextlib.redirect_stdout(io.StringIO()) as out:
            record_public_source.main()
        return out.getvalue().strip()
    finally:
        sys.argv = argv


def _registered(evidence, sha256, candidate_id, *, source_url=None):
    """Evidence id of a file already retained for the candidate (by content, or by its public address)."""
    for entry in (evidence.get('collections') or {}).get('sources', []):
        payload = entry.get('payload') if isinstance(entry, dict) else None
        if (isinstance(payload, dict) and payload.get('candidate_id') == candidate_id
                and (payload.get('sha256') == sha256 if sha256 else payload.get('source_url') == source_url)):
            return entry.get('evidence_id'), payload.get('sha256')
    return None, None


REFUSED_MEDIA = ('raw', 'core-dossier', 'refused-media.json')
REFUSED_CODES = ('MEDIA_HTTP_403', 'MEDIA_HTTP_404', 'MEDIA_HTTP_410')


def _refused_media(task_dir):
    path = Path(task_dir).joinpath(*REFUSED_MEDIA)
    try:
        value = load_json(path) if path.is_file() else {}
    except (OSError, ValueError):
        value = {}
    return value if isinstance(value, dict) else {}


def _remember_refused(task_dir, url, reason):
    """r5d7: an image address the server refused for good (403 / 404 / 410) is not asked again in this task. Google
    refuses the drawings of recent grants to everyone; every core round asked again (B0GLNPC6K8: 127 refused
    requests, about 75 seconds, per round)."""
    refused = _refused_media(task_dir)
    refused[url] = reason[:120]
    atomic_write_json(Path(task_dir).joinpath(*REFUSED_MEDIA), refused)


def retain_files(task_dir, candidate, detail, *, fetch_image=_fetch_image, fetch_document=_fetch_document,
                 drawings=None):
    """Download and register the record's drawings and PDF; failures are reported, never fatal. ``drawings`` caps the
    drawings taken (r5d24: the design screen's picture retrieval takes the first two; the deep check takes the rest)."""
    task_dir = Path(task_dir)
    refused = _refused_media(task_dir)
    payload = detail['payload']
    number = str(payload.get('publication_number') or candidate.get('publication_number') or '')
    folder = task_dir / 'raw' / 'core-dossier' / re.sub(r'[^A-Za-z0-9_-]', '_', number or candidate['candidate_id'])
    common = {'publication_number': number, 'jurisdiction': candidate.get('jurisdiction') or 'US',
              'right_type': candidate.get('right_type'), 'candidate_id': candidate['candidate_id']}
    result = {'drawings': [], 'document': None, 'failures': []}
    images = [url for url in payload.get('images') or [] if isinstance(url, str) and url.startswith('https://')]
    limit = MAX_DESIGN_DRAWINGS if candidate.get('right_type') == 'design' else MAX_DRAWINGS
    if drawings is not None:
        limit = min(limit, drawings)
    for index, url in enumerate(images[:limit]):
        label = (re.search(r'-(D\d{5})\.', url) or [None, 'D%05d' % index])[1]
        known, digest = _registered(load_json(task_dir / 'evidence.json'), None, candidate['candidate_id'], source_url=url)
        if known:
            result['drawings'].append({'figure_label': label, 'sha256': digest, 'evidence_id': known, 'source_url': url,
                                       'reused': True})
            continue
        if url in refused:
            result['failures'].append({'url': url, 'kind': 'drawing', 'reason': refused[url], 'earlier_attempt': True})
            continue
        try:
            body, suffix, final = fetch_image(url)
            import image_convert
            if image_convert.format_of(suffix):
                # r5d4: a GIF / TIFF drawing is kept as its lossless PNG, the form every reader takes
                body, suffix = image_convert.to_png(body), '.png'
        except (OSError, ValueError) as exc:
            reason = (type(exc).__name__ + ':' + str(exc))[:200]
            result['failures'].append({'url': url, 'kind': 'drawing', 'reason': reason})
            if str(exc).startswith(REFUSED_CODES):
                _remember_refused(task_dir, url, reason)
                refused[url] = reason
            continue
        digest = sha256_bytes(body)
        known, _ = _registered(load_json(task_dir / 'evidence.json'), digest, candidate['candidate_id'])
        if not known:
            path = folder / (label + suffix)
            atomic_write_bytes(path, body)
            _register(task_dir, {**common, 'kind': 'patent_drawing_image', 'visual_role': 'patent_drawings',
                'figure_label': label, 'source_record_evidence_id': detail['evidence_id'], 'path': str(path),
                'sha256': digest, 'bytes': len(body), 'source_url': url,
                'reasoning': '准确详情记录 images[%d] 所列该权利自身附图，按原公开地址取回留存；仅作图样，不含比较结论。' % index})
            known, _ = _registered(load_json(task_dir / 'evidence.json'), digest, candidate['candidate_id'])
        result['drawings'].append({'figure_label': label, 'sha256': digest, 'evidence_id': known, 'source_url': url})
    pdf = payload.get('pdf')
    reused, reused_digest = (_registered(load_json(task_dir / 'evidence.json'), None, candidate['candidate_id'], source_url=pdf)
                             if isinstance(pdf, str) else (None, None))
    if reused:
        result['document'] = {'sha256': reused_digest, 'evidence_id': reused, 'source_url': pdf, 'reused': True}
    elif isinstance(pdf, str) and pdf.startswith('https://'):
        try:
            body, final = fetch_document(pdf)
        except (OSError, ValueError) as exc:
            result['failures'].append({'url': pdf, 'kind': 'document', 'reason': (type(exc).__name__ + ':' + str(exc))[:200]})
        else:
            digest = sha256_bytes(body)
            known, _ = _registered(load_json(task_dir / 'evidence.json'), digest, candidate['candidate_id'])
            if not known:
                path = folder / ((number or 'document') + '.pdf')
                atomic_write_bytes(path, body)
                _register(task_dir, {**common, 'kind': 'design_document' if candidate.get('right_type') == 'design'
                    else 'patent_document', 'path': str(path), 'sha256': digest, 'bytes': len(body), 'source_url': pdf,
                    'reasoning': '准确详情记录 pdf 字段所列该权利公开文本，按原公开地址取回留存。'})
                known, _ = _registered(load_json(task_dir / 'evidence.json'), digest, candidate['candidate_id'])
            result['document'] = {'sha256': digest, 'evidence_id': known, 'source_url': pdf}
    return result


def retained_media_fetcher(task_dir, detail, fallback):
    """An image fetcher that answers from the detail record's own retained media (``payload.media``: url, path, sha256,
    written by the SerpApi adapter through the API channel) and falls back to the public download otherwise."""
    from common import resolve_retained_path
    rows = {row.get('url'): row for row in (detail.get('payload') or {}).get('media') or []
            if isinstance(row, dict) and row.get('url') and row.get('path') and row.get('sha256')}

    def fetch(url):
        row = rows.get(url)
        if row is not None:
            try:
                path = resolve_retained_path(Path(task_dir), row['path'], expected_sha256=row['sha256'])
                return path.read_bytes(), path.suffix.lower() or '.png', url
            except (OSError, ValueError):
                pass
        return fallback(url)
    return fetch


def retain_page(task_dir, candidate, number, *, role, fetch_page=None, fetch_image=_fetch_image,
                fetch_document=_fetch_document, drawings=None):
    """Retain the public Google Patents page of ``number`` for the candidate (core-focus tasks).

    ``role`` is 'public_page' (no exact API record: the page, its PDF and drawings stand in for the published text)
    or 'granted_publication' (the API record is an application publication whose application was granted: the
    granted claims are the ones in force). The page must name exactly this number. Returns a dict with the
    evidence id, parsed claims and page facts, or {'failure': reason}."""
    import core_focus
    from common import canonical_patent_number
    fetch_page = fetch_page or _fetch_page
    task_dir = Path(task_dir)
    number = canonical_patent_number(number)
    url = core_focus.page_url(number)
    folder = task_dir / 'raw' / 'core-dossier' / re.sub(r'[^A-Za-z0-9_-]', '_', number)
    known, digest = _registered(load_json(task_dir / 'evidence.json'), None, candidate['candidate_id'], source_url=url)
    if known:
        entry = next(row for row in load_json(task_dir / 'evidence.json')['collections']['sources']
                     if row.get('evidence_id') == known)
        body = Path(entry['payload']['path']).read_bytes()
        acquired = entry.get('collected_at') or now_iso()
    else:
        try:
            body, _ = fetch_page(url)
        except (OSError, ValueError) as exc:
            return {'failure': (type(exc).__name__ + ':' + str(exc))[:200], 'url': url}
        acquired = now_iso()
    text = body.decode('utf-8', 'replace')
    facts = core_focus.page_facts(text)
    if canonical_patent_number(facts.get('publication_number')) != number:
        return {'failure': 'PUBLIC_PAGE_IDENTITY_MISMATCH:' + str(facts.get('publication_number'))[:40], 'url': url}
    claims = core_focus.page_claims(text)
    if not known:
        digest = sha256_bytes(body)
        path = folder / 'google-patents-page.html'
        atomic_write_bytes(path, body)
        design = candidate.get('right_type') == 'design'
        _register(task_dir, {'publication_number': number, 'jurisdiction': candidate.get('jurisdiction') or 'US',
            'right_type': candidate.get('right_type'), 'candidate_id': candidate['candidate_id'],
            'kind': 'design_document' if design else 'patent_document', 'page_role': role,
            'authority_scope': 'published_document_only', 'path': str(path), 'sha256': digest, 'bytes': len(body),
            'source_url': url, 'claims_count': len(claims),
            'reasoning': ('公开专利检索页面（Google Patents）所载 %s 的公开文本与权利要求，按原公开地址取回留存；页面上的法律状态'
                          '是网站推算，不是官方现时记录。' % number) + (
                          '该号码是候选申请（同一申请）的授权公告文本。' if role == 'granted_publication' else '')})
        known, _ = _registered(load_json(task_dir / 'evidence.json'), digest, candidate['candidate_id'])
    result = {'evidence_id': known, 'number': number, 'url': url, 'claims': claims, 'facts': facts,
              'acquired_at': acquired, 'role': role}
    if role == 'public_page':
        # r7: the same application's granted publication, when the page lists one (read by search-guard tasks)
        result['granted_number'] = core_focus.page_granted_publication(text)
    if role == 'public_page' and known:
        # drawings only: the page already carries the full published text, a second copy (the PDF) would only be
        # read twice by every later reviewer
        payload = {'publication_number': number, 'images': facts.get('images') or []}
        result['files'] = retain_files(task_dir, candidate, {'payload': payload, 'evidence_id': known},
                                       fetch_image=fetch_image, fetch_document=fetch_document, drawings=drawings)
    return result


# ----- specialty events -----------------------------------------------------------------------------------------
def _scope(view_scope):
    return {key: view_scope[key] for key in ('candidate_id', 'scenario_id', 'jurisdiction', 'right_type')}


def _handoff(task, scope, annotation_id):
    from candidate_triage_stage import events as triage_events
    return next((row for row in reversed(triage_events(task)) if row.get('kind') == 'selected_handoff'
                 and all(row.get(key) == scope[key] for key in scope) and row.get('annotation_id') == annotation_id), None)


def product_evidence(task, evidence, indexed, scope):
    """(evidence id, image ids, description, statements) of the included product object of the scope's directions."""
    import product_scope as ps
    data = ps.scope(task) if ps.enabled(task) else {}
    directions = [row for row in data.get('directions', []) if row.get('scenario_id') == scope['scenario_id']
                  and row.get('right_type') == scope['right_type']]
    object_ids = {oid for row in directions for oid in row.get('object_ids', [])}
    objects = [row for row in data.get('objects', []) if row.get('object_id') in object_ids
               and row.get('scope_status', 'included') == 'included' and row.get('kind') == 'product']
    refs = [ref for row in objects for ref in row.get('source_refs', []) if ref in indexed]
    for name in ('browser', 'product'):
        if not refs:
            refs = [row.get('evidence_id') for row in (evidence.get('collections') or {}).get(name, [])
                    if row.get('evidence_id') in indexed][-1:]
    if not refs:
        return None
    images = list(dict.fromkeys(i for row in objects for i in (row.get('visual_evidence') or {}).get('image_ids', [])))
    fact_ids = {fid for row in directions for fid in row.get('fact_ids', [])}
    facts = [row for row in data.get('facts', []) if row.get('fact_id') in fact_ids]
    return {'evidence_id': refs[0], 'image_ids': images,
            'description': '；'.join(str(row.get('description')) for row in objects if row.get('description')),
            'statements': [(row.get('fact_id'), row.get('nature'), str(row.get('value') or '')[:160]) for row in facts]}


def _api_reading(payload):
    fields = [key for key in ('publication_number', 'title', 'application_number', 'priority_date', 'filing_date',
                              'publication_date', 'legal_status', 'status', 'worldwide_applications', 'legal_events',
                              'assignees', 'inventors') if payload.get(key) not in (None, '', [], {})]
    claims = payload.get('claims')
    if isinstance(claims, list) and claims:
        fields.append('claims[0-%d]' % (len(claims) - 1))
    return ['SerpApi candidate_detail payload: ' + '; '.join(fields)]


def _latest_event(payload):
    events = [row for row in payload.get('legal_events') or [] if isinstance(row, dict) and _day(row.get('date'))]
    if not events:
        return None
    row = max(events, key=lambda item: item['date'])
    return '%s %s %s' % (row['date'], row.get('code') or '', row.get('title') or '')


def _independent_claim_numbers(payload):
    from claims_triage_host import parse_claims
    return [row['number'] for row in parse_claims(payload.get('claims') or []) if row['independent']]


def _page_reading(page):
    return ['Google Patents public page of %s: publication number, title, claims[1-%d]%s' % (
        page['number'], len(page['claims']), '; page status "%s" (site-derived)' % page['facts']['legal_status']
        if page['facts'].get('legal_status') else '')]


def _page_payload(page):
    """The page in the shape the statements below read (no API status or owner fields)."""
    facts = page['facts']
    return {'publication_number': page['number'], 'title': facts.get('title'), 'claims': page['claims'],
            'country': 'US' if page['number'].startswith('US') else page['number'][:2]}


def uspto_grant(evidence, candidate_id):
    """The USPTO grant PDF of a US design as retained page by page (``pipeline_robust.retain_uspto_pages``), or None.

    r5d8 real run B0GLNPC6K8 (new task): the program retained the official grant PDF of both selected designs, but
    the dossier only knew the SerpApi record and the Google page. One design had neither (SerpApi "no record", Google
    404) and waited for an intake no step could write; the other had a record whose drawings Google refuses, so its
    protection stayed unknown and the view comparison never ran. The grant PDF is the office's own published
    document: its front page names the number, title and claim and every further page is a drawing sheet. It
    supports identity and protection; it says nothing about the current status or holder."""
    import pipeline_robust
    rows = []
    for entry in (evidence.get('collections') or {}).get('sources', []):
        payload = entry.get('payload') if isinstance(entry, dict) and isinstance(entry.get('payload'), dict) else {}
        derived = payload.get('derived_from') if isinstance(payload.get('derived_from'), dict) else {}
        if (payload.get('kind') == 'patent_drawing_image' and payload.get('candidate_id') == candidate_id
                and str(payload.get('source_url') or '').startswith(pipeline_robust.USPTO_PDF)
                and entry.get('evidence_id') and derived.get('page_number') and payload.get('publication_number')):
            rows.append((int(derived['page_number']), entry))
    if not rows:
        return None
    rows.sort(key=lambda row: row[0])
    first = rows[0][1]
    return {'number': str(first['payload']['publication_number']), 'url': first['payload']['source_url'],
            'evidence_refs': list(dict.fromkeys(entry['evidence_id'] for _, entry in rows)),
            'pages': [number for number, _ in rows], 'acquired_at': first.get('collected_at') or now_iso()}


def _grant_reading(grant):
    return ['USPTO grant PDF of %s (%s): pages %s - front page (number, title, dates, the claim) and the drawing '
            'sheets' % (grant['number'], grant['url'], ', '.join(map(str, grant['pages'])))]


def _grant_material(grant, alias, purposes, supported, today):
    return {'kind': 'material', 'alias': alias, 'document_id': grant['number'],
            'document_version': 'uspto-' + (_day(grant['acquired_at']) or today),
            'evidence_refs': list(grant['evidence_refs']), 'acquired_at': grant['acquired_at'],
            'source_form': 'original_document', 'purposes': purposes, 'supported_facts': supported,
            'reading_locations': _grant_reading(grant), 'status': 'sufficient_for_listed_purposes',
            'support_reasoning': 'USPTO 官方原始文件入口取回的授权 PDF，逐页原样留存：首页载号码、标题与外观设计权利要求，'
                                 '其余各页为授权附图；外观设计的保护内容以这些附图为准。授权文件不证明现时维持状态与现时权利人。'}


def _grant_batch(grant, alias):
    refs = list(grant['evidence_refs'])
    return {'kind': 'batch', 'batch_id': 'import:' + refs[0], 'received_evidence_refs': refs,
            'received_material_event_ids': [{'$event': alias}], 'processed_material_event_ids': [{'$event': alias}],
            'disposition_by_evidence_ref': {ref: 'USPTO 授权 PDF 的一页，已逐页读取并登记为专项材料。' for ref in refs},
            'disposition_reasoning': '逐来源登记阅读去向；不据此推断权属或侵权。'}


def _protection_supported(rows):
    return any(row.get('kind') == 'material' and row.get('status') == 'sufficient_for_listed_purposes'
               and 'protection' in row.get('supported_facts', []) for row in rows)


def grant_amendment(scope, intake, history, grant, *, today):
    """The grant PDF added to a design intake the program recorded before the PDF was retained (or in a run made
    before r5d8): its material, a supported protection fact that resolves the single-kind protection handoff gap,
    and its batch. The earlier unknown protection fact and its limitation stay in the history; the comparison then
    reads the newest protection material."""
    gaps = [gap for gap in intake.get('verification_gaps', []) if gap_kinds(gap) == ['protection']]
    fact = {'kind': 'fact', 'alias': 'f_protection', 'fact_id': 'F-protection-uspto', 'fact_kind': 'protection',
            'outcome': 'supported',
            'raw_statement': '授权附图 %d 页（USPTO 官方授权 PDF 原页 %s，含首页的号码、标题与外观设计权利要求）；保护内容以授权附图为准。' % (
                len(grant['pages']), '、'.join('P%02d' % n for n in grant['pages'])),
            'reasoning': '程序按 USPTO 官方授权文件登记；字段存在并已采信。',
            'document_version': 'uspto-' + (_day(grant['acquired_at']) or today), 'reading_locations': _grant_reading(grant),
            'evidence_refs': [grant['evidence_refs'][0]], 'material_event_ids': [{'$event': 'm_uspto'}],
            **({'resolves_handoff_gaps': gaps} if gaps else {})}
    events = [_grant_material(grant, 'm_uspto', ['protection'], ['protection'], today), fact, _grant_batch(grant, 'm_uspto')]
    return ({'scope': scope, 'reviewer': REVIEWER,
             'reason': 'USPTO 官方授权 PDF 已留存：补登其为保护内容材料；不比较、不评级。', 'events': events},
            {'supported_facts': ['protection'], 'amended': 'uspto_grant'})


def base_request(task, evidence, candidates, ledger, supplement, indexed, view_scope, detail, *, today=None,
                 granted=None, page=None, grant=None):
    """The program-authored specialty transaction for one scope, or (None, reason).

    ``detail`` is the exact API record; without one (core-focus tasks, record budget used up) ``page`` is the
    retained public page, recorded as an original published document that supports identity and protection only.
    ``granted`` is the retained granted publication of the record's application: its claims become the claims
    material the comparison reads. ``grant`` (r5d8, US designs) is the retained USPTO grant PDF (``uspto_grant``):
    without a record or page it is the record material (identity and protection); beside a record whose drawings
    could not be retained it supplies the protection the record cannot. A design the program already recorded
    without protection gets the grant PDF added to the same intake once it is retained (``grant_amendment``)."""
    import specialty_analysis as sa
    import trusted_api
    scope = _scope(view_scope)
    current = sa._current(task, evidence, candidates, ledger, supplement, tuple(scope.values()))
    handoff = _handoff(task, scope, current['annotation']['annotation_id'])
    if handoff is None:
        return None, 'selected_handoff_pending'
    prior = sa._intake(task, tuple(scope.values()))
    if prior and prior.get('selected_handoff_event_id') == handoff['event_id']:
        mine = [row for row in sa.events(task) if row.get('intake_event_id') == prior['event_id']]
        if any(row.get('reviewer') == REVIEWER for row in mine):
            if (grant and scope['right_type'] == 'design' and not _protection_supported(mine)
                    and all(row.get('reviewer') == REVIEWER for row in mine if row.get('kind') != 'intake')):
                return grant_amendment(scope, prior, mine, grant, today=today or _today())
            return None, 'already_recorded'
        elif any(row.get('kind') in {'material', 'fact'} for row in mine):
            return None, 'agent_specialty_present'
    if grant and not detail and not page:
        page = {'grant': grant}
    record_ref = (detail['evidence_id'] if detail else
                  grant['evidence_refs'][0] if page and page.get('grant') else (page or {}).get('evidence_id'))
    if record_ref is None:
        return None, 'no_record'
    if record_ref not in indexed:
        return None, 'detail_record_not_indexed'
    product = product_evidence(task, evidence, indexed, scope)
    if product is None:
        return None, 'product_evidence_missing'
    today = today or _today()
    if detail:
        payload = detail['payload']
        number = str(payload.get('publication_number') or '')
        acquired = detail.get('collected_at') or now_iso()
        version = 'api-' + (_day(payload.get('publication_date')) or _day(acquired) or 'record')
        draft = trusted_api.bind_material_candidate(task, {**scope, 'source_form': trusted_api.FORM,
            'document_id': number, 'evidence_refs': [detail['evidence_id']]}, candidates)
        supported = [fact for fact in API_FACTS if trusted_api.material_support(task, draft, indexed, fact, evidence=evidence)]
        if 'identity' not in supported:
            return None, 'detail_record_identity_not_accepted'
        form, purposes, locations = trusted_api.FORM, list(API_FACTS), _api_reading(payload)
        reason_api = '程序逐字段读取准确详情记录；只采信所列字段，权属字段未标注为现时权利人时保留未知。'
    elif page.get('grant'):
        from annotate_materiality import iter_candidates
        row = next((row for _, row in iter_candidates(candidates) if row.get('candidate_id') == scope['candidate_id']), {})
        number = grant['number']
        payload = {'publication_number': number, 'title': row.get('title') or '', 'claims': [], 'country': 'US'}
        acquired = grant['acquired_at']
        version = 'uspto-' + (_day(acquired) or today)
        supported = ['identity', 'protection']
        form, purposes, locations = 'original_document', list(API_FACTS), _grant_reading(grant)
        reason_api = _grant_material(grant, 'm_api', purposes, supported, today)['support_reasoning']
    else:
        if not page.get('claims'):
            return None, 'public_page_claims_missing'
        payload = _page_payload(page)
        number = page['number']
        acquired = page.get('acquired_at') or now_iso()
        version = 'page-' + (_day(acquired) or 'record')
        supported = ['identity', 'protection']
        # read for every fact purpose (each fact must name a material read for it); it supports two of them
        form, purposes, locations = 'original_document', list(API_FACTS), _page_reading(page)
        reason_api = ('程序读取公开专利检索页面所载的公开文本：号码、标题与全部权利要求；页面上的法律状态是网站推算，'
                      '不作为官方现时记录，状态、地域效力与权利人保留未知。')
    official = bool(page and page.get('grant'))
    # a record (or page) without retained drawings: the grant PDF supplies the design's protection beside it
    extra = grant if grant and not official and scope['right_type'] == 'design' and 'protection' not in supported else None
    if official:
        detail = {'evidence_id': grant['evidence_refs'][0], 'payload': payload, 'collected_at': acquired}
    detail = detail or {'evidence_id': page['evidence_id'], 'payload': payload, 'collected_at': acquired}
    events = []
    if not (prior and prior.get('selected_handoff_event_id') == handoff['event_id']):
        intake = {'kind': 'intake', 'alias': 'intake', 'selected_handoff_event_id': handoff['event_id'],
                  'assessment_date': today, 'assessment_date_basis': '程序专项登记当日（本地日期）'}
        if prior:
            intake.update(prior_intake_event_id=prior['event_id'],
                          new_round_reasoning='入选交接已更新，按当前交接重新登记专项材料与事实。')
        events.append(intake)
    events.append({'kind': 'material', 'alias': 'm_api', 'document_id': number, 'document_version': version,
        'evidence_refs': list(grant['evidence_refs']) if official else [detail['evidence_id']],
        'acquired_at': acquired, 'source_form': form,
        'purposes': purposes, 'supported_facts': supported, 'reading_locations': locations,
        'status': 'sufficient_for_listed_purposes', 'support_reasoning': reason_api})
    product_version = 'product-v%s' % task.get('product_change_version', 1)
    product_locations = ['images ' + ', '.join(product['image_ids'])] if product['image_ids'] else []
    product_locations.append('product_scope objects/facts of the %s direction' % scope['right_type'])
    events.append({'kind': 'material', 'alias': 'm_product',
        'document_id': str((task.get('product') or {}).get('actual_asin') or (task.get('product') or {}).get('requested_asin')
                           or (task.get('product') or {}).get('product_id') or 'product'),
        'document_version': product_version, 'evidence_refs': [product['evidence_id']],
        'acquired_at': next((row.get('collected_at') for row in (evidence.get('collections') or {}).get('browser', [])
                             if row.get('evidence_id') == product['evidence_id'] and row.get('collected_at')), acquired),
        'source_form': 'product_original', 'purposes': ['product', 'comparison'], 'supported_facts': ['product'],
        'reading_locations': product_locations, 'status': 'sufficient_for_listed_purposes',
        'support_reasoning': '复述已审产品范围的对象描述及页面事实性质；页面声明不作为已核实结构。'})
    # Combined handoff gaps are classified per fact kind; a single-kind gap is resolved by its supported fact.
    resolves, unresolved = {}, []
    for gap in handoff.get('verification_gaps', []):
        kinds = gap_kinds(gap)
        if not kinds:
            unresolved.append(gap)
            continue
        if len(kinds) > 1:
            events.append({'kind': 'handoff_classification', 'alias': 'class:' + gap, 'handoff_gap': gap,
                'fact_kinds': kinds, 'material_event_ids': [{'$event': 'm_api'}], 'evidence_refs': [detail['evidence_id']],
                'reading_locations': locations,
                'classification_reasoning': '该交接缺口包含%s，逐项按准确记录字段分别处理，不整体声称关闭。' % '、'.join(kinds)})
        for kind in kinds:
            resolves.setdefault(kind, []).append(gap)
    status_value = payload.get('legal_status') or payload.get('status')
    claims = payload.get('claims') or []
    independent = _independent_claim_numbers(payload)
    assignees = payload.get('assignees') or []
    inventors = [row.get('name') for row in payload.get('inventors') or [] if isinstance(row, dict) and row.get('name')]
    grant_note = ''
    if granted and granted.get('evidence_id'):
        grant_note = '同一申请已授权公告为 %s（准确记录 worldwide_applications／events 所列；授权文本已留存，比较以授权权利要求为准）。' % granted['number']
    statements = {
        'identity': '%s，%s；申请号 %s；公开/授权日 %s。%s' % (number, payload.get('title') or '', payload.get('application_number') or '未载',
                                                    payload.get('publication_date') or '未载', grant_note),
        'territory': '准确%s记录（country=%s）；legal_status=%s。' % (scope['jurisdiction'], payload.get('country') or '未载', status_value or '未载'),
        'status': 'legal_status=%s；最近法律事件：%s。记录取得日 %s。' % (status_value or '未载', _latest_event(payload) or '未载', _day(acquired) or today),
        'protection': '共 %d 项权利要求，独立权利要求 %s；文本取自准确详情记录 claims 字段。' % (len(claims), '、'.join(map(str, independent)) or '未识别'),
        'rights_holder': ('现时权利人字段：%s。' % assignees) if 'rights_holder' in supported else
            'assignees=%s，未标注为现时权利人；发明人 %s 不能等同现时权利主体或任何品牌的授权链。' % (assignees or '未载', '、'.join(inventors) or '未载'),
    }
    if form != trusted_api.FORM and not official:
        shown = page['facts'].get('legal_status') or page['facts'].get('application_status') or '未载'
        page_grant = ('同一申请已授权公告为 %s（公开页事件表所列；授权文本已留存，比较以授权权利要求为准）。' % granted['number']
                      if granted and granted.get('evidence_id') else '')
        statements.update(
            identity='%s，%s；公开专利检索页面所载公开文本（非官方现时记录）。%s' % (number, payload.get('title') or '', page_grant),
            territory='公开文本为%s文献；现时地域效力未经官方或可信记录核实。' % scope['jurisdiction'],
            status='页面显示的状态为“%s”（网站推算，不是官方现时状态记录），按未知处理。页面取得日 %s。' % (shown, _day(acquired) or today),
            rights_holder='公开页未提供可采信的现时权利人记录，保留未知。',
            protection='共 %d 项权利要求，独立权利要求 %s；文本取自留存公开页的权利要求段。' % (
                len(claims), '、'.join(map(str, independent)) or '未识别'))
    if official or extra:
        statements['protection'] = '授权附图 %d 页（USPTO 官方授权 PDF 原页 %s，含首页的号码、标题与外观设计权利要求）；保护内容以授权附图为准。' % (
            len(grant['pages']), '、'.join('P%02d' % n for n in grant['pages']))
    if official:
        statements.update(
            identity='%s，%s；USPTO 官方授权 PDF（原始文件入口 %s）。' % (number, payload.get('title') or '', grant['url']),
            territory='美国授权文件；现时地域效力未经官方状态记录核实。',
            status='授权文件不证明现时维持状态，按未知处理。文件取得日 %s。' % (_day(acquired) or today),
            rights_holder='授权文件所载的原始权利人不等于现时权利人；未取得现时权属记录，保留未知。')
    for kind in API_FACTS:
        own = bool(extra) and kind == 'protection'
        outcome = 'supported' if kind in supported or own else 'unknown'
        fact = {'kind': 'fact', 'alias': 'f_' + kind, 'fact_id': 'F-' + kind, 'fact_kind': kind, 'outcome': outcome,
                'raw_statement': statements[kind],
                'reasoning': ('程序按 USPTO 官方授权文件登记；' if official or own else
                              '程序按准确详情记录的对应字段登记；' if form == trusted_api.FORM else '程序按留存的公开文本登记；')
                             + ('字段存在并已采信。' if outcome == 'supported' else '字段缺失或未标注现时属性，保留未知。'),
                'document_version': version, 'reading_locations': locations,
                'evidence_refs': [detail['evidence_id']], 'material_event_ids': [{'$event': 'm_api'}]}
        if own:
            fact.update(document_version='uspto-' + (_day(grant['acquired_at']) or today),
                        reading_locations=_grant_reading(grant), evidence_refs=[grant['evidence_refs'][0]],
                        material_event_ids=[{'$event': 'm_uspto'}])
        if kind in {'territory', 'status'}:
            fact.update(right_identity=number, territory_basis='同一%s编号的准确详情记录及其状态字段，不外推其他国家。' % scope['jurisdiction'])
        if kind == 'status':
            fact['source_checked_date'] = _day(acquired) or today
        if kind == 'rights_holder' and scope['right_type'] == 'design':
            fact.update(holder_identity=str(assignees or '未载'),
                        assessment_applicability_reasoning='外观专利权利人只按准确记录的现时权利人字段采信。')
        if outcome == 'supported' and resolves.get(kind):
            fact['resolves_handoff_gaps'] = list(resolves[kind])
        if own:
            events.append(_grant_material(grant, 'm_uspto', ['protection'], ['protection'], today))
        events.append(fact)
    product_statement = (product['description'] or '所列产品') + (
        '；页面图片 ' + '、'.join(product['image_ids']) if product['image_ids'] else '') + ''.join(
        '；%s（%s）：%s' % (fid, nature, value) for fid, nature, value in product['statements'][:4])
    events.append({'kind': 'fact', 'alias': 'f_product', 'fact_id': 'F-product', 'fact_kind': 'product',
        'outcome': 'supported', 'raw_statement': product_statement[:900],
        'reasoning': '复述已审产品范围；页面声明性质原样保留，不推断不可见结构。',
        'document_version': product_version, 'reading_locations': product_locations,
        'evidence_refs': [product['evidence_id']], 'material_event_ids': [{'$event': 'm_product'}],
        **({'resolves_handoff_gaps': list(resolves['product'])} if resolves.get('product') else {})})
    if granted and granted.get('evidence_id') and granted.get('claims'):
        events.append({'kind': 'material', 'alias': 'm_grant', 'document_id': granted['number'],
            'document_version': 'grant-' + (_day(granted.get('acquired_at')) or today),
            'evidence_refs': [granted['evidence_id']], 'acquired_at': granted.get('acquired_at') or acquired,
            'source_form': 'original_document', 'purposes': ['protection'], 'supported_facts': ['protection'],
            'reading_locations': _page_reading(granted), 'status': 'sufficient_for_listed_purposes',
            'support_reasoning': '同一申请的授权公告文本（公开页）所载全部权利要求；元素比较以授权权利要求为准。'})
    # Accounting: every material in its own batch, every remaining candidate source as received evidence.
    events.append(_grant_batch(grant, 'm_api') if official else
                  _batch(detail['evidence_id'], 'm_api', '准确详情记录已逐字段读取并登记为专项材料。'
                         if form == trusted_api.FORM else '公开文本已读取并登记为专项材料。'))
    if extra:
        events.append(_grant_batch(grant, 'm_uspto'))
    if granted and granted.get('evidence_id') and granted.get('claims'):
        events.append(_batch(granted['evidence_id'], 'm_grant', '授权公告文本已读取并登记为专项材料。'))
    events.append(_batch(product['evidence_id'], 'm_product', '产品原件已按已审范围读取并登记为专项材料。'))
    from annotate_materiality import iter_candidates
    candidate = next(row for _, row in iter_candidates(candidates) if row.get('candidate_id') == scope['candidate_id'])
    refs = [ref for ref in candidate.get('evidence_refs', []) if isinstance(ref, str)]
    refs += [row.get('evidence_id') for row in candidate.get('sources', []) if isinstance(row, dict) and row.get('evidence_id')]
    unaccounted = []
    for ref in dict.fromkeys(refs):
        if ref in {detail['evidence_id'], product['evidence_id']} or (
                (official or extra) and ref in grant['evidence_refs']):
            continue
        if ref not in indexed:
            unaccounted.append(ref)
            continue
        events.append(_batch(ref, None, '候选来源记录已核对；其身份与内容由同一准确详情记录承接，未作为新增权利。'))
    request = {'scope': scope, 'reviewer': REVIEWER,
               'reason': '程序按准确详情记录与已审产品范围登记专项材料、事实与来源去向；不比较、不评级。',
               'events': events}
    return request, {'supported_facts': supported, 'unresolved_handoff_gaps': unresolved,
                     'unaccounted_candidate_refs': unaccounted}


def record_gap_planned(task_dir, task, evidence, candidates, ledger, supplement, plan, scope):
    """True when the planner has given up on the exact record of this scope (API_RECORD_FACT_GAP: every bounded record
    operation tried or unavailable). Only then may the dossier stand on the discovery card alone.

    r5d8: this used to ask ``api_record_gap_entry``, which also wants the scope's intake and facts - the very events
    the card dossier is about to write - so it was never true for a scope without an intake (B0GLNPC6K8: the design
    SerpApi had no record of waited at checkpoint 2). The planner itself is asked, as that function does first: one
    saved API_RECORD_FACT_GAP row for the scope that the current planner reproduces."""
    from copy import deepcopy
    import specialty_analysis as sa
    from annotate_materiality import iter_candidates
    from candidate_api_actions import append
    keys = ('candidate_id', 'scenario_id', 'jurisdiction', 'right_type')
    matches = [row for row in plan.get('candidate_action_gaps', []) if row.get('code') == 'API_RECORD_FACT_GAP'
               and all(row.get(key) == scope.get(key) for key in keys)]
    if len(matches) != 1 or not matches[0].get('required_facts'):
        return False
    caps = _capabilities(task, evidence, plan, task_dir)
    candidate = next((row for _, row in iter_candidates(candidates) if row.get('candidate_id') == scope['candidate_id']), None)
    if caps is None or candidate is None:
        return False
    try:
        current = sa._current(task, evidence, candidates, ledger, supplement, tuple(scope[key] for key in keys))
        requirements = [row for row in task.get('coverage_requirements', [])
                        if row.get('jurisdiction') == scope['jurisdiction'] and row.get('right_type') == scope['right_type']]
        regenerated = append(task, evidence, deepcopy(plan.get('queries', {})), candidate,
                             {**current, **{key: scope[key] for key in keys}}, requirements, capabilities=caps, plan=plan,
                             task_dir=task_dir)
    except (ValueError, KeyError, TypeError):
        return False
    return regenerated == matches


def fallback_request(task, evidence, candidates, ledger, supplement, indexed, view_scope, *, today=None):
    """r5d4 tasks: the specialty transaction of a selected scope whose exact record and public page are both
    unavailable (the planner already lists API_RECORD_FACT_GAP). The material is the candidate's own discovery card,
    read but not sufficient for any fact: every record fact stays unknown and the planned gap limits it, so the run
    goes on with a disclosed limitation instead of an intake no program step could write (B0FSJBDTF2)."""
    import specialty_analysis as sa
    from annotate_materiality import iter_candidates
    scope = _scope(view_scope)
    current = sa._current(task, evidence, candidates, ledger, supplement, tuple(scope.values()))
    handoff = _handoff(task, scope, current['annotation']['annotation_id'])
    if handoff is None:
        return None, 'selected_handoff_pending'
    prior = sa._intake(task, tuple(scope.values()))
    if prior and prior.get('selected_handoff_event_id') == handoff['event_id']:
        mine = [row for row in sa.events(task) if row.get('intake_event_id') == prior['event_id']]
        if any(row.get('reviewer') == REVIEWER for row in mine):
            return None, 'already_recorded'
        if any(row.get('kind') in {'material', 'fact'} for row in mine):
            return None, 'agent_specialty_present'
    candidate = next(row for _, row in iter_candidates(candidates) if row.get('candidate_id') == scope['candidate_id'])
    refs = [ref for ref in candidate.get('evidence_refs', []) if isinstance(ref, str)]
    refs += [row.get('evidence_id') for row in candidate.get('sources', []) if isinstance(row, dict) and row.get('evidence_id')]
    refs = [ref for ref in dict.fromkeys(refs) if ref in indexed]
    if not refs:
        return None, 'card_evidence_missing'
    product = product_evidence(task, evidence, indexed, scope)
    if product is None:
        return None, 'product_evidence_missing'
    today = today or _today()
    number = str(candidate.get('publication_number') or candidate.get('registration_number') or scope['candidate_id'])
    acquired = next((indexed[ref].get('collected_at') for ref in refs if indexed[ref].get('collected_at')), None) or now_iso()
    version = 'card-' + (_day(acquired) or today)
    locations = ['discovery card of %s: publication number, title and dates as returned by the search source' % number]
    events = []
    if not (prior and prior.get('selected_handoff_event_id') == handoff['event_id']):
        intake = {'kind': 'intake', 'alias': 'intake', 'selected_handoff_event_id': handoff['event_id'],
                  'assessment_date': today, 'assessment_date_basis': '程序专项登记当日（本地日期）'}
        if prior:
            intake.update(prior_intake_event_id=prior['event_id'],
                          new_round_reasoning='入选交接已更新，按当前交接重新登记专项材料与事实。')
        events.append(intake)
    events.append({'kind': 'material', 'alias': 'm_card', 'document_id': number, 'document_version': version,
        'evidence_refs': refs, 'acquired_at': acquired, 'source_form': 'other', 'purposes': list(API_FACTS),
        'reading_locations': locations, 'status': 'read',
        'support_reasoning': '只有检索来源返回的候选卡片；准确记录与公开文本均未取得，卡片不足以支持任何权利事实。'})
    product_version = 'product-v%s' % task.get('product_change_version', 1)
    product_locations = ['images ' + ', '.join(product['image_ids'])] if product['image_ids'] else []
    product_locations.append('product_scope objects/facts of the %s direction' % scope['right_type'])
    events.append({'kind': 'material', 'alias': 'm_product',
        'document_id': str((task.get('product') or {}).get('actual_asin') or (task.get('product') or {}).get('requested_asin')
                           or (task.get('product') or {}).get('product_id') or 'product'),
        'document_version': product_version, 'evidence_refs': [product['evidence_id']],
        'acquired_at': next((row.get('collected_at') for row in (evidence.get('collections') or {}).get('browser', [])
                             if row.get('evidence_id') == product['evidence_id'] and row.get('collected_at')), acquired),
        'source_form': 'product_original', 'purposes': ['product', 'comparison'], 'supported_facts': ['product'],
        'reading_locations': product_locations, 'status': 'sufficient_for_listed_purposes',
        'support_reasoning': '复述已审产品范围的对象描述及页面事实性质；页面声明不作为已核实结构。'})
    title = str(candidate.get('title') or '标题未载')
    statements = {'identity': '%s，%s；仅有检索卡片，准确记录与公开文本均未取得。' % (number, title),
                  'territory': '仅有检索卡片所列号码；现时地域效力未经记录核实。',
                  'status': '准确记录未取得，现行状态未知。',
                  'protection': '保护内容（权利要求或授权附图）未取得。',
                  'rights_holder': '现时权利人未取得记录，保留未知。'}
    for kind in API_FACTS:
        fact = {'kind': 'fact', 'alias': 'f_' + kind, 'fact_id': 'F-' + kind, 'fact_kind': kind, 'outcome': 'unknown',
                'raw_statement': statements[kind],
                'reasoning': '程序按检索卡片登记；卡片不足以支持该事实，保留未知并按计划登记的记录缺口限制。',
                'document_version': version, 'reading_locations': locations, 'evidence_refs': refs,
                'material_event_ids': [{'$event': 'm_card'}]}
        if kind in {'territory', 'status'}:
            fact.update(right_identity=number, territory_basis='检索卡片所列%s编号；不外推其他国家。' % scope['jurisdiction'])
        if kind == 'status':
            fact['source_checked_date'] = _day(acquired) or today
        if kind == 'rights_holder' and scope['right_type'] == 'design':
            fact.update(holder_identity='未载', assessment_applicability_reasoning='外观专利权利人只按准确记录的现时权利人字段采信。')
        events.append(fact)
    product_statement = (product['description'] or '所列产品') + (
        '；页面图片 ' + '、'.join(product['image_ids']) if product['image_ids'] else '') + ''.join(
        '；%s（%s）：%s' % (fid, nature, value) for fid, nature, value in product['statements'][:4])
    events.append({'kind': 'fact', 'alias': 'f_product', 'fact_id': 'F-product', 'fact_kind': 'product',
        'outcome': 'supported', 'raw_statement': product_statement[:900],
        'reasoning': '复述已审产品范围；页面声明性质原样保留，不推断不可见结构。',
        'document_version': product_version, 'reading_locations': product_locations,
        'evidence_refs': [product['evidence_id']], 'material_event_ids': [{'$event': 'm_product'}]})
    for ref in refs:
        events.append(_batch(ref, 'm_card', '候选检索卡片已读取并登记为专项材料；不足以支持权利事实。'))
    events.append(_batch(product['evidence_id'], 'm_product', '产品原件已按已审范围读取并登记为专项材料。'))
    request = {'scope': scope, 'reviewer': REVIEWER,
               'reason': '准确记录与公开文本均未取得；程序按检索卡片登记专项材料，记录事实保持未知；不比较、不评级。',
               'events': events}
    return request, {'supported_facts': [], 'fallback': 'discovery_card', 'card_refs': refs}


def _batch(ref, material_alias, reason):
    materials = [{'$event': material_alias}] if material_alias else []
    return {'kind': 'batch', 'batch_id': 'import:' + ref, 'received_evidence_refs': [ref],
            'received_material_event_ids': materials, 'processed_material_event_ids': list(materials),
            'disposition_by_evidence_ref': {ref: reason}, 'disposition_reasoning': '逐来源登记阅读去向；不据此推断权属或侵权。'}


def _capabilities(task, evidence, plan, task_dir):
    from necessary_completion import capability_map
    from runtime_v24 import resolved_capabilities
    path = Path(task_dir) / 'source-capabilities.json'
    if not path.is_file():
        return None
    caps = capability_map(task, load_json(path))
    browser = Path(task_dir) / 'browser-execution-status.json'
    return resolved_capabilities(task, evidence, plan, caps, task_dir,
                                 browser_status=load_json(browser) if browser.is_file() else None)


def limitation_request(task_dir, task, evidence, candidates, ledger, supplement, plan, scope, detail, *, card=False,
                       official=False):
    """Gap + limited follow-up for the record facts the planner lists as API_RECORD_FACT_GAP, or (None, reason)."""
    import specialty_analysis as sa
    from necessary_completion import api_record_gap_entry
    key = tuple(scope.values())
    intake = sa._intake(task, key)
    if intake is None:
        return None, 'intake_missing'
    history = [row for row in sa.events(task) if sa._scope(row) == key and row.get('intake_event_id') == intake['event_id']]
    proofs = [row['source_plan_gap_proof'] for row in history if row.get('kind') == 'gap' and row.get('source_plan_gap_proof')]
    import pipeline_robust
    if proofs and not pipeline_robust.enabled(task):
        return None, 'already_recorded'
    caps = _capabilities(task, evidence, plan, task_dir)
    if caps is None:
        return None, 'capabilities_missing'
    source = api_record_gap_entry(task, evidence, candidates, ledger, plan, caps, dict(scope),
                                  supplement=supplement, require_review=False, task_dir=task_dir)
    if source is None:
        return None, 'already_recorded' if proofs else 'no_planned_record_fact_gap'
    # r5d8: a limitation recorded before the grant PDF amended the intake binds facts and materials that changed;
    # only a limitation whose proof still matches stands, otherwise the remaining unknown facts are limited again
    if any(sa._source_gap_proof_matches(task, source['delivery_limit'], proof) for proof in proofs):
        return None, 'already_recorded'
    aliases = {'current_status': 'status', 'protection_content': 'protection', 'representative_figures': 'protection'}
    needed = [aliases.get(fact, fact) for fact in source.get('required_facts', [])]
    latest = {}
    for row in history:
        if row.get('kind') == 'fact':
            latest[row['fact_kind']] = row
    import core_focus
    if core_focus.enabled(task):
        # A retained public text supports identity/protection itself; only the facts left unknown are limited.
        needed = list(dict.fromkeys(kind for kind in needed if (latest.get(kind) or {}).get('outcome') != 'supported'))
        if not needed:
            return None, 'no_unknown_fact'
    classifications = {}
    for row in history:
        if row.get('kind') == 'handoff_classification':
            classifications[row['handoff_gap']] = row
    # The ledger raises one blocker per (handoff gap, fact kind) when a classification maps a gap to several facts,
    # while one gap event may bind each handoff gap only once (bindings are keyed by reason and gap). The first gap
    # event carries every fact binding and the first facet of each handoff gap; each further facet gets its own
    # gap event over the same planned record-field gap.
    groups = [[]]
    for kind in needed:
        fact = latest.get(kind)
        if fact is None or fact.get('outcome') != 'unknown':
            return None, 'fact_not_unknown:' + kind
        groups[0].append({'reason': 'SPECIALTY_FACT_REQUIRED', 'fact_kind': kind, 'basis_event_id': fact['event_id'],
                          'reasoning': '准确记录未提供该字段的现时值。'})
        for gap, row in classifications.items():
            if kind not in row.get('fact_kinds', []):
                continue
            binding = {'reason': 'SPECIALTY_HANDOFF_GAP_OPEN', 'handoff_gap': gap, 'fact_kind': kind,
                       'basis_event_id': fact['event_id'], 'handoff_classification_event_id': row['event_id'],
                       'handoff_classification_sha256': sha256_json(row),
                       'reasoning': '交接缺口中该项仍未知，其余各项已按记录分别处理。'}
            target = next((group for group in groups if not any(b.get('handoff_gap') == gap for b in group)), None)
            if target is None:
                target = []
                groups.append(target)
            target.append(binding)
    label = '、'.join(needed)
    base_id = 'API-FIELD-' + scope['candidate_id'][-10:] + '-' + '-'.join(sorted(needed))
    events = []
    unavailable = None
    import pipeline_robust
    if pipeline_robust.enabled(task) and 'protection' in needed and not any(
            row.get('kind') == 'material' and row.get('status') == 'sufficient_for_listed_purposes'
            and 'protection' in row.get('purposes', []) for row in history):
        # r5d4: no claims or drawings at all - the comparison inventory cannot be built and is limited with the gap
        required = [fact for fact in source.get('required_facts', []) if fact in {'protection_content', 'representative_figures'}]
        if required:
            unavailable = {'required_facts': required, 'unit_ids': [],
                           'reasoning': '准确记录、公开文本与附图均未取得，无法建立权利要求或视图清单，比较保持未完成。',
                           'readable_parts_review': '已读材料只有检索卡片（号码、标题、日期），不含可比较的保护内容。'}
    for index, bindings in enumerate(groups):
        alias = 'g%d' % index
        gap_id = base_id if index == 0 else '%s-%d' % (base_id, index + 1)
        facet = label if index == 0 else '、'.join(sorted({b['fact_kind'] for b in bindings}))
        events += [{'kind': 'gap', 'alias': alias, 'gap_id': gap_id, 'question': '准确记录未给出的%s是什么？' % facet,
            'affected_judgment': '%s 及交接缺口的相应部分' % facet, 'action_kind': 'verify_known_right',
            'minimum_action': '读取已留存的准确记录及可用的受支持路线', 'completion_condition': '取得准确现时记录或保留有记录的字段限制',
            'existing_material_check': ('只有检索卡片；准确记录与公开文本均未取得。' if card else
                                        '准确记录未取得；已读 USPTO 官方授权 PDF，授权文件不载现时状态与现时权利人。'
                                        if official else '准确详情记录已逐字段读取；该字段缺失或未标注现时属性。'),
            'next_value': '准确的现时权属/状态记录可解决该事实', 'evidence_refs': [detail['evidence_id']],
            'source_plan_gap_sha256': source['delivery_limit']['planning_gap_sha256'],
            'source_capabilities_sha256': source['delivery_limit']['capabilities_sha256'], 'obligation_bindings': bindings,
            **({'unavailable_comparison': unavailable} if unavailable and index == 0 else {})},
            {'kind': 'followup', 'gap_id': gap_id, 'gap_event_id': {'$event': alias}, 'outcome': 'limited',
             'result_review': '准确记录未给出该字段的现时值。', 'remaining_impact': '%s保持未知；其余已采信事实不受影响。' % facet,
             'next_action_or_dependency': '取得准确的现时转让/权属记录或恢复可提供该字段的路线后重开',
             'limit_evidence': ('准确记录与公开文本均未取得；计划已登记 API_RECORD_FACT_GAP。' if card else
                                '准确记录未取得，授权文件不载现时值；计划已登记 API_RECORD_FACT_GAP。' if official else
                                '已留存的准确详情记录未给出现时值；计划已登记 API_RECORD_FACT_GAP。'),
             'limit_kind': 'evidence_not_obtainable_within_scope',
             'restore_condition': '取得准确现时权属/状态记录，或可提供该字段的来源能力', 'evidence_refs': [detail['evidence_id']]}]
    # r5d8: the superseded limitation is closed by the facts recorded after it (the grant PDF's protection); what it
    # still left unknown is carried by the new limitation above
    for gap in (row for row in history if row.get('kind') == 'gap' and row.get('source_plan_gap_proof')):
        follow = next((row for row in reversed(history) if row.get('kind') == 'followup'
                       and row.get('gap_event_id') == gap['event_id']), {})
        later = history[history.index(gap) + 1:]
        settled = [row for row in later if row.get('kind') == 'fact' and row.get('outcome') == 'supported'
                   and row.get('fact_kind') in {b.get('fact_kind') for b in gap.get('obligation_bindings', [])}]
        if follow.get('outcome') != 'limited' or not settled:
            continue
        events.append({'kind': 'followup', 'gap_id': gap['gap_id'], 'gap_event_id': gap['event_id'], 'outcome': 'resolved',
                       'resolved_event_ids': [row['event_id'] for row in settled],
                       'evidence_refs': list(dict.fromkeys(ref for row in settled for ref in row.get('evidence_refs', []))),
                       'result_review': '此后登记的%s已由新取得的材料支持；其余仍未知的事实改由新的记录字段限制承接。'
                                        % '、'.join(sorted({row['fact_kind'] for row in settled})),
                       'remaining_impact': '%s保持未知，见新的限制。' % label})
    return {'scope': scope, 'reviewer': REVIEWER, 'reason': '按计划登记的记录字段缺口保留有记录的限制；不推断该事实。',
            'events': events}, None


def review_detail_record(task_dir, detail):
    """Register the whole-record reading of the exact detail run this dossier parses (once per run).

    The program reads every field it then uses: publication number, title, abstract, legal status and events,
    assignees and inventors, and the full claim text (independent claims go to the comparison host element by
    element). Image links stay links; the drawings themselves are retained separately. The required reading
    units and limitations come from the recorder itself, never from here."""
    from source_result_processing import append_record_content_review, _retained_run, _whole_record_reading
    task_dir = Path(task_dir)
    evidence = load_json(task_dir / 'evidence.json')
    run_id = detail.get('source_run_id')
    if any(row.get('source_run_id') == run_id for row in evidence.get('record_content_reviews', [])):
        return 'present'
    runs = [row for row in evidence.get('source_runs', []) if row.get('run_id') == run_id]
    if len(runs) != 1:
        return 'run_not_found'
    _, body = _retained_run(task_dir, runs[0], evidence)
    units, _ = _whole_record_reading(runs[0], evidence, body)
    append_record_content_review(task_dir, run_id, {'reading_units': units, 'reviewer': 'program:core_dossier',
        'reason': '程序逐字段读取完整详情记录：公开号、标题、摘要、法律状态与事件、受让人与发明人、全部权利要求文本'
                  '（独立项交比较宿主逐要素比对）；附图链接只作为链接，附图原件另行留存。'})
    return 'recorded'


def read_same_document_records(task_dir):
    """Register the reading of each exact detail record whose document the program has already read (r5d18).

    Run B0H16FDSD8: EPO's USD1035381S and Google's USD1035381S1 stayed two candidates, each with its own detail read;
    ``detail_entry`` takes the newest record of the number for both, so the older record was never registered as read
    and stopped the run at checkpoint 2 (SOURCE_RESULTS_PENDING_PROCESSING). Such a record names the same document as
    a record already read here; it is read the same way. A record whose document nobody has read stays for the Agent.
    Returns (registered run ids, [{run_id, reason}] left)."""
    from source_result_processing import append_record_content_review, _retained_run, _whole_record_reading
    task_dir = Path(task_dir)
    evidence = load_json(task_dir / 'evidence.json')
    read = {row.get('source_run_id') for row in evidence.get('record_content_reviews', []) if isinstance(row, dict)}
    numbers = {}
    for group in (evidence.get('collections') or {}).values():
        for entry in group if isinstance(group, list) else []:
            payload = entry.get('payload') if isinstance(entry, dict) else None
            if (isinstance(payload, dict) and entry.get('provider') == 'serpapi_google_patents'
                    and entry.get('operation') == 'candidate_detail' and entry.get('source_run_id')):
                numbers.setdefault(entry['source_run_id'], _identifier(payload.get('publication_number')))
    first_read = {}
    for run_id, number in numbers.items():
        if run_id in read and number:
            first_read.setdefault(number, run_id)
    done, left = [], []
    for run in evidence.get('source_runs', []):
        run_id = run.get('run_id') if isinstance(run, dict) else None
        twin = first_read.get(numbers.get(run_id)) if run_id and numbers.get(run_id) else None
        if (not twin or run_id in read or run.get('provider') != 'serpapi_google_patents'
                or run.get('operation') != 'candidate_detail' or run.get('status') != 'success'):
            continue
        try:
            current = load_json(task_dir / 'evidence.json')
            _, body = _retained_run(task_dir, run, current)
            units, _ = _whole_record_reading(run, current, body)
            append_record_content_review(task_dir, run_id, {'reading_units': units, 'reviewer': REVIEWER,
                'reason': '与已读取的详情记录 %s 是同一文件（%s）；程序同样逐字段读取本记录：公开号、标题、摘要、'
                          '法律状态与事件、受让人与发明人、全部权利要求文本；附图链接只作为链接。' % (twin, numbers[run_id])})
            done.append(run_id)
        except (ValueError, KeyError, OSError, TypeError) as exc:
            left.append({'run_id': run_id, 'reason': str(exc)[:200]})
    return done, left


def run(task_dir, candidate_ids=None, *, download=True, fetch_image=_fetch_image, fetch_document=_fetch_document, today=None,
        fetch_page=None):
    import core_focus
    import specialty_analysis as sa
    from annotate_materiality import iter_candidates
    task_dir = Path(task_dir)
    task = load_json(task_dir / 'task.json')
    summary = {'schema': 'IPR-CORE-DOSSIER/1.0', 'at': now_iso(), 'candidates': []}
    if not enabled(task) or not sa.enabled(task):
        summary['status'] = 'not_applicable'
        return summary
    context = sa._context(task_dir)
    task, evidence, candidates, ledger, supplement, indexed = context
    focus = core_focus.enabled(task)
    import pipeline_robust
    robust = pipeline_robust.enabled(task)
    plan = load_json(task_dir / 'search-plan.json')
    view = sa.project(task, evidence, candidates, ledger, supplement=supplement, plan=plan, task_dir=task_dir)
    by_id = {row.get('candidate_id'): row for _, row in iter_candidates(candidates)}
    for view_scope in view.get('scopes', []):
        if view_scope['right_type'] not in RIGHTS or (candidate_ids and view_scope['candidate_id'] not in candidate_ids):
            continue
        scope = _scope(view_scope)
        item = {**scope}
        candidate = by_id.get(scope['candidate_id'], {})
        detail = detail_entry(load_json(task_dir / 'evidence.json'), candidate)
        granted = page = None
        card = False
        if robust and scope['right_type'] == 'design':
            import precision
            if precision.enabled(task):
                pipeline_robust.complete_uspto_pages(task_dir, scope['candidate_id'])
        # r5d8: the USPTO grant PDF a robust run retained for a US design (pipeline_robust.retain_design_pictures)
        grant = uspto_grant(load_json(task_dir / 'evidence.json'), scope['candidate_id']) \
            if robust and scope['right_type'] == 'design' else None
        if grant:
            item['uspto_grant'] = {'number': grant['number'], 'pages': len(grant['pages'])}
        if detail is None:
            if focus and download and candidate.get('publication_number'):
                # core-focus: no exact record (budget used up) -> the public page's published text and drawings
                page = retain_page(task_dir, candidate, candidate['publication_number'], role='public_page',
                                   fetch_page=fetch_page, fetch_image=fetch_image, fetch_document=fetch_document)
                item['public_page'] = {key: page.get(key) for key in ('evidence_id', 'url', 'failure', 'files') if page.get(key)}
                number = page.get('granted_number') if not page.get('failure') else None
                if number and __import__('search_guard').enabled(task):
                    # r7 (run B0GFNWR8FW): an application granted under another number is compared on the granted
                    # claims, as when the API record names the grant
                    granted = retain_page(task_dir, candidate, number, role='granted_publication', fetch_page=fetch_page)
                    item['granted'] = {key: granted.get(key) for key in ('number', 'evidence_id', 'url', 'failure')
                                       if granted.get(key)}
                    item['granted'].setdefault('number', number)
            # r5d12 (B0GLNPC6K8): a retained page whose claims cannot be read is no record material either; it used to
            # leave the scope with no registration at all ("public_page_claims_missing") and stop checkpoint 2
            if page is None or page.get('failure') or not page.get('evidence_id') or (robust and not page.get('claims')):
                if page is not None and page.get('evidence_id') and not page.get('claims'):
                    item['public_page']['claims'] = 'unreadable'
                page = None
                # r5d4: once the planner has given up on the exact record, the dossier stands on the discovery card
                # and the record facts stay limited; before that, the scope waits for its record as before
                if grant is None and not (robust and record_gap_planned(
                        task_dir, task, evidence, candidates, ledger, supplement, load_json(task_dir / 'search-plan.json'),
                        scope)):
                    item['status'] = 'no_detail_record'
                    summary['candidates'].append(item)
                    continue
                # r5d8: the official grant PDF, when retained, is the record material (identity and protection)
                card = grant is None
        else:
            item['detail_evidence_id'] = detail['evidence_id']
            try:
                item['record_review'] = review_detail_record(task_dir, detail)
            except (ValueError, KeyError, OSError, TypeError) as exc:
                item['record_review'] = 'left_for_agent:' + str(exc)[:160]
            if download:
                # r5d4: the drawings the SerpApi adapter already retained through the API channel are reused, not
                # fetched again through the public-address channel (a local fake-IP proxy refused them there)
                fetcher = retained_media_fetcher(task_dir, detail, fetch_image) if robust else fetch_image
                item['files'] = retain_files(task_dir, candidate, detail, fetch_image=fetcher, fetch_document=fetch_document)
                number = core_focus.granted_publication(detail['payload']) if focus else None
                if number:
                    granted = retain_page(task_dir, candidate, number, role='granted_publication', fetch_page=fetch_page)
                    item['granted'] = {key: granted.get(key) for key in ('number', 'evidence_id', 'url', 'failure')
                                       if granted.get(key)}
                    item['granted'].setdefault('number', number)
        try:
            task, evidence, candidates, ledger, supplement, indexed = sa._context(task_dir)
            if card:
                request, info = fallback_request(task, evidence, candidates, ledger, supplement, indexed, view_scope,
                                                 today=today)
            else:
                request, info = base_request(task, evidence, candidates, ledger, supplement, indexed, view_scope, detail,
                                             today=today, granted=granted if granted and not granted.get('failure') else None,
                                             page=page, grant=grant)
            if request is None:
                item['base'] = info
            else:
                result = sa.record(task_dir, request)
                item['base'] = 'recorded'
                item.update(info)
                item['events'] = len(result.get('events', []))
            task, evidence, candidates, ledger, supplement, indexed = sa._context(task_dir)
            limit, reason = limitation_request(task_dir, task, evidence, candidates, ledger, supplement,
                                               load_json(task_dir / 'search-plan.json'), scope,
                                               detail or {'evidence_id': page['evidence_id'] if page else
                                                          grant['evidence_refs'][0] if grant and not card else
                                                          (info or {}).get('card_refs', [None])[0]}, card=card,
                                               official=bool(grant and not detail and not page and not card))
            if limit is None:
                item['limitation'] = reason
            else:
                sa.record(task_dir, limit)
                item['limitation'] = 'recorded'
            item['status'] = 'done'
        except (ValueError, KeyError, OSError, TypeError) as exc:
            item['status'] = 'left_for_agent'
            item['reason'] = str(exc)[:300]
        summary['candidates'].append(item)
    # r5d18, also for r5d17 tasks (their twin records stopped checkpoint 2 and are continued under r5d18)
    if pipeline_robust.speed_enabled(load_json(task_dir / 'task.json')):
        done, left = read_same_document_records(task_dir)
        if done or left:
            summary['same_document_readings'] = {'recorded': done, 'left_for_agent': left}
    summary['status'] = 'done'
    atomic_write_json(task_dir / OUTPUT, summary)
    return summary


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--task-dir', type=Path, required=True)
    parser.add_argument('--candidate-id', action='append', dest='candidate_ids')
    parser.add_argument('--no-download', action='store_true', help='Record the specialty events only; fetch no files')
    args = parser.parse_args(argv)
    from provider_utils import evidence_lock  # noqa: F401  (recorders take the lock themselves)
    summary = run(args.task_dir.resolve(), args.candidate_ids, download=not args.no_download)
    print(json.dumps(summary, ensure_ascii=False))
    return 0 if summary.get('status') in {'done', 'not_applicable'} else 1


if __name__ == '__main__':
    raise SystemExit(main())
