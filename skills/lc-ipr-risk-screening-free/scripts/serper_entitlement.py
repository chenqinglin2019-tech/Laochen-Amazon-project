#!/usr/bin/env python3
"""Validate retained, redacted official account pages without a metered probe.

The collector must observe the account's API key in the authenticated page and
replace it in memory with its fingerprint. A configured key alone is not proof
of the browser account. Unknown labels, missing prices or conflicting balances
fail closed. This parser is not a claim of live account-page acceptance.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlsplit

from common import atomic_write_json, credential, load_skill_config, sha256_json
from free_search_budget import _root
from provider_utils import ProviderError

SCHEMA = 'SERPER-FREE-ENTITLEMENT/1.0'
CAPTURE_SCHEMA = 'SERPER-ACCOUNT-CAPTURE/1.0'
MAX_AGE_MINUTES = 30
OFFICIAL_BASE = 'https://google.serper.dev'


def fingerprint(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _reject(detail: str):
    raise ProviderError('FREE_ACCOUNT_UNVERIFIED', 'access_limited', detail)


def _time(value):
    try:
        result = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        if result.tzinfo is None:
            raise ValueError('timezone required')
        return result
    except (ValueError, TypeError):
        _reject('Account evidence needs an explicit timezone and capture time')


def _one(text: str, label: str, value_pattern: str, *, required=True):
    values = re.findall(r'(?im)^[ \t]*(?:' + label + r')[ \t]*[:=][ \t]*([^\r\n]*)$', text)
    if any(not re.fullmatch(value_pattern, v.strip(), re.I) for v in values):
        _reject('An official account field has an unknown value: ' + label)
    values = {v.casefold().replace(',', '').strip() for v in values}
    if len(values) != 1:
        if not values and not required:
            return None
        _reject('An official account field is missing or conflicting: ' + label)
    return values.pop()


def validate_capture(capture: dict, key: str, *, now=None) -> dict:
    now = now or datetime.now(timezone.utc)
    if (not key or not isinstance(capture, dict) or capture.get('schema') != CAPTURE_SCHEMA
        or capture.get('collector') != 'cdp-serper-account-v1'
        or capture.get('source_environment') not in {'production', 'test_fixture'}):
        _reject('No supported official account-page capture is available')
    if capture['source_environment'] == 'test_fixture' and os.environ.get('LC_IPR_TEST_MODE') != '1':
        _reject('Fixture account evidence cannot authorize production requests')
    captured = _time(capture.get('captured_at'))
    if captured > now + timedelta(seconds=60) or now >= captured + timedelta(minutes=MAX_AGE_MINUTES):
        _reject('Account-page evidence is stale or has a future capture time')
    cred = capture.get('credential_fingerprint')
    account = capture.get('account_fingerprint')
    if cred != fingerprint(key) or not isinstance(account, str) or not re.fullmatch('[0-9a-f]{64}', account):
        _reject('The observed account credential does not match the configured credential')
    pages = capture.get('pages')
    if not isinstance(pages, list) or not 1 <= len(pages) <= 8:
        _reject('Retained official account pages are missing')
    texts = []
    refs = []
    for page in pages:
        if not isinstance(page, dict):
            _reject('Invalid account-page capture')
        url = str(page.get('url') or '')
        try:
            parsed = urlsplit(url)
            official = (parsed.scheme == 'https' and parsed.hostname in {'serper.dev', 'www.serper.dev'}
                        and parsed.port in (None, 443) and not parsed.username and not parsed.password
                        and not parsed.query and not parsed.fragment)
        except ValueError:
            official = False
        text = page.get('text')
        if (not official or not isinstance(text, str) or not 1 <= len(text.encode()) <= 500_000
            or fingerprint(text) != page.get('sha256') or key in text
            or re.search(r'[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}', text, re.I)):
            _reject('Account proof requires hashed, redacted original text from an official HTTPS page')
        page_time = _time(page.get('captured_at'))
        if not captured - timedelta(minutes=5) <= page_time <= captured:
            _reject('Account pages were not captured in the same bounded session')
        texts.append(text)
        refs.append({'url': url, 'captured_at': page['captured_at'], 'sha256': page['sha256']})
    text = '\n'.join(texts)
    if (set(re.findall(r'\[credential-sha256:([0-9a-f]{64})\]', text)) != {cred}
        or set(re.findall(r'\[account-sha256:([0-9a-f]{64})\]', text)) != {account}):
        _reject('Original page text does not bind one observed account and credential')
    free = int(_one(text, r'Free credits(?: remaining)?|Free credit balance', r'[0-9][0-9,]*'))
    paid = int(_one(text, r'Paid credits(?: remaining)?|Paid credit balance', r'[0-9][0-9,]*'))
    recharge = _one(text, r'Auto(?:matic)?[ -]recharge', r'Disabled|Off|False|Enabled|On|True')
    if paid != 0 or recharge not in {'disabled', 'off', 'false'}:
        raise ProviderError('PAID_QUOTA_USAGE_DETECTED', 'access_limited', 'Paid credits or automatic recharge are enabled on this account')
    if free <= 0:
        raise ProviderError('FREE_QUOTA_EXHAUSTED', 'access_limited', 'The retained account page shows no free credit balance')
    expiry = captured + timedelta(minutes=MAX_AGE_MINUTES)
    raw_expiry = _one(text, r'Free credits? expir(?:y|es|ation)', r'\d{4}-\d{2}-\d{2}T[0-9:+.\-]+Z?', required=False)
    if raw_expiry:
        expiry = min(expiry, _time(raw_expiry.upper().replace('T', 'T')))
    if now >= expiry:
        _reject('The observed free entitlement has expired')
    costs = {}
    for operation, label in [('patents', 'Patents'), ('search', 'Search'), ('images', 'Images')]:
        cost = _one(text, label + r' credits per request', r'[0-9]+', required=False)
        if cost is not None:
            if not 1 <= int(cost) <= 100:
                _reject('The official operation credit bound is invalid')
            costs[operation] = int(cost)
    return {'schema': SCHEMA, 'credential_fingerprint': cred, 'account_fingerprint': account,
            'captured_at': capture['captured_at'], 'expires_at': expiry.isoformat(),
            'free_credit_units': free, 'paid_credit_units': paid, 'automatic_recharge': False,
            'operation_credit_units': costs, 'source_environment': capture['source_environment'],
            'page_evidence': refs, 'capture_sha256': sha256_json(capture)}


def default_path(key: str) -> Path:
    return _root(OFFICIAL_BASE) / ('serper-entitlement-' + fingerprint(key) + '.json')


def create_entitlement(capture_path: Path, output: Path, key: str, *, now=None) -> dict:
    raw = capture_path.read_bytes()
    if len(raw) > 4_000_000 or key.encode() in raw:
        _reject('Capture is oversized or contains an unredacted credential')
    proof = validate_capture(json.loads(raw), key, now=now)
    output.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if output.is_symlink():
        _reject('Linked entitlement output is not supported')
    retained = output.with_name(output.stem + '.capture.json')
    if retained.is_symlink():
        _reject('Linked capture output is not supported')
    atomic_write_json(retained, json.loads(raw)); retained.chmod(0o600)
    proof['capture'] = {'path': retained.name, 'sha256': hashlib.sha256(retained.read_bytes()).hexdigest(), 'bytes': retained.stat().st_size}
    atomic_write_json(output, proof); output.chmod(0o600)
    return proof


def load_entitlement(key: str, operation: str, *, path: Path | None = None, now=None) -> dict:
    try:
        path = path or default_path(key)
        if path.is_symlink() or path.stat().st_size > 100_000:
            _reject('Invalid entitlement file')
        proof = json.loads(path.read_text())
        ref = proof.get('capture', {})
        name = ref.get('path')
        if not isinstance(name, str) or Path(name).name != name:
            _reject('Entitlement has no bounded retained original capture')
        source = path.parent / name
        if source.is_symlink() or source.stat().st_size > 4_000_000:
            _reject('Invalid retained account capture')
        raw = source.read_bytes()
        if len(raw) != ref.get('bytes') or hashlib.sha256(raw).hexdigest() != ref.get('sha256'):
            _reject('Retained account capture has changed')
        recomputed = validate_capture(json.loads(raw), key, now=now)
        if {k: v for k, v in proof.items() if k != 'capture'} != recomputed:
            _reject('Entitlement facts do not match the retained original pages')
        if operation not in recomputed['operation_credit_units']:
            _reject('No retained official per-request credit bound exists for this operation')
        return {**recomputed, 'proof_sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
    except (OSError, ValueError, TypeError, KeyError) as exc:
        _reject('A valid retained Serper account proof is required before a metered request')


def main():
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--capture', type=Path)
    group.add_argument('--verify', type=Path)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--operation', choices=['patents', 'search', 'images'], default='patents')
    args = parser.parse_args()
    try:
        key = credential(load_skill_config(), 'serper_api_key')
        if not key:
            _reject('SERPER_API_KEY is missing; no account or metered request was sent')
        if args.capture:
            proof = create_entitlement(args.capture, args.output or default_path(key), key)
        else:
            proof = load_entitlement(key, args.operation, path=args.verify)
        print(json.dumps({'status': 'verified', 'expires_at': proof['expires_at'],
                          'operation_credit_units': proof['operation_credit_units']}, ensure_ascii=False))
    except (ProviderError, OSError, ValueError) as exc:
        raise SystemExit(str(exc)) from None


if __name__ == '__main__':
    main()
