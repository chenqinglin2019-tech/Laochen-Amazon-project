#!/usr/bin/env python3
"""Fewer stops and smaller final-review packets (new tasks with ``review_focus_revision``, r5d3).

r5d2 real run (B07HQL3SPZ-US-r5d2-20261012-01, 57 min, no report) stopped three times where a program can act:

* three public web cards (a helmet chinstrap, an Indian court judgment, a USPTO PTAB petition) carried only a title
  and a snippet; the text judgment asked the *user* to supply the pages and checkpoint 2 waited until the Agent
  opened them by hand. Here the program reads the card's own public address first (same public-address rules as
  every other retained file), registers the page as a retained public source of that candidate and gives the
  judgment a deterministic excerpt. A card whose page cannot be read and whose only open question is one the user
  cannot answer is closed the way the visual host already closes such public cards (missing facts stay on record
  as reopen conditions);
* the final-review packets carried a 297k-character judgment of a not_selected card in every module and the full
  comparison text of 96 not_selected triage annotations (each repeating the product description): the review
  packet diet now stubs both (decision, reason and the hash of the full record; the frozen input is unchanged);
* the chain summary had to copy three 64-character module digests and dropped two characters of one. The program
  binds the summary to the exact module records it was given; the model no longer copies hashes.

Nothing here grades a risk, relaxes a validator or changes the report.
"""
from __future__ import annotations

import re
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from common import atomic_write_bytes, atomic_write_json, load_json, sha256_bytes, sha256_json

REVISION = 'review-focus-v1'
CARD_PAGE_ROLE = 'card_page'
PAGE_DIR = ('raw', 'card-pages')
FAILURES = 'failures.json'
MAX_CARD_PAGES = 12          # pages read per text-triage invocation
PAGE_TIMEOUT = 20
PAGE_MAX_BYTES = 6 * 1024 * 1024
EXCERPT_LIMIT = 6000         # characters the judgment sees
HEAD_CHARS = 1500
LINE_CHARS = 400
MIN_EXCERPT_FOR_EXCLUSION = 200
IP_WORDS = re.compile(r'patent|trade\s?mark|trade dress|copyright|design|infring|lawsuit|litigation|plaintiff|'
                      r'defendant|court|petition|claim|registration|registered|takedown|counterfeit|\bv\.|\bvs\.?(?=\s)|'
                      r'专利|商标|版权|侵权|诉讼', re.I)


def enabled(task) -> bool:
    return isinstance(task, dict) and task.get('review_focus_revision') == REVISION


# ----- public web-card pages ------------------------------------------------------------------------------------
def _fetch_public(url, *, timeout=PAGE_TIMEOUT, max_bytes=PAGE_MAX_BYTES):
    """(bytes, final_url, 'html'|'pdf') of one public page, through the public-address rules of candidate media."""
    from urllib.parse import urljoin
    from candidate_media import PublicConnection, public_address
    current = url
    stop = time.monotonic() + timeout
    for _ in range(4):
        parsed, address = public_address(current, timeout=max(1, stop - time.monotonic()))
        connection = PublicConnection(parsed.hostname, address, max(1, stop - time.monotonic()))
        try:
            connection.request('GET', parsed.path + ('?' + parsed.query if parsed.query else ''),
                               headers={'Accept': 'text/html,application/pdf;q=0.9',
                                        'User-Agent': 'Mozilla/5.0 (IPR-Public-Media/1.0)'})
            response = connection.getresponse()
            if response.status in (301, 302, 303, 307, 308):
                location = response.getheader('Location')
                if not location:
                    raise ValueError('PAGE_REDIRECT_LOCATION_REQUIRED')
                current = urljoin(current, location)
                continue
            if response.status != 200:
                raise ValueError('PAGE_HTTP_' + str(response.status))
            body = response.read(max_bytes + 1)
            if len(body) > max_bytes:
                raise ValueError('PAGE_SIZE_LIMIT')
            if body.startswith(b'%PDF'):
                return body, current, 'pdf'
            head = body[:4096].lower()
            if b'<html' in head or b'<!doctype html' in head:
                return body, current, 'html'
            raise ValueError('PAGE_NOT_HTML_OR_PDF')
        finally:
            connection.close()
    raise ValueError('PAGE_REDIRECT_LIMIT')


def page_text(data: bytes, kind: str) -> str:
    """Visible text of a retained page (HTML without scripts/styles) or the text layer of a PDF."""
    if kind == 'pdf':
        from io import BytesIO
        from pypdf import PdfReader
        reader = PdfReader(BytesIO(data))
        return '\n'.join('[page %d]\n%s' % (index + 1, page.extract_text() or '') for index, page in enumerate(reader.pages))
    from review_material_bundle import VisibleText
    parser = VisibleText()
    parser.feed(data.decode('utf-8', 'replace'))
    return '\n'.join(parser.parts)


def _terms(task):
    words = set()
    for row in task.get('query_terms') or []:
        value = row.get('value') if isinstance(row, dict) else row
        words.update(word.lower() for word in re.findall(r'[A-Za-z]{4,}', str(value or '')))
    title = (task.get('product') or {}).get('title')
    words.update(word.lower() for word in re.findall(r'[A-Za-z]{4,}', str(title or '')))
    return sorted(words)


def excerpt(text: str, task: dict):
    """(excerpt, complete, total_chars): the whole text when short, else its head plus every line naming the
    product's search words or a rights/dispute word, in document order. Deterministic for the same file and task."""
    lines = [' '.join(line.split()) for line in str(text or '').split('\n')]
    lines = [line for line in lines if line]
    full = '\n'.join(lines)
    if len(full) <= EXCERPT_LIMIT:
        return full, True, len(full)
    terms = _terms(task)
    words = re.compile('|'.join(re.escape(term) for term in terms), re.I) if terms else None
    head = full[:HEAD_CHARS]
    parts, used, offset = [head], len(head), 0
    for line in lines:
        start = full.find(line, offset)
        offset = max(offset, start + len(line)) if start >= 0 else offset
        if start >= 0 and start + len(line) <= HEAD_CHARS:
            continue
        if not (IP_WORDS.search(line) or (words and words.search(line))):
            continue
        piece = line[:LINE_CHARS]
        if used + len(piece) + 3 > EXCERPT_LIMIT:
            break
        parts.append(piece)
        used += len(piece) + 3
    return '\n…\n'.join(parts), False, len(full)


def _page_dir(root):
    return Path(root).joinpath(*PAGE_DIR)


def _failures(root):
    path = _page_dir(root) / FAILURES
    data = load_json(path) if path.is_file() else {}
    return data if isinstance(data, dict) else {}


def retained_card_page(evidence, candidate_id):
    """The evidence entry of the page the program retained for this card, or None."""
    for entry in (evidence.get('collections') or {}).get('sources', []):
        payload = entry.get('payload') if isinstance(entry, dict) else None
        if (isinstance(payload, dict) and payload.get('candidate_id') == candidate_id
                and payload.get('page_role') == CARD_PAGE_ROLE):
            return entry
    return None


def _targets(root, entries):
    from annotate_materiality import candidate_index
    from host_triage import text_only_lead
    root = Path(root)
    index, _ = candidate_index(load_json(root / 'normalized-candidates.json'))
    evidence = load_json(root / 'evidence.json')
    failures = _failures(root)
    result = []
    for cid in dict.fromkeys(entry.get('candidate_id') for entry in entries):
        if cid not in index:
            continue
        candidate = index[cid][1]
        url = str(candidate.get('url') or '')
        if (not text_only_lead(candidate) or not url.startswith('https://') or retained_card_page(evidence, cid)
                or (failures.get(cid) or {}).get('url') == url):
            continue
        result.append((cid, url, candidate))
    return result[:MAX_CARD_PAGES]


def prefetch_card_pages(root, entries, *, fetch=None):
    """Read the public page of every text-only web card about to be judged; register what was read.

    Pages are fetched side by side and registered one by one through record_public_source. A failure is kept (with
    its reason) so the same address is not fetched again by this task; it is never an exclusion by itself."""
    from core_dossier import _register
    root = Path(root)
    fetch = fetch or _fetch_public
    targets = _targets(root, entries)
    summary = {'fetched': 0, 'failed': []}
    if not targets:
        return summary

    def one(item):
        cid, url, _ = item
        try:
            return item, fetch(url), None
        except (OSError, ValueError) as exc:
            return item, None, (type(exc).__name__ + ':' + str(exc))[:200]

    with ThreadPoolExecutor(max_workers=min(4, len(targets))) as pool:
        outcomes = list(pool.map(one, targets))
    failures = _failures(root)
    folder = _page_dir(root)
    for (cid, url, candidate), fetched, error in outcomes:
        if fetched is not None:
            body, final, kind = fetched
            try:
                text = page_text(body, kind)
            except Exception as exc:  # an unreadable PDF text layer is a reading failure, not a crash
                fetched, error = None, ('PAGE_TEXT_UNREADABLE:' + type(exc).__name__)[:200]
            else:
                if len(' '.join(text.split())) < 40:
                    fetched, error = None, 'PAGE_TEXT_EMPTY'
        if fetched is None:
            failures[cid] = {'url': url, 'reason': error, 'at': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}
            summary['failed'].append({'candidate_id': cid, 'reason': error})
            continue
        path = folder / (cid + ('.pdf' if kind == 'pdf' else '.html'))
        atomic_write_bytes(path, body)
        _register(root, {'candidate_id': cid, 'kind': 'published_document', 'page_role': CARD_PAGE_ROLE,
            'jurisdiction': str(candidate.get('jurisdiction') or 'US'), 'right_type': candidate.get('right_type') or 'unknown',
            'path': str(path), 'sha256': sha256_bytes(body), 'bytes': len(body), 'source_url': url,
            'final_url': final, 'content_kind': kind,
            'reasoning': '公开网页卡片只有标题和摘要；程序按卡片自身的公开地址取回该网页原文留存，只用于判断该卡片与产品的关系，'
                         '不认定任何权利、登记或效力。'})
        failures.pop(cid, None)
        summary['fetched'] += 1
    folder.mkdir(parents=True, exist_ok=True)
    atomic_write_json(folder / FAILURES, failures)
    return summary


def card_page_view(root, task, evidence, candidate):
    """What the text judgment is given about a card's page: an excerpt bound to its evidence id, the recorded
    reason it could not be read, or None (not a web card / not attempted)."""
    cid = candidate.get('candidate_id')
    entry = retained_card_page(evidence, cid)
    if entry is not None:
        payload = entry['payload']
        from common import resolve_retained_path
        path = resolve_retained_path(Path(root), payload['path'], expected_sha256=payload['sha256'],
                                     expected_bytes=payload.get('bytes'))
        text = page_text(path.read_bytes(), payload.get('content_kind') or ('pdf' if path.suffix == '.pdf' else 'html'))
        body, complete, total = excerpt(text, task)
        return {'evidence_id': entry['evidence_id'], 'excerpt': body, 'complete': complete, 'chars': total,
                'note': ('程序按卡片地址取回的网页正文全文（%d 字）' % total if complete else
                         '程序按卡片地址取回的网页正文摘录：开头部分及含产品检索词或权利／争议用语的段落（全文 %d 字，摘录 %d 字）'
                         % (total, len(body)))}
    failure = _failures(root).get(cid)
    if failure and failure.get('url') == candidate.get('url'):
        return {'unavailable': failure.get('reason') or 'unknown'}
    return None


PUBLIC_TEXT_CARD_REOPEN = '取得该网页可读原文或其具体权利、登记、维权记录时重新分流'


def close_public_text_card(decision, card):
    """A needs_info on a public web card whose only next actions ask the user becomes not_selected (the same rule
    visual_triage_host.close_public_card applies to public picture cards): the user cannot supply facts about a
    third party's page. The missing facts stay on the record as reopen conditions; nothing is invented."""
    actions = decision.get('next_actions') or []
    if (decision.get('decision') != 'needs_info' or not actions
            or any(not isinstance(action, dict) or action.get('kind') != 'user_information' for action in actions)
            or card.get('right_type') not in (None, '', 'unknown') or card.get('candidate_nature') != 'web_result'
            or card.get('publication_number') or card.get('registration_number')):
        return decision
    missing = [str(item) for item in decision.get('missing_information') or [] if str(item).strip()]
    comparison = dict(decision.get('comparison') or {})
    for key in ('missing_fact_effect', 'completion_condition', 'existing_material_review'):
        comparison.pop(key, None)
    read = '及程序取回的网页正文' if card.get('page_excerpt') else ''
    comparison['difference'] = ('公开网页卡片' + read + '不足以建立与产品对象的具体关联；所缺事实（'
                                + ('；'.join(missing) or '该网页的具体内容') + '）只能由该网页来源提供，用户无法补充。')
    comparison['applicability_limit'] = ('仅依据卡片标题、摘要' + read + '；未入选不等于法律不侵权，'
                                         '取得该网页可读原文或具体权利记录时重新分流。')
    closed = {key: value for key, value in decision.items() if key not in ('missing_information', 'next_actions')}
    closed.update(decision='not_selected', comparison=comparison,
                  reason='公开网页卡片资料不足且所缺事实用户无法提供，按程序规则不入选：' + str(decision.get('reason') or ''),
                  basis_summary=('程序规则（公开卡片不向用户索取第三方信息）；' + str(decision.get('basis_summary') or ''))[:600],
                  reopen_conditions=list(dict.fromkeys([*(decision.get('reopen_conditions') or []), PUBLIC_TEXT_CARD_REOPEN,
                                                        *[('补得：' + item)[:200] for item in missing]])))
    return closed


# ----- final-review packet diet ---------------------------------------------------------------------------------
def _annotation_time(row):
    return str(row.get('annotated_at') or '')


def ledger_excluded(source, excluded):
    """Add candidates whose newest decision in every triaged scope is not_selected according to the ledger itself.

    The candidate file's projection can lag behind the ledger (r5d2 run: three cards closed by hand still showed
    their earlier needs_info in normalized-candidates.json, so their 393 KB pages went to every module). For each
    (candidate, scenario, country, right) the newest of the ledger rows and the projected current rows wins."""
    from annotate_materiality import iter_candidates
    newest = {}
    def offer(row):
        key = tuple(row.get(name) for name in ('candidate_id', 'scenario_id', 'jurisdiction', 'right_type'))
        if key[0] and (key not in newest or _annotation_time(row) >= _annotation_time(newest[key])):
            newest[key] = row
    for row in ((source.get('materiality_ledger') or {}).get('annotations') or []):
        if isinstance(row, dict):
            offer(row)
    for _, item in iter_candidates(source.get('candidates') or {}):
        for rows in (item.get('triage_by_scenario') or {}).values():
            for row in rows if isinstance(rows, list) else []:
                annotation = row.get('annotation') if isinstance(row, dict) else None
                if isinstance(annotation, dict) and row.get('current'):
                    offer({**annotation, 'decision': row.get('decision', annotation.get('decision'))})
    by_candidate = {}
    for key, row in newest.items():
        by_candidate.setdefault(key[0], []).append(row)
    added = {}
    for cid, rows in by_candidate.items():
        if cid in excluded or not rows or any(row.get('decision') != 'not_selected' for row in rows):
            continue
        latest = max(rows, key=_annotation_time)
        added[cid] = {'decision': 'not_selected', 'reason': latest.get('reason') or ''}
    return added


def evidence_owners(source):
    """evidence_id -> {candidate_id} for the full frozen records that name their candidate (retained pages,
    drawings and documents registered for one candidate)."""
    owners = {}
    collections = ((source.get('evidence') or {}).get('collections') or {}) if isinstance(source, dict) else {}
    for rows in collections.values():
        for record in rows if isinstance(rows, list) else []:
            if not isinstance(record, dict) or not record.get('evidence_id'):
                continue
            payload = record.get('payload') if isinstance(record.get('payload'), dict) else {}
            ids = {value for value in (record.get('candidate_id'), payload.get('candidate_id'))
                   if isinstance(value, str) and value}
            if ids:
                owners[record['evidence_id']] = ids
    return owners


ANNOTATION_STUB_FIELDS = ('annotation_id', 'candidate_id', 'scenario_id', 'jurisdiction', 'right_type', 'decision',
                          'reason', 'reviewer', 'annotated_at', 'reading_level', 'evidence_refs', 'reopen_conditions')


def stub_annotations(ledger, excluded):
    """Triage annotations of not_selected candidates keep their decision, reason, reviewer and evidence ids plus the
    concrete difference; the repeated product description and card copy become the full annotation's hash."""
    rows = ledger.get('annotations') if isinstance(ledger, dict) else None
    if not isinstance(rows, list):
        return 0
    count = 0
    projected = []
    for row in rows:
        if isinstance(row, dict) and row.get('candidate_id') in excluded:
            stub = {key: row[key] for key in ANNOTATION_STUB_FIELDS if row.get(key) not in (None, '', [])}
            comparison = row.get('comparison') if isinstance(row.get('comparison'), dict) else {}
            for key in ('difference', 'applicability_limit'):
                if comparison.get(key):
                    stub.setdefault('comparison', {})[key] = comparison[key]
            stub['review_packet_stub'] = {'revision': REVISION, 'annotation_sha256': sha256_json(row)}
            projected.append(stub)
            count += 1
        else:
            projected.append(row)
    ledger['annotations'] = projected
    return count
