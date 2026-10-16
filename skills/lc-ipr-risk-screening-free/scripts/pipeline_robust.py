#!/usr/bin/env python3
"""Runs that do not stop where a program can act (new tasks with ``pipeline_robust_revision``, r5d4).

r5d4 real run B0FSJBDTF2_US_20261012 (about 75 minutes, no report) stopped or stalled at points the program owns:

* the first direction review died with the network (the Mac slept); the runner then deferred all eleven planned
  discovery queries and each deferral was booked as a no-progress round, eleven of the twelve allowed, so every later
  dispatch sent one query (``advance_work`` caps a call by the rounds left). The two EPO queries that find the
  decisive design patents were never sent by the pipeline. Rows the runner's own gate holds (missing direction or
  expression review, pending recovery review, ...) are now left out before the cap, so a gate never spends rounds;
* image cards the visual host cannot prepare (or has no picture of) held back every new source through the
  "triage first" rule. Cards the hosts already refused at preparation or media time no longer hold dispatch: they
  stay open triage work and are listed at checkpoint 2.

Nothing here judges a candidate, relaxes a validator or changes the report.
"""
from __future__ import annotations

from pathlib import Path

from common import load_json

REVISION = 'robust-v1'
REFUSED_PHASES = frozenset({'preparation', 'media'})
# r5d17 (run B0HF19R4YF, 41 minutes): speed without changing any judgment - final-review originals once per file
# content, comparison sessions in five slots, malformed comparison ids normalized instead of voiding the batch, and
# the idle source and core rounds skipped.
SPEED_REVISION = 'speed-v1'


def enabled(task) -> bool:
    return isinstance(task, dict) and task.get('pipeline_robust_revision') == REVISION


def speed_enabled(task) -> bool:
    return isinstance(task, dict) and task.get('pipeline_speed_revision') == SPEED_REVISION


def review_rules_enabled(task) -> bool:
    """The final-review rules of r5d4 (licence default, candidate evidence binding) also apply to r5d3 tasks: those
    tasks can be continued to a report under r5d4 (B0FSJBDTF2), and without the binding rule a 高 design finding
    whose reviewers cited only drawings is silently turned into 待定 at publication."""
    import review_focus
    return enabled(task) or review_focus.enabled(task)


def enabled_dir(root) -> bool:
    try:
        return enabled(load_json(Path(root) / 'task.json'))
    except (OSError, ValueError):
        return False


# ----- source dispatch ------------------------------------------------------------------------------------------
def gated_queries(task_dir, plan, entries):
    """{query_id: code} for the source entries whose exact plan row the runner would hold with a temporary code.

    The runner records such a hold as a deferred, not-submitted attempt and the dispatcher books it as a
    no-progress round; the hold itself is checked again by the runner when the row is finally sent."""
    from advance_work import plan_rows
    from workflow_v24 import TEMPORARY_DISPATCH_CODES, scenario_dispatch_block_from_dir
    index = plan_rows(plan)
    result = {}
    for query_id in dict.fromkeys(str(entry.get('query_id') or '') for entry in entries):
        found = index.get(query_id)
        if not found:
            continue
        provider, row = found
        try:
            block = scenario_dispatch_block_from_dir(Path(task_dir), provider, row)
        except (OSError, ValueError, KeyError, TypeError):
            continue                       # cannot tell here: the runner decides, as before
        code = str((block or {}).get('code') or (block or {}).get('reason') or '')
        if code in TEMPORARY_DISPATCH_CODES:
            result[query_id] = code
    return result


def dispatchable(task_dir, plan, entries):
    """(entries the runner can take now, {query_id: code} held by a temporary gate)."""
    held = gated_queries(task_dir, plan, entries) if entries else {}
    return [entry for entry in entries if str(entry.get('query_id') or '') not in held], held


def refused_work_ids(task_dir) -> set:
    """Triage work the hosts already refused before any judgment (preparation or media phase) in their last run."""
    path = Path(task_dir) / 'visual-triage' / 'last-run.json'
    try:
        summary = load_json(path) if path.is_file() else {}
    except (OSError, ValueError):
        return set()
    result = set()
    for batch in summary.get('batches', []) if isinstance(summary, dict) else []:
        if isinstance(batch, dict) and batch.get('status') == 'needs_info' and batch.get('phase') in REFUSED_PHASES:
            result.update(str(work_id) for work_id in batch.get('work_ids') or [] if work_id)
    return result


# ----- "record not found" closeouts -----------------------------------------------------------------------------
CLOSEOUT_REVIEWER = 'program:record-not-found'


def record_absent_runs(evidence):
    """Submitted exact-record reads the source answered with "no such record" and nobody reviewed yet."""
    from recovery_stage_b import RECORD_ABSENT_CODES, _latest, effective_submission
    return [run for run in evidence.get('source_runs', []) if isinstance(run, dict)
            and run.get('operation') == 'candidate_detail' and run.get('status') == 'failed'
            and str(run.get('error_code') or '') in RECORD_ABSENT_CODES
            and effective_submission(evidence, run) == 'submitted'
            and not _latest(evidence, run, 'failure_review')]


def close_record_not_found(root):
    """Close every unreviewed "no such record" exact read the way the recovery recorder requires: the receipt is an
    explicit non-result error and the source allows no retry (asking again returns the same answer). One failed read
    used to raise five blockers (receipt processing, recovery review, potential material, specialty source and
    intake; B0FSJBDTF2). The candidate keeps its record gap as a disclosed limitation; nothing is inferred."""
    from common import sha256_json
    from recovery_stage_b import record_failure_closeout
    root = Path(root)
    task = load_json(root / 'task.json')
    summary = {'recorded': 0, 'closed': [], 'rejected': []}
    if not enabled(task):
        return summary
    evidence = load_json(root / 'evidence.json')
    plan = load_json(root / 'search-plan.json') if (root / 'search-plan.json').is_file() else {}
    rows = {(provider, row.get('query_id')): row for provider, values in (plan.get('queries') or {}).items()
            for row in values if isinstance(row, dict)}
    for run in record_absent_runs(evidence):
        row = rows.get((run.get('provider'), run.get('query_id')))
        if row is None or sha256_json(row) != run.get('plan_entry_sha256'):
            continue
        number = str((run.get('request_params') or {}).get('q') or row.get('q') or run.get('query_id'))
        reason = ('%s 的准确记录接口明确回答“查无此记录”（%s）；同一请求再发只会得到同样答复。' % (number, run.get('error_code')))
        review = {'reviewer': CLOSEOUT_REVIEWER, 'reasoning': reason,
                  'receipt_review': '回执是来源的“查无此记录”答复，不含任何记录或卡片。',
                  'material_review': '本次读取未取得任何可读材料。',
                  'remaining_work': '该候选的记录事实保持未知，作为有记录的限制随报告保留。',
                  'repair_basis': '号码已按来源的写法发送；来源答复本身是确定的，不属于可修复的请求错误。',
                  'source_rule_ref': 'SerpApi Google Patents Details：无结果答复（PROVIDER_RECORD_NOT_FOUND）',
                  'source_allows_retry': False, 'retry_disposition': 'not_requested',
                  'no_retry_reason': '来源明确答复无此记录；重复请求不会改变结果。',
                  'retry_constraint': {'kind': 'source_record_absent', 'provider': run.get('provider'),
                                       'plan_entry_sha256': sha256_json(row), 'error_code': run.get('error_code')}}
        if not run.get('raw_paths'):
            review['receipt_absence_reason'] = '来源只返回错误答复，未留存原始回执文件。'
        try:
            record_failure_closeout(root, source_run_id=run['run_id'], source_run_sha256=sha256_json(run),
                receipt_disposition={'outcome': 'non_result_error', 'reviewer': CLOSEOUT_REVIEWER, 'reason': reason},
                failure_review=review)
            summary['recorded'] += 1
            summary['closed'].append(run['run_id'])
        except (OSError, ValueError, KeyError, TypeError) as exc:
            summary['rejected'].append({'run_id': run.get('run_id'), 'reason': str(exc)[:200]})
    return summary


# ----- network failures: one retry of the same request (r5d25) ---------------------------------------------------
RETRY_REVIEWER = 'program:network-retry'
NETWORK_CODES = frozenset({'PROVIDER_NETWORK_ERROR'})
RETRY_PROVIDERS = frozenset({'serpapi_google_patents'})


def network_failed_runs(evidence):
    """Submitted Google Patents requests that ended in a transport failure (no answer, no receipt) and nobody
    reviewed yet - the first such failure of their request only; a second one is the recovery limit."""
    from recovery_stage_b import _latest, effective_submission, request_identity
    failed = [run for run in evidence.get('source_runs', []) if isinstance(run, dict)
              and run.get('provider') in RETRY_PROVIDERS and run.get('status') == 'failed'
              and str(run.get('error_code') or '') in NETWORK_CODES and not run.get('raw_paths')
              and effective_submission(evidence, run) == 'submitted']
    def identity(run):
        return request_identity({'task_id': evidence.get('task_id')}, run.get('provider'), run)['recovery_object_id']
    counts = {}
    for run in failed:
        counts[identity(run)] = counts.get(identity(run), 0) + 1
    return [run for run in failed if counts[identity(run)] == 1 and not _latest(evidence, run, 'failure_review')]


def retry_network_failures(root):
    """Allow one more send of a planned search or detail read that failed in transport (run B0GLNPC6K8: the
    "touch activation" search timed out after 31 s, was never sent again and reached the report as 查询失败). The
    request is the same one, so this widens nothing: SerpApi answers a repeat of the same parameters from its one-hour
    cache without charging again, and the task's request limit still applies. A second failure stays a limitation."""
    from common import sha256_json
    from recovery_stage_b import record_failure_closeout
    root = Path(root)
    task = load_json(root / 'task.json')
    summary = {'recorded': 0, 'retry_allowed': [], 'rejected': []}
    if not enabled(task):
        return summary
    evidence = load_json(root / 'evidence.json')
    plan = load_json(root / 'search-plan.json') if (root / 'search-plan.json').is_file() else {}
    rows = {(provider, row.get('query_id')): row for provider, values in (plan.get('queries') or {}).items()
            for row in values if isinstance(row, dict)}
    for run in network_failed_runs(evidence):
        row = rows.get((run.get('provider'), run.get('query_id')))
        if row is None or sha256_json(row) != run.get('plan_entry_sha256'):
            continue
        reason = ('%s 的请求在传输中失败（%s，未收到来源答复）；按原参数再发一次，同参数请求由 SerpApi 一小时缓存应答、不重复计费。'
                  % (run.get('query_id'), run.get('error_code')))
        review = {'reviewer': RETRY_REVIEWER, 'reasoning': reason,
                  'receipt_review': '没有回执：请求在收到来源答复前中断。',
                  'material_review': '本次请求未取得任何材料。',
                  'remaining_work': '同一请求再发一次；再次失败则作为有记录的限制随报告保留。',
                  'repair_basis': '请求本身没有错误，失败发生在网络传输；原参数不变。',
                  'source_rule_ref': 'SerpApi：同参数请求一小时内由缓存应答，不计费',
                  'source_allows_retry': True, 'retry_disposition': 'requested',
                  'receipt_absence_reason': '请求在收到来源答复前中断，没有可留存的回执。'}
        try:
            # no receipt exists, so there is no receipt disposition to bind - only the retry decision
            record_failure_closeout(root, source_run_id=run['run_id'], source_run_sha256=sha256_json(run),
                receipt_disposition=None, failure_review=review)
            summary['recorded'] += 1
            summary['retry_allowed'].append(run['run_id'])
        except (OSError, ValueError, KeyError, TypeError) as exc:
            summary['rejected'].append({'run_id': run.get('run_id'), 'reason': str(exc)[:200]})
    return summary


# ----- visual triage --------------------------------------------------------------------------------------------
def choose_product_views(preferred, limit):
    """(the first ``limit`` distinct product views in task order - main image first -, omitted image ids).

    The visual host used to refuse every batch when a product had more views than one session takes (B0FSJBDTF2: 7
    images, limit 6), so no picture card could ever be triaged. The choice is deterministic so the commit-time
    packet is the same packet; the omitted views are disclosed on every decision."""
    kept, seen, omitted = [], set(), []
    for ref, row in preferred:
        if row['sha256'] in seen:
            kept.append((ref, row))            # the same picture under another id costs no extra view
            continue
        if len(seen) < limit:
            seen.add(row['sha256'])
            kept.append((ref, row))
        else:
            omitted.append(ref)
    return kept, omitted


DESIGN_PICTURES = ('raw', 'design-pictures')
PERMANENT_PICTURE_FAILURES = ('DOCUMENT_HTTP_404', 'PUBLIC_PAGE_IDENTITY_MISMATCH', 'DOCUMENT_NOT_HTML')
# r5d7: the official file server answers for every granted US design, Google Patents only for older ones
USPTO_PDF = 'https://image-ppubs.uspto.gov/dirsearch-public/print/downloadPdf/'
PERMANENT_USPTO_FAILURES = ('DOCUMENT_HTTP_404', 'DOCUMENT_NOT_PDF', 'PDF_PAGES_UNREADABLE', 'USPTO_PDF_NO_PAGE_IMAGE',
                            'USPTO_NUMBER_UNSUPPORTED')
MAX_DESIGN_PAGES = 16


def has_picture(evidence, candidate_id) -> bool:
    """True when an image file is retained for the candidate (any registered collection)."""
    for rows in (evidence.get('collections') or {}).values():
        for row in rows if isinstance(rows, list) else []:
            payload = row.get('payload') if isinstance(row, dict) and isinstance(row.get('payload'), dict) else {}
            owner = (row.get('candidate_id') if isinstance(row, dict) else None) or payload.get('candidate_id')
            path = str(payload.get('path') or (row.get('path') if isinstance(row, dict) else '') or '')
            if owner == candidate_id and Path(path).suffix.lower() in {'.png', '.jpg', '.jpeg', '.webp'}:
                return True
    return False


def us_design_number(candidate):
    """The candidate's US design publication number in the Google Patents spelling, or None."""
    from common import canonical_patent_number
    number = canonical_patent_number(candidate.get('publication_number'))
    return number if candidate.get('right_type') == 'design' and number.startswith('USD') else None


def uspto_pdf_url(number):
    """USD1146173S1 -> the USPTO grant PDF address .../downloadPdf/D1146173 (None for another number form)."""
    import re
    match = re.fullmatch(r'USD0*(\d{1,8})S\d?', str(number or ''))
    return USPTO_PDF + 'D' + match.group(1) if match else None


def _fetch_uspto_pdf(url):
    import core_dossier
    return core_dossier._fetch_document(url, timeout=60, browser=True)


def retain_uspto_pages(root, candidate, number, body, url, *, max_pages=None, max_images=None):
    """Register the page images of an already fetched USPTO grant PDF as the candidate's drawings.

    r5d7 real run B0GLNPC6K8: 14 of 16 design candidates were granted in 2026; Google Patents had no page for some
    (HTTP 404) and refuses the drawing files of the others (HTTP 403 for everyone), so all were selected unseen and
    read by hand from this same official PDF. Each page is the office's own scanned sheet (number, sheet and figure
    printed on it), kept as a grayscale PNG with the PDF's hash and page number beside it. Returns
    {'pages': n} or {'failure': reason}; nothing is decided here."""
    import re
    import core_dossier
    import image_convert
    from common import atomic_write_bytes, sha256_bytes
    root = Path(root)
    cid = candidate['candidate_id']
    try:
        pages = image_convert.pdf_page_pngs(body, max_pages=max_pages or core_dossier.MAX_DESIGN_DRAWINGS,
                                            max_images=max_images)
    except ValueError as exc:
        return {'failure': str(exc)[:200]}
    if not pages:
        return {'failure': 'USPTO_PDF_NO_PAGE_IMAGE'}
    folder = root.joinpath(*DESIGN_PICTURES, re.sub(r'[^A-Za-z0-9_-]', '_', number))
    document = folder / 'uspto-grant.pdf'
    if not document.is_file() or document.read_bytes() != body:
        atomic_write_bytes(document, body)
    digest = sha256_bytes(body)
    registered = 0
    for page_number, png in pages:
        page_digest = sha256_bytes(png)
        known, _ = core_dossier._registered(load_json(root / 'evidence.json'), page_digest, cid)
        if not known:
            path = folder / ('page-%02d.png' % page_number)
            atomic_write_bytes(path, png)
            core_dossier._register(root, {
                'publication_number': number, 'jurisdiction': 'US', 'right_type': 'design', 'candidate_id': cid,
                'kind': 'patent_drawing_image', 'visual_role': 'patent_drawings',
                'figure_label': 'USPTO-P%02d' % page_number, 'path': str(path), 'sha256': page_digest,
                'bytes': len(png), 'source_url': url,
                'derived_from': {'original_file': str(document.relative_to(root)), 'original_sha256': digest,
                                 'original_bytes': len(body), 'page_number': page_number,
                                 'transform': image_convert.PDF_PAGE_TRANSFORM},
                'reasoning': ('按准确美国外观授权号从 USPTO 官方原始文件入口取回授权 PDF（%s），第 %d 页的扫描图样原样转为'
                              '灰度 PNG 留存；页上印有案号、页码与图号。仅作图样，不含比较结论；文件不证明当前维持状态。'
                              % (url, page_number))})
            known, _ = core_dossier._registered(load_json(root / 'evidence.json'), page_digest, cid)
        registered += int(bool(known))
    return {'pages': registered} if registered else {'failure': 'USPTO_PAGE_REGISTRATION_FAILED'}


def complete_uspto_pages(root, candidate_id):
    """r5d24: the design screen registers only the first pages of a USPTO grant PDF; a design selected for the deep
    check gets the rest of the same retained PDF (no new request). Returns the pages added (0 when nothing to do)."""
    import core_dossier
    from common import sha256_bytes
    root = Path(root)
    rows = []
    for entry in (load_json(root / 'evidence.json').get('collections') or {}).get('sources', []):
        payload = entry.get('payload') if isinstance(entry, dict) and isinstance(entry.get('payload'), dict) else {}
        derived = payload.get('derived_from') if isinstance(payload.get('derived_from'), dict) else {}
        if (payload.get('kind') == 'patent_drawing_image' and payload.get('candidate_id') == candidate_id
                and str(payload.get('source_url') or '').startswith(USPTO_PDF) and derived.get('original_file')):
            rows.append((payload, derived))
    if not rows:
        return 0
    import precision
    if len(rows) > precision.SCREEN_DRAWINGS:
        return 0
    payload, derived = rows[0]
    document = root / str(derived['original_file'])
    try:
        body = document.read_bytes()
    except OSError:
        return 0
    if sha256_bytes(body) != derived.get('original_sha256'):
        return 0
    result = retain_uspto_pages(root, {'candidate_id': candidate_id}, str(payload.get('publication_number')), body,
                                str(payload.get('source_url')), max_pages=core_dossier.MAX_DESIGN_DRAWINGS)
    return max(0, int(result.get('pages') or 0) - len(rows))


RECENT_DESIGN_DAYS = 490
USPTO_WORKERS = 6
# r9 (run B0FHQ475MY: about 100 designs, 160 s of page and drawing reads before the screen): the Google pages and
# drawings are read side by side in as many threads as the USPTO PDFs (was 4)
GOOGLE_WORKERS = 6


def recent_design(candidate, today=None) -> bool:
    """r5d24 (B0GLNPC6K8): Google Patents served the drawings of every design granted before 2025-07 and refused
    (HTTP 403) every later one; the cat screen fetched 65 such pages for nothing before the USPTO PDF. A design granted
    within about 16 months goes straight to the USPTO grant PDF (Google stays its fallback)."""
    import datetime
    text = str(candidate.get('publication_date') or candidate.get('grant_date') or '')[:10]
    try:
        granted = datetime.date.fromisoformat(text)
    except ValueError:
        return False
    return ((today or datetime.date.today()) - granted).days <= RECENT_DESIGN_DAYS


def retain_design_pictures(root, entries, *, fetch_page=None, fetch_image=None, fetch_pdf=None,
                           max_pages=MAX_DESIGN_PAGES, drawings=None, today=None):
    """Before the visual triage, retain the drawings of US design candidates that have no picture (EPO results carry
    no image; B0FSJBDTF2: 12 such designs were triaged by title, then read by hand): the public Google Patents page
    and its drawings first, then (r5d7) the official USPTO grant PDF for every design still without a picture.
    Pages are fetched side by side, registrations one at a time; a Google page that names another number is refused
    by ``core_dossier.retain_page``. Returns a summary; nothing is decided here.

    ``drawings`` (r5d24, the precision-v1 design screen) takes only that many drawings per design - the screen looks
    at two - and sends recent grants (``recent_design``) to the USPTO first, their PDFs fetched while the Google pages
    of the older ones are read; a design that fails on its first route tries the other. B0GLNPC6K8 (103 designs):
    every drawing of every design was fetched and registered, 17 minutes before the 52-second screen, and the 958
    images later overflowed the final review's bundle."""
    import core_dossier
    import core_focus
    from annotate_materiality import candidate_index
    from concurrent.futures import ThreadPoolExecutor
    from common import atomic_write_json
    root = Path(root)
    evidence = load_json(root / 'evidence.json')
    index, _ = candidate_index(load_json(root / 'normalized-candidates.json'))
    folder = root.joinpath(*DESIGN_PICTURES)
    failures_path = folder / 'failures.json'
    failures = load_json(failures_path) if failures_path.is_file() else {}
    per_design = core_dossier.MAX_DESIGN_DRAWINGS if drawings is None else min(drawings, core_dossier.MAX_DESIGN_DRAWINGS)

    def permanent(number, key, prefixes):
        # failures are stored as 'ValueError:DOCUMENT_HTTP_404'; the code after the exception name decides
        reason = str((failures.get(number) or {}).get(key) or '')
        return reason.split(':', 1)[-1].startswith(prefixes) if reason.startswith(('ValueError:', 'OSError:')) \
            else reason.startswith(prefixes)
    wanted = []
    for cid in dict.fromkeys(str(entry.get('candidate_id') or '') for entry in entries):
        found = index.get(cid)
        candidate = found[1] if found else None
        number = us_design_number(candidate) if candidate else None
        if (not number or has_picture(evidence, cid)
                or (permanent(number, 'reason', PERMANENT_PICTURE_FAILURES)
                    and permanent(number, 'uspto', PERMANENT_USPTO_FAILURES))):
            continue
        wanted.append((cid, candidate, number))
    wanted = wanted[:max_pages]
    summary = {'requested': len(wanted), 'retained': [], 'failed': []}
    if not wanted:
        return summary
    fetch_page = fetch_page or core_dossier._fetch_page
    fetch_image = fetch_image or core_dossier._fetch_image
    fetch_pdf = fetch_pdf or _fetch_uspto_pdf
    official_first = {cid for cid, candidate, number in wanted
                      if drawings is not None and recent_design(candidate, today)
                      and not permanent(number, 'uspto', PERMANENT_USPTO_FAILURES)}
    google_failed = {}

    def pdf(number):
        url = uspto_pdf_url(number)
        if not url:
            return number, url, None, 'USPTO_NUMBER_UNSUPPORTED'
        try:
            body, _ = fetch_pdf(url)
            return number, url, body, None
        except (OSError, ValueError) as exc:
            return number, url, None, (type(exc).__name__ + ':' + str(exc))[:200]

    def google_round(items):
        """Fetch the Google pages and their first drawings side by side, then register one design at a time."""
        pages, images = {}, {}

        def page(number):
            try:
                return number, fetch_page(core_focus.page_url(number)), None
            except (OSError, ValueError) as exc:
                return number, None, (type(exc).__name__ + ':' + str(exc))[:200]

        with ThreadPoolExecutor(max_workers=GOOGLE_WORKERS) as pool:
            for number, body, error in pool.map(page, [number for _, _, number in items]):
                pages[number] = (body, error)
        urls = []
        for number, (body, _) in pages.items():
            if body:
                facts = core_focus.page_facts(body[0].decode('utf-8', 'replace'))
                urls += [url for url in (facts.get('images') or [])[:per_design]
                         if isinstance(url, str) and url.startswith('https://')]

        def image(url):
            try:
                return url, fetch_image(url), None
            except (OSError, ValueError) as exc:
                return url, None, exc

        with ThreadPoolExecutor(max_workers=GOOGLE_WORKERS) as pool:
            for url, value, error in pool.map(image, list(dict.fromkeys(urls))):
                images[url] = (value, error)

        def cached_image(url):
            value, error = images.get(url, (None, ValueError('IMAGE_NOT_PREFETCHED')))
            if error is not None:
                raise error if isinstance(error, (OSError, ValueError)) else ValueError(str(error))
            return value

        for cid, candidate, number in items:
            body, error = pages.get(number, (None, 'PAGE_NOT_FETCHED'))
            if error:
                google_failed[cid] = error
                failures.setdefault(number, {}).update(reason=error, candidate_id=cid)
                continue
            result = core_dossier.retain_page(root, candidate, number, role='public_page',
                                              fetch_page=lambda url, _body=body: _body, fetch_image=cached_image,
                                              **({'drawings': per_design} if drawings is not None else {}))
            if result.get('failure'):
                google_failed[cid] = result['failure']
                failures.setdefault(number, {}).update(reason=result['failure'], candidate_id=cid)
                continue
            found = [row for row in (result.get('files') or {}).get('drawings', []) if row.get('evidence_id')]
            if found:
                summary['retained'].append({'candidate_id': cid, 'number': number, 'page': result.get('evidence_id'),
                                            'drawings': len(found), 'source': 'google_patents'})
            else:
                # Google lists the drawings of a recent grant but refuses the files (HTTP 403 for everyone)
                google_failed[cid] = 'GOOGLE_DRAWINGS_UNAVAILABLE'

    def official_round(items, documents):
        for cid, candidate, number in items:
            url, body, error = documents[number]
            result = {'failure': error} if error else retain_uspto_pages(
                root, candidate, number, body, url, **({'max_images': per_design} if drawings is not None else {}))
            if result.get('failure'):
                failures.setdefault(number, {}).update(uspto=result['failure'].split(':', 1)[-1]
                                                       if result['failure'].startswith('ValueError:') else result['failure'],
                                                       candidate_id=cid)
                if cid in official_first and not permanent(number, 'reason', PERMANENT_PICTURE_FAILURES):
                    continue                                      # its Google page is tried below
                summary['failed'].append({'candidate_id': cid, 'number': number,
                                          'reason': google_failed.get(cid) or '', 'uspto': result['failure']})
                continue
            summary['retained'].append({'candidate_id': cid, 'number': number, 'drawings': result['pages'],
                                        'source': 'uspto_pdf', 'url': url})

    early = [item for item in wanted if item[0] in official_first]
    google = [(cid, candidate, number) for cid, candidate, number in wanted
              if cid not in official_first and not permanent(number, 'reason', PERMANENT_PICTURE_FAILURES)]
    documents = {}
    with ThreadPoolExecutor(max_workers=USPTO_WORKERS) as official_pool:
        # the recent grants' PDFs download while the older designs' Google pages are read
        pending = {number: official_pool.submit(pdf, number) for _, _, number in early}
        google_round(google)
        for number, future in pending.items():
            _, url, body, error = future.result()
            documents[number] = (url, body, error)
    official_round(early, documents)
    evidence = load_json(root / 'evidence.json')
    official = [(cid, candidate, number) for cid, candidate, number in wanted
                if cid not in official_first and not has_picture(evidence, cid)
                and not permanent(number, 'uspto', PERMANENT_USPTO_FAILURES)]
    later = {}
    with ThreadPoolExecutor(max_workers=USPTO_WORKERS if drawings is not None else 4) as pool:
        for number, url, body, error in pool.map(pdf, [number for _, _, number in official]):
            later[number] = (url, body, error)
    official_round(official, later)
    evidence = load_json(root / 'evidence.json')
    fallback = [(cid, candidate, number) for cid, candidate, number in early
                if not has_picture(evidence, cid) and not permanent(number, 'reason', PERMANENT_PICTURE_FAILURES)]
    if fallback:
        google_round(fallback)
        for cid, candidate, number in fallback:
            if cid in google_failed:
                summary['failed'].append({'candidate_id': cid, 'number': number, 'reason': google_failed[cid],
                                          'uspto': (failures.get(number) or {}).get('uspto') or ''})
    folder.mkdir(parents=True, exist_ok=True)
    atomic_write_json(failures_path, failures)
    atomic_write_json(folder / 'last-run.json', summary)
    return summary


def selected_candidate_ids(root) -> set:
    """Candidates with at least one current selected scope (the same projection the review unit count uses)."""
    from decision_workflow import triage_summary
    from workflow_v24 import scenario_supplement
    root = Path(root)
    task = load_json(root / 'task.json')
    evidence = load_json(root / 'evidence.json')
    candidates = load_json(root / 'normalized-candidates.json')
    ledger = load_json(root / 'materiality-annotations.json')
    supplement = scenario_supplement(root, task=task, evidence=evidence)
    records = triage_summary(task, candidates, ledger, evidence=evidence, supplement=supplement).get('records', [])
    return {row.get('candidate_id') for row in records if row.get('decision') == 'selected' and row.get('candidate_id')}


def unresolved_text_candidates(task_dir) -> set:
    """r5d23: candidates the text host left unresolved after its own retry in its last run.

    Run B0GLNPC6K8 (r5d21): one lawsuit web card whose page could not be read behind the proxy was answered "needs
    information" without any executable next step, which the recorder refuses; the card stayed open triage work and the
    "triage first" rule then held back all seven planned searches (eleven work items) - two first-round discovery queries, the copyright
    image searches and three detail reads of selected patents - until the core stage failed. Such a card stays open
    and is listed (checkpoint 2 or the time-box closure); it no longer holds back dispatch."""
    path = Path(task_dir) / 'text-triage' / 'last-run.json'
    try:
        summary = load_json(path) if path.is_file() else {}
    except (OSError, ValueError):
        return set()
    rows = summary.get('unresolved', []) if isinstance(summary, dict) else []
    return {str(row['candidate_id']) for row in rows if isinstance(row, dict) and row.get('candidate_id')}


def light_triage_pending(view, task_dir) -> bool:
    """``candidate_triage_stage.light_triage_pending`` without the work the hosts already refused or left unresolved."""
    from candidate_triage_stage import light_triage_pending as pending
    refused = refused_work_ids(task_dir)
    unresolved = unresolved_text_candidates(task_dir)
    if not refused and not unresolved:
        return pending(view)
    return pending({**view, 'entries': [row for row in view.get('entries', [])
                                        if str(row.get('work_id') or '') not in refused
                                        and not (row.get('kind') == 'triage'
                                                 and str(row.get('candidate_id') or '') in unresolved)]})


def main(argv=None):
    import argparse
    import json
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--task-dir', type=Path, required=True)
    parser.add_argument('--closeouts', action='store_true',
                        help='Close unreviewed "no such record" exact reads (receipt disposition + no-retry review)')
    args = parser.parse_args(argv)
    result = {}
    if args.closeouts:
        result['closeouts'] = close_record_not_found(args.task_dir.resolve())
        result['network_retries'] = retry_network_failures(args.task_dir.resolve())
    result['recorded'] = sum(value.get('recorded', 0) for value in result.values() if isinstance(value, dict))
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
