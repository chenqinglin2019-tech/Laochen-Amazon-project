#!/usr/bin/env python3
"""Free-plan-only Google Lens discovery using already-public product images.

https://serpapi.com/google-lens-api . No image upload endpoint is used.
Shares the Account API guard, per-task lock, stop signals, and total search
budget with the existing SerpApi Google Patents client.
"""
from __future__ import annotations
import argparse
import json
import os
import re
from pathlib import Path
from urllib.parse import urlencode, urlparse
from common import ensure_object, load_json, sha256_json
from provider_utils import ProviderError, http_json, record_result
from free_search_budget import attempt_context, reserve_search
from provider_plan_v24 import load_action
from serpapi_patents_client import budget_lock, consumed_queries, free_account_snapshot, persisted_quota_block_reason, settings

PROVIDER = 'serpapi_google_lens'
OPERATION = 'image_search'


def public_product_image(task: dict, item: dict) -> str:
    value = str(item.get('image_url') or item.get('q') or '')
    parsed = urlparse(value)
    host = (parsed.hostname or '').lower()
    if parsed.scheme != 'https' or parsed.username or parsed.password or parsed.port not in (None, 443) or parsed.fragment or parsed.query or not (host == 'media-amazon.com' or host.endswith('.media-amazon.com')):
        raise ProviderError('LENS_PUBLIC_IMAGE_REQUIRED', 'failed', 'Lens accepts a public Amazon product image URL; local images are never uploaded')
    images = task.get('images', [])
    if not any(isinstance(row, dict) and row.get('source_url') == value and row.get('sha256') for row in images):
        raise ProviderError('LENS_IMAGE_NOT_BOUND_TO_PRODUCT', 'failed', 'Lens image URL must match a captured product image with a digest')
    return value


def search(base: str, key: str, timeout: int, image_url: str, item: dict):
    search_type = str(item.get('type') or 'all')
    language = str(item.get('hl') or 'en')
    country = str(item.get('country') or 'us').lower()
    if search_type not in {'all', 'visual_matches', 'exact_matches'} or not re.fullmatch(r'[a-z]{2}(?:-[A-Z]{2})?', language) or country not in {'us', 'gb', 'fr', 'de', 'it', 'es', 'jp'}:
        raise ProviderError('LENS_QUERY_INVALID', 'failed', 'Lens type, language, or country is unsupported')
    params = {'engine': 'google_lens', 'api_key': key, 'url': image_url, 'type': search_type, 'hl': language, 'country': country, 'output': 'json'}
    return http_json(f'{base}/search.json?{urlencode(params)}', timeout=timeout, retries=0)


def normalize(payload: dict) -> dict:
    metadata = payload.get('search_metadata')
    if not isinstance(metadata, dict) or metadata.get('status') != 'Success':
        if payload.get('error'):
            text = str(payload['error']).casefold()
            if any(x in text for x in ('quota', 'limit', 'searches left')):
                raise ProviderError('FREE_QUOTA_EXHAUSTED', 'access_limited', 'Lens Free-plan search allowance is exhausted')
        raise ProviderError('RESPONSE_SCHEMA_CHANGED', 'failed', 'Lens did not return successful search metadata')
    collections = [name for name in ('visual_matches', 'exact_matches') if name in payload]
    if not collections or payload.get('error'):
        raise ProviderError('RESPONSE_SCHEMA_CHANGED', 'failed', 'Lens response does not contain an explicit matching-results collection')
    candidates = []
    for name in collections:
        if not isinstance(payload[name], list):
            raise ProviderError('RESPONSE_SCHEMA_CHANGED', 'failed', 'Lens matches collection is not an array')
        for row in payload[name]:
            if not isinstance(row, dict) or not isinstance(row.get('link'), str) or urlparse(row['link']).scheme not in {'http', 'https'}:
                raise ProviderError('RESPONSE_SCHEMA_CHANGED', 'failed', 'Lens match lacks a source page URL')
            candidates.append({'title': str(row.get('title') or ''), 'url': row['link'], 'source': PROVIDER, 'source_name': str(row.get('source') or ''),
                'image_url': str(row.get('image') or row.get('thumbnail') or ''), 'match_type': name,
                'right_type': 'copyright', 'role': 'discovery_only', 'material': False,
                'authoritative_for_final_rating': False, 'official_verification': {'status': 'not_checked'}})
    return {'candidates': candidates, 'role': 'discovery_only', 'authoritative_for_final_rating': False,
        'search_metadata': {'total_hits': None, 'retrieved_hits': len(candidates), 'reviewed_hits': None, 'truncated': True, 'stop_reason': 'ranked_search_total_unknown', 'source_updated_at': None, 'schema_valid': True}}


def execute(task_dir: Path, query_id: str, *, attempt_id='initial', retry_reason=''):
    attempt = attempt_context(attempt_id, retry_reason)
    task_dir = task_dir.resolve()
    with budget_lock(task_dir):
        task, item, params = load_action(task_dir, PROVIDER, query_id, {OPERATION})
        options = dict(provider=PROVIDER, operation=OPERATION, query=item.get('q', ''), jurisdiction=item.get('jurisdiction', ''), evidence_type='copyright', request_params=params, query_id=query_id, mandatory=False,
            source_environment='test_fixture' if os.environ.get('LC_IPR_TEST_MODE') == '1' else 'commercial_freemium_free_plan', authoritative_for_final_rating=False)
        attempted = False; account = dict(attempt); body = b''
        try:
            selection = task.get('serpapi_free_enhancement') or {}
            if selection.get('enabled') is not True:
                raise ProviderError('SERPAPI_NOT_ENABLED', 'failed', 'SerpApi discovery was not selected for this task')
            image_url = public_product_image(task, item)
            if any(item.get(k) != expected for k, expected in {'required': False, 'required_for': 'discovery_only', 'requirement_ids': [], 'role': 'discovery_only', 'authoritative_for_final_rating': False}.items()):
                raise ProviderError('DISCOVERY_ONLY_CONTRACT_INVALID', 'failed', 'Lens cannot satisfy formal or low-risk requirements')
            evidence = ensure_object(load_json(task_dir / 'evidence.json'), 'evidence.json')
            maximum = min(int(selection.get('max_queries_per_task', 3)), 3)
            if consumed_queries(evidence) >= maximum:
                raise ProviderError('SERPAPI_TASK_QUERY_LIMIT_REACHED', 'access_limited', 'Combined Lens and Patents task search budget is exhausted')
            if persisted_quota_block_reason(evidence) and attempt_id == 'initial':
                raise ProviderError('FREE_QUOTA_EXHAUSTED', 'access_limited', 'A SerpApi Free-plan stop is already recorded')
            config, base, key = settings()
            if not key:
                raise ProviderError('AUTH_FAILED', 'access_limited', 'SERPAPI_API_KEY is missing')
            timeout = int(config.get('http', {}).get('timeout_seconds', 30))
            account.update(free_account_snapshot(base, key, timeout))
            account.update(reserve_search('serpapi', key, base, remaining=account['plan_searches_left'], task_dir=task_dir,
                query_id=query_id, renewal_date=account.get('plan_renewal_date', ''), plan_entry_sha256=sha256_json(item), max_queries_per_task=maximum, **attempt))
            attempted = True
            payload, _, body = search(base, key, timeout, image_url, item)
            normalized = normalize(payload)
            return record_result(task_dir, **options, status='success' if normalized['candidates'] else 'no_result', normalized=normalized, raw_body=body, raw_suffix='json', quota={**account, 'network_request_attempted': True})
        except ProviderError as exc:
            return record_result(task_dir, **options, status=exc.source_status, normalized=None, raw_body=body, raw_suffix='json', error_code=exc.code, detail=exc.detail, quota={**account, 'network_request_attempted': attempted})


def main():
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument('--task-dir', type=Path, required=True)
    parser.add_argument('--query-id', required=True)
    parser.add_argument('--attempt-id', default='initial')
    parser.add_argument('--retry-reason', default='')
    args = parser.parse_args()
    try:
        run = execute(args.task_dir, args.query_id, attempt_id=args.attempt_id, retry_reason=args.retry_reason)
        print(json.dumps({key: run.get(key) for key in ('status', 'error_code', 'query_id')}))
    except (ProviderError, OSError, ValueError) as exc:
        raise SystemExit(str(exc)) from None

if __name__ == '__main__':
    main()
