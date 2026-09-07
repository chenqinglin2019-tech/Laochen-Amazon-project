#!/usr/bin/env python3
"""DATA INPI PI API client, based on the official API PI v1.0 documentation.

https://www.inpi.fr/sites/default/files/Inpi_doc_tech_API_PI_v1.0_0.pdf
No credentials, cookies, or headers are written to disk. TLS verification is on.
Search/notice envelope compatibility remains subject to authenticated live
acceptance; an unfamiliar response is retained as a gap, never an empty search.
"""
from __future__ import annotations
import argparse
import http.cookiejar
import json
import os
import re
from pathlib import Path
from urllib import error, request
from urllib.parse import unquote
from xml.etree import ElementTree
from common import atomic_write_bytes, credential, image_info, load_skill_config, now_iso, sha256_bytes
from provider_utils import ProviderError, assert_test_endpoint, request_timeout, classify_http, enforce_task_limit, record_error, record_result
from provider_plan_v24 import load_action

PROVIDER = 'inpi_api'
BASE = 'https://api-gateway.inpi.fr'
API = '/services/apidiffusion/api'
MAX_BODY = 16 * 1024 * 1024
KINDS = {'patent': 'brevets', 'utility_model': 'brevets', 'trademark_word': 'marques', 'trademark_figurative': 'marques', 'design': 'modeles'}
COLLECTIONS = {'brevets': {'FR', 'EP', 'WO', 'CCP'}, 'marques': {'FR', 'EU', 'WO'}, 'modeles': {'FR', 'WO'}}


class NoRedirect(request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ProviderError('INPI_LOGIN_REQUIRED', 'needs_user_action', 'INPI redirected the API request; confirm API account activation')


class InpiSession:
    def __init__(self, username: str, password: str, timeout=30):
        assert_test_endpoint(BASE)
        if not username or not password:
            raise ProviderError('AUTH_FAILED', 'access_limited', 'INPI_USERNAME and INPI_PASSWORD for the activated PI API account are required')
        self.cookies = http.cookiejar.CookieJar()
        self.opener = request.build_opener(request.HTTPCookieProcessor(self.cookies), NoRedirect)
        self.timeout = timeout
        self.call('/services/uaa/api/authenticate', accept='application/json')
        if not self.xsrf():
            raise ProviderError('RESPONSE_SCHEMA_CHANGED', 'failed', 'INPI authentication bootstrap did not return an XSRF cookie')
        self.call('/auth/login', payload={'username': username, 'password': password, 'rememberMe': False})
        if not any(c.name == 'access_token' and c.value for c in self.cookies):
            raise ProviderError('AUTH_FAILED', 'access_limited', 'INPI API login did not establish an access session')

    def xsrf(self):
        return next((unquote(c.value) for c in self.cookies if c.name == 'XSRF-TOKEN'), '')

    def call(self, path: str, payload=None, accept='application/xml'):
        if not path.startswith('/') or path.startswith('//') or '?' in path or '#' in path:
            raise ProviderError('INPI_ENDPOINT_INVALID', 'failed', 'Invalid documented INPI API path')
        headers = {'Accept': accept, 'User-Agent': 'lc-ipr-risk-screening-free/2.4'}
        if self.xsrf():
            headers['X-XSRF-TOKEN'] = self.xsrf()
        data = None
        if payload is not None:
            data = json.dumps(payload, ensure_ascii=False).encode()
            headers['Content-Type'] = 'application/json'
        req = request.Request(BASE + path, data=data, headers=headers)
        try:
            with self.opener.open(req, timeout=request_timeout(self.timeout)) as response:
                body = response.read(MAX_BODY + 1)
                if len(body) > MAX_BODY:
                    raise ProviderError('INPI_RESPONSE_TOO_LARGE', 'access_limited', 'INPI response exceeds the bounded download size')
                return body
        except error.HTTPError as exc:
            if exc.code == 404:
                raise ProviderError('INPI_RECORD_NOT_AVAILABLE', 'access_limited', 'INPI could not supply this record; this is not a successful search zero') from None
            # Never include an authentication response or request body in errors.
            raise classify_http(exc.code, b'', {}) from None
        except (error.URLError, TimeoutError, OSError):
            raise ProviderError('PROVIDER_NETWORK_ERROR', 'failed', 'INPI API request failed') from None


def search_request(item: dict) -> tuple[str, dict]:
    kind = KINDS.get(item.get('right_type'))
    query = str(item.get('q') or '')
    collections = item.get('collections')
    position, size = item.get('position', 0), item.get('size', 25)
    if kind is None or not query.strip().startswith('[') or not query.strip().endswith(']') or len(query) > 3000:
        raise ProviderError('INPI_QUERY_INVALID', 'failed', 'INPI search requires bounded, explicit bracketed INPI query syntax')
    if not isinstance(collections, list) or not collections or any(c not in COLLECTIONS[kind] for c in collections):
        raise ProviderError('INPI_COLLECTION_INVALID', 'failed', 'INPI collections do not match the selected right type')
    if isinstance(position, bool) or isinstance(size, bool) or not isinstance(position, int) or not isinstance(size, int) or not 0 <= position <= (200 if kind == 'modeles' else 500) or not 1 <= size <= (100 if kind == 'modeles' else 200 if kind == 'marques' else 500):
        raise ProviderError('INPI_PAGINATION_INVALID', 'failed', 'INPI pagination exceeds the documented bounds')
    return f'{API}/{kind}/search', {'collections': collections, 'query': query, 'position': position, 'size': size}


def notice_path(item: dict) -> str:
    kind = KINDS.get(item.get('right_type'))
    number = str(item.get('identifier') or item.get('q') or '').upper()
    if kind is None or not re.fullmatch(r'(?:FR|EP|WO|EU)[A-Z0-9]+(?:-\d{1,3})?', number):
        raise ProviderError('INPI_IDENTIFIER_INVALID', 'failed', 'INPI requires an office-prefixed known identifier')
    return f'{API}/{kind}/notice/{"pubnum/" if kind == "brevets" else ""}{number}'


def xml_tree(body: bytes):
    try:
        root = ElementTree.fromstring(body)
    except ElementTree.ParseError:
        raise ProviderError('RESPONSE_SCHEMA_CHANGED', 'failed', 'INPI returned invalid XML') from None
    if root.tag.rsplit('}', 1)[-1].casefold() in {'html', 'error', 'fault'} or any(node.tag.rsplit('}', 1)[-1].casefold() in {'error', 'fault'} for node in root.iter()):
        raise ProviderError('RESPONSE_SCHEMA_CHANGED', 'failed', 'INPI response is an error or login page')
    return root


def field_values(root, names):
    values = []
    for node in root.iter():
        local = node.tag.rsplit('}', 1)[-1]
        if local in names or node.attrib.get('name') in names:
            value = ' '.join(' '.join(node.itertext()).split())
            if value:
                values.append(value)
    return list(dict.fromkeys(values))


def candidate_from_xml(row, right_type: str, fallback_country='FR') -> dict:
    names = {'patent': {'PUBN', 'publication-number'}, 'utility_model': {'PUBN', 'publication-number'}, 'trademark_word': {'ApplicationNumber'}, 'trademark_figurative': {'ApplicationNumber'}, 'design': {'DesignApplicationNumber'}}[right_type]
    numbers = field_values(row, names)
    if not numbers:
        # Patent notices may use ST.36 publication-reference/document-id.
        numbers = []
        for ref in row.iter():
            if ref.tag.rsplit('}', 1)[-1] == 'publication-reference':
                country = field_values(ref, {'country'}); number = field_values(ref, {'doc-number'}); kind = field_values(ref, {'kind'})
                if country and number:
                    numbers.append(country[0] + number[0] + (kind[0] if kind else ''))
    if len(set(numbers)) != 1:
        raise ProviderError('RESPONSE_SCHEMA_CHANGED', 'failed', 'INPI record lacks one unambiguous application/publication identity')
    number = re.sub(r'\s+', '', numbers[0]).upper()
    prefix = number[:2] if re.match(r'^[A-Z]{2}', number) else fallback_country
    if not re.match(r'^[A-Z]{2}', number):
        number = prefix + number
    if prefix not in {'FR', 'EP', 'WO', 'EU'} or not re.search(r'\d', number):
        raise ProviderError('RESPONSE_SCHEMA_CHANGED', 'failed', 'INPI result identity is malformed')
    owners = field_values(row, {'DENM', 'DENE', 'TINM', 'DEPOSANT', 'DEPOTIT', 'ApplicantName', 'ApplicantNameText', 'HolderName'})
    states = field_values(row, {'MarkCurrentStatusCode', 'PatentCurrentStatusCode', 'DesignCurrentStatusCode', 'CurrentStatusCode'})
    classes = field_values(row, {'IPCR', 'IPRC', 'CPC', 'ClassNumber'})
    candidate = {'jurisdiction': prefix, 'right_type': right_type, 'source': PROVIDER, 'owners': owners, 'legal_status': '; '.join(states), 'classifications': classes, 'title': '; '.join(field_values(row, {'TIT', 'DesignTitle'})), 'material': False,
        'authoritative_for_final_rating': False, 'official_verification': {'status': 'not_checked'}}
    if right_type.startswith('trademark'):
        candidate.update(application_number=number, mark_text='; '.join(field_values(row, {'Mark', 'MarkVerbalElementText'})), nice_classes=classes)
    else:
        candidate['publication_number'] = number
    if right_type == 'design':
        candidate['locarno'] = classes
    return candidate


def normalize_search(body: bytes, right_type: str, position=0, size=25, collections=None) -> dict:
    root = xml_tree(body)
    # Solr XML result/doc is a defined envelope. DTO envelopes are accepted only
    # with an explicit record collection and a numeric declared total.
    solr = [node for node in root.iter() if node.tag.rsplit('}', 1)[-1] == 'result' and 'numFound' in node.attrib]
    if len(solr) == 1:
        raw_total = solr[0].attrib['numFound']; rows = list(solr[0])
        if any(row.tag.rsplit('}', 1)[-1] != 'doc' for row in rows):
            raise ProviderError('RESPONSE_SCHEMA_CHANGED', 'failed', 'INPI Solr result contains an unexpected record type')
    else:
        totals = field_values(root, {'totalResults', 'totalElements', 'numFound', 'total'})
        containers = [node for node in root.iter() if node.tag.rsplit('}', 1)[-1] in {'results', 'notices', 'documents', 'content'}]
        if len(totals) != 1 or len(containers) != 1:
            raise ProviderError('INPI_RESPONSE_CONTRACT_UNVALIDATED', 'access_limited', 'INPI response envelope needs authenticated schema acceptance; no zero-result inferred')
        raw_total = totals[0]; rows = list(containers[0])
    if not str(raw_total).isdigit():
        raise ProviderError('RESPONSE_SCHEMA_CHANGED', 'failed', 'INPI result count is invalid')
    total = int(raw_total)
    fallback = collections[0] if isinstance(collections, list) and len(collections) == 1 else ''
    candidates = [candidate_from_xml(row, right_type, fallback) for row in rows]
    if total < len(candidates) or total > position and not candidates:
        raise ProviderError('RESPONSE_SCHEMA_CHANGED', 'failed', 'INPI result count contradicts the returned records')
    truncated = position > 0 or total > len(candidates)
    return {'candidates': candidates, 'search_metadata': {'total_hits': total, 'retrieved_hits': len(candidates), 'reviewed_hits': None, 'truncated': truncated, 'stop_reason': 'page_limit' if truncated else 'query_exhausted', 'source_updated_at': None, 'schema_valid': True, 'position': position, 'page_size': size}}


def normalize_notice(body: bytes, item: dict, media: list | None = None):
    media = media or []
    root = xml_tree(body)
    requested = re.sub(r'\s+', '', str(item.get('identifier') or item.get('q') or '')).upper()
    candidate = candidate_from_xml(root, item['right_type'], requested[:2])
    actual = str(candidate.get('publication_number') or candidate.get('application_number') or '')
    # Known INPI patent notice lookup omits the kind, but do not ignore the office
    # or number, and never equate designs with separate sequence numbers.
    stem = lambda x: re.sub(r'([A-Z]{2}\d+)[A-Z]\d?$', r'\1', x)
    if stem(actual) != stem(requested):
        raise ProviderError('RESPONSE_IDENTITY_MISMATCH', 'failed', 'INPI notice identity differs from the planned candidate')
    missing = [key for key, value in [('owner', candidate['owners']), ('legal_status', candidate['legal_status']), ('classes', candidate['classifications'])] if not value]
    if item['right_type'] in {'design', 'trademark_figurative'} and not media:
        missing.append('official_media')
    if item['right_type'] == 'design':
        # The documented search count does not establish a complete view manifest.
        missing.append('official_media_manifest')
    # INPI is a French national authority; EP/EU/WO notices do not establish
    # current effects in Germany, the UK, Italy, Spain, Japan, or the US.
    authoritative = candidate['jurisdiction'] == 'FR' and item.get('jurisdiction') == 'FR'
    candidate.update(candidate_id=item.get('candidate_id', ''), authoritative_for_final_rating=authoritative,
        official_verification={'status': 'verified' if authoritative and not missing else 'partial', 'identity_match': True, 'authority': 'INPI', 'source': 'DATA INPI PI API notice', 'url': BASE + notice_path(item), 'checked_at': now_iso(), 'owner': candidate['owners'], 'legal_status': candidate['legal_status'], 'classes': candidate['classifications'], 'media': media, 'reason': ','.join(missing + ([] if authoritative else ['non_national_authority_scope'])), 'method': 'official_free_api'})
    candidate['media'] = media
    return candidate


def fetch_trademark_image(session: InpiSession, task_dir: Path, item: dict) -> list:
    if item.get('right_type') != 'trademark_figurative':
        return []
    number = str(item.get('identifier') or item.get('q') or '').upper()
    # notice_path validates the identifier before it can enter any media path.
    notice_path(item)
    body = session.call(f'{API}/marques/image/{number}/std', accept='image/png')
    digest = sha256_bytes(body)
    target = task_dir / 'raw' / PROVIDER / f'{number}-{digest[:16]}.image'
    atomic_write_bytes(target, body)
    try:
        mime, width, height = image_info(target)
    except ValueError:
        target.unlink(missing_ok=True)
        raise ProviderError('RESPONSE_SCHEMA_CHANGED', 'failed', 'INPI image endpoint did not return a supported image') from None
    return [{'role': 'mark_image', 'path': str(target), 'sha256': digest, 'bytes': len(body), 'mime_type': mime, 'width': width, 'height': height, 'source_url': BASE + f'{API}/marques/image/{number}/std'}]


def execute(task_dir: Path, query_id: str):
    task_dir = task_dir.resolve()
    _, item, params = load_action(task_dir, PROVIDER, query_id, {'search', 'candidate_verification'})
    operation = item['operation']
    environment = 'test_fixture' if os.environ.get('LC_IPR_TEST_MODE') == '1' else 'production'
    options = dict(provider=PROVIDER, operation=operation, query=item.get('q', ''), jurisdiction=item.get('jurisdiction', ''), evidence_type='official_verification' if operation == 'candidate_verification' else 'trademark' if item.get('right_type', '').startswith('trademark') else 'patent', request_params=params, query_id=query_id, source_environment=environment)
    body = b''
    try:
        path, payload = search_request(item) if operation == 'search' else (notice_path(item), None)
        enforce_task_limit(task_dir, PROVIDER, operation, 20 if operation == 'search' else 40)
        config = load_skill_config()
        assert_test_endpoint(BASE)
        session = InpiSession(credential(config, 'inpi_username'), credential(config, 'inpi_password'))
        body = session.call(path, payload)
        if operation == 'search':
            normalized = normalize_search(body, item['right_type'], payload['position'], payload['size'], payload['collections'])
            status = 'success' if normalized['candidates'] else 'no_result'
            authoritative = False
        else:
            # Verify identity before requesting a media resource. Missing media
            # preserves the notice as a partial official record.
            normalized = normalize_notice(body, item)
            try:
                media = fetch_trademark_image(session, task_dir, item)
                normalized = normalize_notice(body, item, media)
            except ProviderError as media_error:
                normalized['official_verification']['reason'] += ',' + media_error.code
            status = 'success' if normalized['official_verification']['status'] == 'verified' else 'access_limited'
            authoritative = normalized['authoritative_for_final_rating']
        normalized['source_environment'] = environment
        if environment != 'production':
            authoritative = False
            for candidate in normalized.get('candidates', [normalized]):
                candidate['authoritative_for_final_rating'] = False
                candidate['source_environment'] = environment
                if isinstance(candidate.get('official_verification'), dict):
                    candidate['official_verification']['status'] = 'not_checked'
            if operation == 'candidate_verification':
                status = 'access_limited'
        return record_result(task_dir, **options, status=status, normalized=normalized, raw_body=body, raw_suffix='xml', authoritative_for_final_rating=authoritative, error_code='OFFICIAL_VERIFICATION_INCOMPLETE' if status == 'access_limited' else '')
    except ProviderError as exc:
        if body:
            return record_result(task_dir, **options, status=exc.source_status, normalized=None, raw_body=body, raw_suffix='xml', error_code=exc.code, detail=exc.detail, authoritative_for_final_rating=False)
        return record_error(task_dir, **options, error_value=exc, authoritative_for_final_rating=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument('--task-dir', type=Path, required=True)
    parser.add_argument('--query-id', required=True)
    args = parser.parse_args()
    try:
        run = execute(args.task_dir, args.query_id)
        print(json.dumps({key: run.get(key) for key in ('status', 'error_code', 'query_id')}))
    except (ProviderError, OSError, ValueError) as exc:
        raise SystemExit(str(exc)) from None

if __name__ == '__main__':
    main()
