#!/usr/bin/env python3
"""EPO Publication Server REST 1.2: known EP documents, never national status.

Contract: https://data.epo.org/publication-server/doc/EPS%20REST%20services.pdf
Use the stricter current webpage limit: 5 GB per IP per rolling seven days.
The local ledger covers all Skill tasks on this computer; it cannot observe other
computers sharing the IP. Server quota responses always stop further requests.
"""
from __future__ import annotations
import argparse
import json
import math
import os
import re
import secrets
import time
from contextlib import contextmanager
from pathlib import Path
from urllib import error, request
from xml.etree import ElementTree
from common import atomic_write_json, load_json, now_iso, sha256_bytes
from provider_utils import ProviderError, assert_test_endpoint, request_timeout, classify_http, record_error, record_result, file_lock
from provider_plan_v24 import load_action

PROVIDER = 'epo_publication_server'
BASE = 'https://data.epo.org/publication-server/rest/v1.2'
WINDOW_SECONDS = 7 * 86400
FREE_LIMIT = 5_000_000_000
STOP_MARGIN = 50_000_000
MAX_RESPONSE = 32 * 1024 * 1024


def ledger_directory() -> Path:
    override = os.environ.get('LC_IPR_EPS_LEDGER_DIR')
    if os.environ.get('LC_IPR_TEST_MODE') == '1' and override:
        return Path(override)
    return Path.home() / '.local' / 'state' / 'lc-ipr-risk-screening-free' / 'eps-quota'


class EpsQuotaLedger:
    def __init__(self, directory: Path | None = None, clock=time.time):
        self.directory = directory or ledger_directory()
        self.clock = clock
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.path = self.directory / 'rolling-seven-days.json'

    @contextmanager
    def locked(self):
        with file_lock(self.directory / '.lock'):
            yield

    def read(self):
        now = self.clock()
        try:
            state = load_json(self.path) if self.path.exists() else {'version': 1, 'updated_at': now, 'entries': []}
            updated = float(state['updated_at'])
            blocked = float(state.get('blocked_until', 0))
            if not all(math.isfinite(value) for value in (now, updated, blocked)) or now < 0 or updated < 0 or blocked < 0:
                raise ValueError()
            if state.get('version') != 1 or not isinstance(state['entries'], list) or updated > now + 1:
                raise ValueError()
            for row in state['entries']:
                if not isinstance(row, dict) or isinstance(row['bytes'], bool) or not isinstance(row['bytes'], int) or row['bytes'] < 0 or not math.isfinite(float(row['time'])) or float(row['time']) < 0 or float(row['time']) > now + 1 or not row['id']:
                    raise ValueError()
            state['entries'] = [row for row in state['entries'] if row['time'] > now - WINDOW_SECONDS]
            state['updated_at'] = now
            return state
        except (OSError, ValueError, KeyError, TypeError):
            raise ProviderError('EPS_QUOTA_LEDGER_INVALID', 'access_limited', 'EPS quota history or clock is uncertain; no automatic reset') from None

    def reserve(self, maximum=MAX_RESPONSE):
        if not isinstance(maximum, int) or not 0 < maximum <= MAX_RESPONSE:
            raise ProviderError('EPS_RESPONSE_BOUND_INVALID', 'failed', 'Invalid download reservation')
        with self.locked():
            state = self.read()
            used = sum(row['bytes'] for row in state['entries'])
            if state.get('blocked_until', 0) > self.clock() or used + maximum > FREE_LIMIT - STOP_MARGIN:
                raise ProviderError('FREE_QUOTA_EXHAUSTED', 'access_limited', 'EPS rolling seven-day free allowance reached')
            identifier = secrets.token_hex(16)
            state['entries'].append({'id': identifier, 'time': self.clock(), 'bytes': maximum, 'pending': True})
            atomic_write_json(self.path, state)
            return identifier

    def settle(self, identifier, actual_bytes=None, blocked=False):
        with self.locked():
            state = self.read()
            rows = [row for row in state['entries'] if row['id'] == identifier]
            if len(rows) != 1:
                raise ProviderError('EPS_QUOTA_LEDGER_INVALID', 'access_limited', 'EPS reservation is missing')
            if actual_bytes is not None:
                if not isinstance(actual_bytes, int) or not 0 <= actual_bytes <= rows[0]['bytes']:
                    raise ProviderError('EPS_QUOTA_LEDGER_INVALID', 'access_limited', 'EPS download exceeds reserved bytes')
                rows[0]['bytes'] = actual_bytes
            rows[0]['pending'] = False
            if blocked:
                state['blocked_until'] = self.clock() + WINDOW_SECONDS
            atomic_write_json(self.path, state)


def document_identity(value: str) -> tuple[str, str, str]:
    normalized = re.sub(r'\s+', '', str(value)).upper()
    match = re.fullmatch(r'EP(\d{1,10})(?:(NW|W\d))?([AB][12389])', normalized)
    if not match:
        raise ProviderError('EPS_DOCUMENT_ID_INVALID', 'failed', 'EPS requires an EP publication number including A/B kind code')
    number, correction, kind = match.groups()
    return number.zfill(7), correction or 'NW', kind


class NoRedirect(request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ProviderError('EPS_REDIRECT_REJECTED', 'access_limited', 'EPS unexpectedly redirected the official document request')


def download(document: str, format: str = 'xml', ledger: EpsQuotaLedger | None = None):
    number, correction, kind = document_identity(document)
    if format != 'xml':
        raise ProviderError('EPS_FORMAT_UNSUPPORTED', 'failed', 'Use XML for identity-bound document extraction')
    url = f'{BASE}/patents/EP{number}{correction}{kind}/document.xml'
    assert_test_endpoint(url)
    budget = ledger or EpsQuotaLedger()
    reservation = budget.reserve()
    downloaded = 0
    try:
        req = request.Request(url, headers={'Accept': 'application/xml', 'User-Agent': 'lc-ipr-risk-screening-free/2.4'})
        with request.build_opener(NoRedirect).open(req, timeout=request_timeout(30)) as response:
            declared = response.headers.get('Content-Length')
            if declared and (not declared.isdigit() or int(declared) > MAX_RESPONSE):
                raise ProviderError('EPS_DOCUMENT_TOO_LARGE', 'access_limited', 'Document exceeds the bounded download size')
            chunks = []
            while downloaded < MAX_RESPONSE:
                request_timeout(30)
                chunk = response.read(min(65536, MAX_RESPONSE - downloaded))
                if not chunk:
                    break
                downloaded += len(chunk); chunks.append(chunk)
            if downloaded == MAX_RESPONSE:
                raise ProviderError('EPS_DOCUMENT_TOO_LARGE', 'access_limited', 'Document reached the bounded download size')
            body = b''.join(chunks)
        budget.settle(reservation, downloaded)
        return body, url
    except error.HTTPError as exc:
        budget.settle(reservation, blocked=exc.code in {402, 403, 429})
        if exc.code == 404:
            raise ProviderError('EPS_DOCUMENT_NOT_AVAILABLE', 'access_limited', 'The requested publication XML is not available; this is not a search zero-result') from None
        raise classify_http(exc.code, b'', {}) from None
    except (error.URLError, TimeoutError, OSError):
        budget.settle(reservation)
        raise ProviderError('PROVIDER_NETWORK_ERROR', 'failed', 'EPS document download failed') from None
    except ProviderError:
        budget.settle(reservation)
        raise


def normalize_document(document: str, body: bytes, candidate_id='') -> dict:
    number, _, kind = document_identity(document)
    try:
        root = ElementTree.fromstring(body)
    except ElementTree.ParseError:
        raise ProviderError('RESPONSE_SCHEMA_CHANGED', 'failed', 'EPS document is not valid XML') from None
    if root.tag.rsplit('}', 1)[-1] != 'ep-patent-document':
        raise ProviderError('RESPONSE_SCHEMA_CHANGED', 'failed', 'EPS response is not a patent document')
    if root.attrib.get('country') != 'EP' or root.attrib.get('doc-number', '').zfill(7) != number or root.attrib.get('kind') != kind:
        raise ProviderError('RESPONSE_IDENTITY_MISMATCH', 'failed', 'EPS document identity differs from the requested publication')
    text_of = lambda node: ' '.join(' '.join(node.itertext()).split())
    claims = [{'language': group.attrib.get('lang', root.attrib.get('lang', '')), 'number': node.attrib.get('num') or node.attrib.get('id') or '', 'text': text_of(node)} for group in root.iter() if group.tag.rsplit('}', 1)[-1] == 'claims' for node in group if node.tag.rsplit('}', 1)[-1] == 'claim']
    descriptions = [{'language': node.attrib.get('lang', root.attrib.get('lang', '')), 'text': text_of(node)} for node in root.iter() if node.tag.rsplit('}', 1)[-1] == 'description']
    candidate = {'publication_number': f'EP{number}{kind}', 'jurisdiction': 'EP', 'right_type': 'patent', 'source': PROVIDER,
        'candidate_id': candidate_id, 'claims': claims, 'descriptions': descriptions,
        'publication_date': root.attrib.get('date-publ', ''), 'publication_kind': kind,
        'document_identity_match': True, 'document_sha256': sha256_bytes(body),
        'authoritative_for_final_rating': False, 'authority_scope': 'published_document_only',
        'current_national_effect': 'not_checked', 'official_verification': {'status': 'not_checked'},
        'document_completeness': {'claims_available': bool(claims), 'description_available': bool(descriptions), 'images_available': False},
    }
    return {'candidates': [candidate], 'authority_scope': 'published_document_only', 'authoritative_for_final_rating': False}


def execute(task_dir: Path, query_id: str):
    task_dir = task_dir.resolve()
    _, item, params = load_action(task_dir, PROVIDER, query_id, {'document_retrieval'})
    query = str(item.get('q') or '')
    options = dict(provider=PROVIDER, operation='document_retrieval', query=query, jurisdiction=item.get('jurisdiction', 'EP'), evidence_type='patent', request_params=params, query_id=query_id, source_environment='test_fixture' if os.environ.get('LC_IPR_TEST_MODE') == '1' else 'production', authoritative_for_final_rating=False)
    try:
        document = str(item.get('document') or query)
        body, url = download(document, str(item.get('format') or 'xml'))
        normalized = normalize_document(document, body, str(item.get('candidate_id') or ''))
        normalized['source_url'] = url
        return record_result(task_dir, **options, status='success', normalized=normalized, raw_body=body, raw_suffix='xml', quota={'downloaded_bytes': len(body), 'window_days': 7, 'free_limit_bytes': FREE_LIMIT, 'ledger_scope': 'shared_local_computer'})
    except ProviderError as exc:
        return record_error(task_dir, **options, error_value=exc)


def main():
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument('--task-dir', type=Path, required=True)
    parser.add_argument('--query-id', required=True)
    args = parser.parse_args()
    try:
        run = execute(args.task_dir, args.query_id)
        print(json.dumps({k: run.get(k) for k in ('status', 'error_code', 'query_id')}))
    except (ProviderError, OSError, ValueError) as exc:
        raise SystemExit(str(exc)) from None

if __name__ == '__main__':
    main()
