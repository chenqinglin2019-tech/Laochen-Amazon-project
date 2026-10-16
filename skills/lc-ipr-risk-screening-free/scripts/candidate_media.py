"""Retain representative images from exact saved candidate receipts, without new source runs."""
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
from collections import deque
from io import BytesIO
import argparse
import http.client
import ipaddress
import json
from pathlib import Path
import socket
import ssl
import time
import threading
from urllib.parse import urlsplit, urljoin, parse_qsl
import warnings

from common import atomic_write_bytes, atomic_write_json, load_json, now_iso, sha256_bytes, sha256_file, sha256_json
from execution_efficiency import policy

IMAGE_FIELDS = {'image', 'image_url', 'imageUrl', 'thumbnail', 'thumbnail_url', 'thumbnailUrl', 'original', 'full'}
# Only used to name the cause of a refusal. A transparent proxy in "fake-IP" mode (Clash, Surge, ...)
# answers every name from the benchmarking block, which the public-address rule below refuses.
FAKE_IP_NETWORK = ipaddress.ip_network('198.18.0.0/15')
SHARED_ADDRESS_NETWORK = ipaddress.ip_network('100.64.0.0/10')


def address_class(address):
    """Short, non-secret name of why a resolved address is not a public one."""
    ip = ipaddress.ip_address(address)
    if ip.version == 4 and ip in FAKE_IP_NETWORK:
        return 'benchmarking_198.18.0.0/15'
    if ip.is_loopback:
        return 'loopback'
    if ip.is_link_local:
        return 'link_local'
    if ip.version == 4 and ip in SHARED_ADDRESS_NETWORK:
        return 'shared_100.64.0.0/10'
    if ip.is_private:
        return 'private'
    return 'not_global'


_FAKE_IP_MODE = {}
_FAKE_IP_LOCK = threading.Lock()
# r9: an IPv6 placeholder block some fake-IP proxies hand out beside the IPv4 one (unique local addresses)
UNIQUE_LOCAL_V6 = ipaddress.ip_network('fc00::/7')


def fake_ip_mode_confirmed():
    """True when this machine's resolver answers the fixed probe names from 198.18.0.0/15 (a local fake-IP proxy).

    Owner decision F3 (r5d4): only then, and only for that block, a public file may be fetched through the proxy's
    placeholder address; every other non-public address is still refused. Probed once per process, DNS only."""
    with _FAKE_IP_LOCK:
        if 'value' not in _FAKE_IP_MODE:
            try:
                from network_diagnostic import diagnose
                _FAKE_IP_MODE['value'] = diagnose(timeout=3.0).get('status') == 'fake_ip_detected'
            except Exception:
                _FAKE_IP_MODE['value'] = False
        return _FAKE_IP_MODE['value']


def download_proxy(hostname):
    """(host, port, Proxy-Authorization value or None) of the user's own HTTP(S) proxy for this host, or None.

    r9 (owner decision 2026-10-16): with only a system proxy (or HTTPS_PROXY) and no TUN, every public download went
    straight to Google and failed from mainland China while the API clients - urllib, which reads the same settings -
    worked. Downloads now go through that proxy with HTTP CONNECT; the address rule above still runs on the local
    answer and TLS still verifies the real host name. With a confirmed fake-IP proxy nothing changes (the TUN already
    carries the connection). SOCKS-only and PAC-only settings are not read (urllib does not read them either)."""
    if fake_ip_mode_confirmed():
        return None
    import urllib.request
    try:
        proxies = urllib.request.getproxies()
    except Exception:
        return None
    value = proxies.get('https') or proxies.get('http')
    if not value:
        return None
    try:
        if urllib.request.proxy_bypass(hostname):
            return None
    except Exception:
        pass
    parsed = urlsplit(value if '://' in value else 'http://' + value)
    if parsed.scheme not in ('http', 'https') or not parsed.hostname:
        return None
    authorization = None
    if parsed.username:
        import base64
        from urllib.parse import unquote
        token = (unquote(parsed.username) + ':' + unquote(parsed.password or '')).encode('utf-8')
        authorization = 'Basic ' + base64.b64encode(token).decode('ascii')
    return parsed.hostname, parsed.port or (443 if parsed.scheme == 'https' else 80), authorization


def _ordered(addresses):
    """IPv4 answers first, then IPv6, each in the resolver's sorted order (a home network without working IPv6 is
    common; the old single string-sorted pick could start with an unroutable IPv6 address and never try another)."""
    return ([value for value in addresses if ':' not in value] + [value for value in addresses if ':' in value])


class ValidatedAddress(str):
    """The first validated address; ``alternates`` holds the other validated ones in connection order (r9)."""
    alternates = ()


def public_address(url, *, timeout=None):
    """(parsed url, first validated address). r9: the address carries the other validated addresses, which
    PublicConnection tries in turn when one does not answer; callers are unchanged."""
    value, addresses = public_addresses(url, timeout=timeout)
    first = ValidatedAddress(addresses[0])
    first.alternates = tuple(addresses[1:])
    return value, first


def public_addresses(url, *, timeout=None):
    """(parsed url, validated addresses in connection order). r9: a connection tries each of them in turn."""
    value = urlsplit(url)
    if (value.scheme != 'https' or not value.hostname or value.username or value.password
            or value.port not in (None, 443) or value.fragment
            or any(k.lower() in {'api_key', 'apikey', 'token', 'access_token', 'authorization'} for k, _ in parse_qsl(value.query))):
        raise ValueError('MEDIA_PUBLIC_HTTPS_REQUIRED')
    if timeout is None:
        resolved = socket.getaddrinfo(value.hostname, 443, type=socket.SOCK_STREAM)
    else:
        # Resolver APIs have no socket timeout. A daemon cannot hold process
        # shutdown or the bounded download worker after this URL's deadline.
        done, result = threading.Event(), []
        def resolve():
            try:
                result.append(socket.getaddrinfo(value.hostname, 443, type=socket.SOCK_STREAM))
            except OSError as exc:
                result.append(exc)
            finally:
                done.set()
        threading.Thread(target=resolve, daemon=True).start()
        if not done.wait(max(0, timeout)):
            raise TimeoutError('MEDIA_DNS_TIMEOUT')
        if isinstance(result[0], OSError):
            raise result[0]
        resolved = result[0]
    addresses = sorted({row[4][0] for row in resolved})
    if not addresses:
        raise ValueError('MEDIA_PUBLIC_ADDRESS_REQUIRED')
    bad = [addr for addr in addresses if not ipaddress.ip_address(addr).is_global]
    fake = [addr for addr in bad if ipaddress.ip_address(addr).version == 4 and ipaddress.ip_address(addr) in FAKE_IP_NETWORK]
    placeholders6 = [addr for addr in bad if ipaddress.ip_address(addr).version == 6
                     and ipaddress.ip_address(addr) in UNIQUE_LOCAL_V6]
    if fake and set(bad) <= set(fake) | set(placeholders6) and fake_ip_mode_confirmed():
        # F3: a confirmed local fake-IP proxy answers every name from this block; the connection goes to the proxy
        # and TLS still verifies the real host name. Public answers, when present, are preferred. r9: an IPv6
        # unique-local placeholder beside the 198.18 answer is never connected to; the 198.18 answer is used.
        good = [addr for addr in addresses if addr not in bad]
        return value, _ordered(good or fake)
    if bad:
        raise ValueError('MEDIA_PUBLIC_ADDRESS_REQUIRED:' + address_class(bad[0]))
    return value, _ordered(addresses)


ADDRESS_ATTEMPT_SECONDS = 8.0


class PublicConnection(http.client.HTTPSConnection):
    def __init__(self, hostname, address, timeout):
        super().__init__(hostname, timeout=timeout, context=ssl.create_default_context())
        self.addresses = ([str(address), *getattr(address, 'alternates', ())] if isinstance(address, str)
                          else [str(value) for value in address])
        self.address = self.addresses[0]
        self.stop = time.monotonic() + timeout

    def _direct(self):
        # Connect to a validated address; DNS cannot change the destination between checks. r9: the next validated
        # address is tried when one does not answer (IPv4 first).
        last = None
        for index, address in enumerate(self.addresses):
            left = self.stop - time.monotonic()
            if left <= 0:
                break
            limit = left if index == len(self.addresses) - 1 else min(left, ADDRESS_ATTEMPT_SECONDS)
            try:
                self.address = address
                return socket.create_connection((address, 443), min(self.timeout, limit))
            except OSError as exc:
                last = exc
        raise last or TimeoutError('MEDIA_TIMEOUT')

    def _through_proxy(self, proxy):
        """r9: an HTTP CONNECT tunnel through the user's own proxy to this host's port 443."""
        host, port, authorization = proxy
        raw = socket.create_connection((host, port), self.timeout)
        try:
            raw.settimeout(max(0.1, self.stop - time.monotonic()))
            request = 'CONNECT %s:443 HTTP/1.1\r\nHost: %s:443\r\n' % (self.host, self.host)
            if authorization:
                request += 'Proxy-Authorization: %s\r\n' % authorization
            raw.sendall((request + '\r\n').encode('ascii'))
            reply = b''
            while b'\r\n\r\n' not in reply:
                chunk = raw.recv(4096)
                if not chunk or len(reply) > 65536:
                    raise OSError('MEDIA_PROXY_TUNNEL_FAILED')
                reply += chunk
            status = reply.split(b'\r\n', 1)[0].split()
            if len(status) < 2 or status[1] != b'200':
                raise OSError('MEDIA_PROXY_TUNNEL_REFUSED:' + (status[1].decode('ascii', 'replace') if len(status) > 1 else '?'))
            return raw
        except BaseException:
            raw.close()
            raise

    def connect(self):
        proxy = download_proxy(self.host)
        raw = self._through_proxy(proxy) if proxy else self._direct()
        try:
            left = self.stop - time.monotonic()
            if left <= 0:
                raise TimeoutError('MEDIA_TIMEOUT')
            raw.settimeout(left)
            self.sock = self._context.wrap_socket(raw, server_hostname=self.host)
        except BaseException:
            raw.close()
            raise


def decode_image(data):
    from PIL import Image
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('error', Image.DecompressionBombWarning)
            with Image.open(BytesIO(data)) as image:
                kind, size = image.format, image.size
                image.verify()
            with Image.open(BytesIO(data)) as image:
                image.load()
    except Exception as exc:
        raise ValueError('MEDIA_IMAGE_DECODE_' + type(exc).__name__) from exc
    suffix = {'PNG': '.png', 'JPEG': '.jpg', 'WEBP': '.webp'}.get(kind)
    if suffix is None:
        raise ValueError('MEDIA_NATIVE_IMAGE_FORMAT_UNSUPPORTED')
    return suffix, size


class MediaBudgetExhausted(ValueError):
    def __init__(self, request_started=False):
        super().__init__('MEDIA_EXECUTION_BUDGET_EXHAUSTED')
        self.request_started = request_started


class MediaDownloadError(ValueError):
    def __init__(self, cause, request_started):
        super().__init__(type(cause).__name__ + ':' + str(cause))
        self.request_started = request_started


def download(url, *, timeout=15, max_bytes=8388608, deadline=None, revised_budget=False):
    state = {'request_started': False, 'budget_stop': time.monotonic() +
             max(0, deadline - time.time()) if deadline is not None else float('inf'),
             'url_stop': time.monotonic() + timeout}
    try:
        return _download(url, timeout=timeout, max_bytes=max_bytes, deadline=deadline,
                         state=state if revised_budget else None)
    except (OSError, ValueError, http.client.HTTPException) as exc:
        if not revised_budget:
            raise
        if (isinstance(exc, MediaBudgetExhausted) or
                isinstance(exc, (OSError, http.client.HTTPException)) and state['budget_stop'] <= state['url_stop']
                and time.monotonic() >= state['budget_stop']):
            raise MediaBudgetExhausted(state['request_started']) from None
        raise MediaDownloadError(exc, state['request_started']) from exc


def _download(url, *, timeout, max_bytes, deadline, state=None):
    stop = min(time.monotonic() + timeout,
               time.monotonic() + max(0, deadline - time.time()) if deadline else float('inf'))
    if state is not None:
        stop = min(state['url_stop'], state['budget_stop'])
    def check_deadline():
        if stop <= time.monotonic():
            if state is not None and state['budget_stop'] <= state['url_stop']:
                raise MediaBudgetExhausted(state['request_started'])
            raise TimeoutError('MEDIA_TIMEOUT')
    current = url
    for _ in range(4):
        check_deadline()
        parsed, address = public_address(current, timeout=stop - time.monotonic())
        remaining = stop - time.monotonic()
        check_deadline()
        connection = PublicConnection(parsed.hostname, address, remaining)
        cutoff = None
        try:
            check_deadline()
            if state is not None:
                # request() may send bytes before raising; never claim that an
                # interrupted call was definitely not submitted.
                state['request_started'] = True
            connection.request('GET', parsed.path + ('?' + parsed.query if parsed.query else '') or '/',
                               headers={'Accept': 'image/*', 'User-Agent': 'IPR-Public-Media/1.0'})
            check_deadline()
            if connection.sock:
                connection.sock.settimeout(stop - time.monotonic())
                active_socket = connection.sock
                def close_at_deadline(sock=active_socket):
                    try:
                        sock.shutdown(socket.SHUT_RDWR)
                    except OSError:
                        pass
                # Socket timeouts alone reset on each small incoming read.
                # This wall deadline also bounds slowly streamed HTTP headers.
                cutoff = threading.Timer(max(0, stop - time.monotonic()), close_at_deadline)
                cutoff.daemon = True
                cutoff.start()
            response = connection.getresponse()
            if state is not None:
                check_deadline()
            if response.status in (301, 302, 303, 307, 308):
                location = response.getheader('Location')
                if not location:
                    raise ValueError('MEDIA_REDIRECT_LOCATION_REQUIRED')
                current = urljoin(current, location)
                continue
            if response.status != 200:
                raise ValueError('MEDIA_HTTP_' + str(response.status))
            size = response.getheader('Content-Length')
            if size is not None and (not size.isdigit() or int(size) > max_bytes):
                raise ValueError('MEDIA_SIZE_LIMIT')
            chunks, total = [], 0
            while True:
                remaining = stop - time.monotonic()
                check_deadline()
                if connection.sock:
                    connection.sock.settimeout(remaining)
                chunk = response.read1(min(65536, max_bytes + 1 - total))
                if state is not None:
                    check_deadline()
                if not chunk:
                    break
                chunks.append(chunk)
                total += len(chunk)
                if total > max_bytes:
                    raise ValueError('MEDIA_SIZE_LIMIT')
            body = b''.join(chunks)
            suffix, dimensions = decode_image(body)
            return body, suffix, dimensions, current
        finally:
            if cutoff is not None:
                cutoff.cancel()
            connection.close()
    raise ValueError('MEDIA_REDIRECT_LIMIT')


def candidate_urls(task_dir, candidate, evidence, *, receipt_index=None):
    from source_result_processing import (_retained_run, _json_result_values,
        _run_entries, _candidate_rows, _unbound_cua_rows)
    urls = []
    for ref in candidate.get('sources', []):
        runs = [r for r in evidence.get('source_runs', []) if r.get('run_id') == ref.get('source_run_id')]
        if len(runs) != 1:
            continue
        run = runs[0]
        failed_material = run.get('status') == 'failed' and run.get('submission_state') == 'submitted'
        if run.get('status') != 'success' and not failed_material:
            continue
        key = (run['run_id'], run.get('payload_digest'))
        cached = receipt_index.get(key) if receipt_index is not None else None
        if cached is None:
            index, body = _retained_run(task_dir, run, evidence)
            if failed_material and _unbound_cua_rows(body, str(run.get('provider') or '')):
                raise ValueError('RESULT_PROCESSING_QUERY_BINDING_REQUIRED')
            values = _json_result_values(body, run['provider']) or []
            rows_by_hash, rows_by_position = {}, {}
            for row in index['rows']:
                rows_by_hash.setdefault(row.get('raw_sha256'), []).append(row)
                rows_by_position.setdefault(row['position'], []).append(row)
            cached = (rows_by_hash, rows_by_position,
                      {(collection, position): value for collection, position, value in values})
            if receipt_index is not None:
                receipt_index[key] = cached
        rows_by_hash, rows_by_position, originals_by_position = cached
        if not originals_by_position:
            # A receipt without JSON result cards (for example an EPO OPS XML response) can never supply an
            # image link, so its position/hash bindings are irrelevant here. Checking them would abort the
            # whole collection (and every visual triage batch) for candidates that have no image anyway.
            continue
        positions = [ref[key] for key in ('source_position', 'result_position') if key in ref]
        if positions:
            if any(type(position) is not int or position < 1 for position in positions):
                raise ValueError('MEDIA_SOURCE_POSITION_INVALID')
            if len(set(positions)) != 1:
                raise ValueError('MEDIA_SOURCE_POSITION_CONFLICT')
            rows = rows_by_position.get(positions[0], [])
            if len(rows) != 1:
                raise ValueError('MEDIA_SOURCE_POSITION_NOT_FOUND')
            if rows[0]['raw_sha256'] != ref.get('source_record_sha256'):
                raise ValueError('MEDIA_SOURCE_POSITION_HASH_MISMATCH')
        else:
            # Legacy references without a location still need an unambiguous
            # hash. An explicit conflicting location must never fall back here.
            rows = rows_by_hash.get(ref.get('source_record_sha256'), [])
            if len(rows) != 1:
                continue
        row = rows[0]
        if 'source_collection' in ref and ref['source_collection'] != row['collection']:
            raise ValueError('MEDIA_SOURCE_COLLECTION_MISMATCH')
        if failed_material and not any(
                entry.get('evidence_id') == ref.get('evidence_id')
                and any(item.get('source_record_sha256') == row['raw_sha256']
                        and (item.get('source_position') or item.get('result_position')) == row['position']
                        for item in _candidate_rows(entry.get('payload')))
                for entry in _run_entries(evidence, run['run_id'])):
            # A readable error body alone is not a registered candidate. Keep
            # failed/unknown query obligations; only reuse its bound media.
            continue
        location = (row['collection'], row['collection_position'])
        if location not in originals_by_position:
            continue
        def visit(value, label=''):
            if isinstance(value, dict):
                for key, child in value.items():
                    if key in IMAGE_FIELDS and isinstance(child, str) and child.startswith('https://'):
                        urls.append({'url': child, 'thumbnail': 'thumbnail' in key.lower() or 'thumbnail' in label,
                            'source_run_id': run['run_id'], 'source_record_sha256': row['raw_sha256'],
                            'source_position': row['position'], 'query_jurisdiction': run.get('jurisdiction'),
                            'right_jurisdiction': candidate.get('jurisdiction', 'UNLOCATED')})
                    elif isinstance(child, (dict, list)):
                        visit(child, key)
            elif isinstance(value, list):
                for child in value:
                    visit(child, label)
        visit(originals_by_position[location])
    unique = {row['url']: row for row in reversed(urls)}
    return sorted(unique.values(), key=lambda row: row['thumbnail'])[:2]


def _assert_media_active(root, candidates):
    """Reload user control at each dispatch/write boundary; never cache a pause as URL failure."""
    from continuation_stage_c import dispatch_block
    current_task = load_json(root / 'task.json')
    current_evidence = load_json(root / 'evidence.json')
    if any(dispatch_block(current_task, current_evidence, candidate) for candidate in candidates):
        raise ValueError('USER_ACTIVE_PAUSE')
    if policy(current_task) is None or current_task.get('state') == 'completed':
        raise ValueError('MEDIA_ACTIVE_NEW_TASK_REQUIRED')


def _collect_legacy(task_dir, candidate_ids, *, deadline=None):
    from annotate_materiality import candidate_index
    from provider_utils import evidence_lock
    from runtime_timing import timed_step
    root = Path(task_dir).resolve()
    task, evidence, candidates = [load_json(root / name) for name in
                                  ('task.json', 'evidence.json', 'normalized-candidates.json')]
    limits = policy(task)
    if limits is None or task.get('state') == 'completed':
        raise ValueError('MEDIA_ACTIVE_NEW_TASK_REQUIRED')
    index, errors = candidate_index(candidates)
    if errors or not candidate_ids or len(set(candidate_ids)) != len(candidate_ids) or not set(candidate_ids) <= set(index):
        raise ValueError('MEDIA_CANDIDATE_IDS_INVALID')
    active_candidates = [index[cid][1] for cid in candidate_ids]
    _assert_media_active(root, active_candidates)
    bindings = {cid: candidate_urls(root, index[cid][1], evidence) for cid in candidate_ids}
    cache_path = root / 'candidate-media.json'
    cache = load_json(cache_path) if cache_path.is_file() else {'schema': 'IPR-CANDIDATE-MEDIA/1.0', 'urls': {}, 'candidates': {}}
    receipt_bindings = {}
    for rows in bindings.values():
        for row in rows:
            receipt_bindings.setdefault(row['url'], set()).add(row['source_record_sha256'])
    def fetch(url):
        _assert_media_active(root, active_candidates)
        old = cache['urls'].get(url)
        if old:
            if old['status'] == 'failed':
                return old  # Changing candidate/action IDs never retries a failed URL.
            if not receipt_bindings[url] <= set(old.get('receipt_content_sha256', [])):
                old = None
        if old and old['status'] == 'retained':
            path = root / old['path']
            if not path.is_file() or sha256_file(path) != old['sha256']:
                raise ValueError('MEDIA_RETAINED_IMAGE_CHANGED')
            decode_image(path.read_bytes())
            return old
        try:
            body, suffix, size, final = download(url, timeout=limits['media_timeout_seconds'],
                max_bytes=limits['media_max_bytes'], deadline=deadline)
        except (OSError, ValueError, http.client.HTTPException) as exc:
            _assert_media_active(root, active_candidates)
            return {'status': 'failed', 'reason': type(exc).__name__ + ':' + str(exc)[:240], 'checked_at': now_iso()}
        digest = sha256_bytes(body)
        path = root / 'raw' / 'candidate-media' / (digest + suffix)
        # Share the pause recorder's lock for the check+write boundary. A pause
        # arriving during network I/O leaves previous evidence untouched.
        with evidence_lock(root):
            _assert_media_active(root, active_candidates)
            path.parent.mkdir(parents=True, exist_ok=True)
            atomic_write_bytes(path, body)
        return {'status': 'retained', 'path': str(path.relative_to(root)), 'sha256': digest,
                'bytes': len(body), 'dimensions': list(size), 'source_url': url,
                'resolved_url': final, 'checked_at': now_iso(),
                'receipt_content_sha256': sorted(receipt_bindings[url])}
    with timed_step(root, 'candidate_media'), ThreadPoolExecutor(max_workers=min(4, limits['media_workers'])) as pool:
        # Only fetch alternates after the original card's first address failed.
        for position in (0, 1):
            pending = list(dict.fromkeys(rows[position]['url'] for rows in bindings.values() if len(rows) > position
                and (position == 0 or cache['urls'].get(rows[0]['url'], {}).get('status') == 'failed')))
            for url, result in zip(pending, pool.map(fetch, pending)):
                cache['urls'][url] = result
    with evidence_lock(root):
        _assert_media_active(root, active_candidates)
        current_evidence = load_json(root / 'evidence.json')
        current_index, errors = candidate_index(load_json(root / 'normalized-candidates.json'))
        if errors or any(cid not in current_index or candidate_urls(root, current_index[cid][1], current_evidence) != rows
                         for cid, rows in bindings.items()):
            raise ValueError('MEDIA_SOURCE_CHANGED_DURING_DOWNLOAD')
        supplement_path = root / 'supplemental-evidence.json'
        supplement = load_json(supplement_path) if supplement_path.is_file() else {
            'schema': 'IPR-SUPPLEMENT/1.0', 'evidence': [], 'coverage_notes': []}
        for cid, rows in bindings.items():
            selected = next((row for row in rows if cache['urls'].get(row['url'], {}).get('status') == 'retained'), None)
            if selected is None:
                cache['candidates'][cid] = {'status': 'needs_info', 'reason': 'No decodable receipt-bound image', 'attempted': rows}
                continue
            saved = cache['urls'][selected['url']]
            ref = 'MEDIA-' + sha256_json([cid, selected, saved['sha256']])[:24]
            entry = {**saved, **selected, 'evidence_id': ref, 'candidate_id': cid, 'kind': 'candidate_image',
                     'image_role': 'thumbnail' if selected['thumbnail'] else 'representative_image',
                     'not_full_rights_views': True}
            entry.pop('url', None)
            if not any(e['evidence_id'] == ref for e in supplement['evidence']):
                supplement['evidence'].append(entry)
            cache['candidates'][cid] = {'status': 'retained', 'evidence_id': ref, 'sha256': saved['sha256']}
        from assessment_estimate import validate_supplement
        validate_supplement(supplement, root, task=task, evidence=current_evidence)
        atomic_write_json(supplement_path, supplement)
        atomic_write_json(cache_path, cache)
    return {cid: cache['candidates'][cid] for cid in candidate_ids}


def collect(task_dir, candidate_ids, *, deadline=None):
    from execution_efficiency import revised
    root = Path(task_dir).resolve()
    if not revised(load_json(root / 'task.json')):
        return _collect_legacy(root, candidate_ids, deadline=deadline)
    return _collect_revised(root, candidate_ids, deadline=deadline)


def _collect_revised(root, candidate_ids, *, deadline=None):
    from annotate_materiality import candidate_index
    from provider_utils import evidence_lock
    from runtime_timing import timed_step
    from execution_budget import remaining
    task, evidence, candidates = [load_json(root / name) for name in
                                  ('task.json', 'evidence.json', 'normalized-candidates.json')]
    limits = policy(task)
    index, errors = candidate_index(candidates)
    if errors or not candidate_ids or len(set(candidate_ids)) != len(candidate_ids) or not set(candidate_ids) <= set(index):
        raise ValueError('MEDIA_CANDIDATE_IDS_INVALID')
    active_candidates = [index[cid][1] for cid in candidate_ids]
    _assert_media_active(root, active_candidates)
    receipt_index = {}
    bindings = {cid: candidate_urls(root, index[cid][1], evidence, receipt_index=receipt_index)
                for cid in candidate_ids}
    cache_path = root / 'candidate-media.json'
    def read_cache():
        return load_json(cache_path) if cache_path.is_file() else {
            'schema': 'IPR-CANDIDATE-MEDIA/1.0', 'urls': {}, 'candidates': {}}
    cache = read_cache()
    receipt_bindings = {}
    for rows in bindings.values():
        for row in rows:
            receipt_bindings.setdefault(row['url'], set()).add(row['source_record_sha256'])
    stopped = threading.Event()
    def budget_check():
        if stopped.is_set():
            raise MediaBudgetExhausted(False)
        try:
            remaining(deadline, limits['media_timeout_seconds'])
        except ValueError as exc:
            if str(exc) != 'EXECUTION_TIME_BUDGET_EXHAUSTED':
                raise
            raise MediaBudgetExhausted(False) from None
    def failed(exc, kind):
        return {'status': 'failed', 'reason': str(exc)[:240], 'checked_at': now_iso(),
                'failure_kind': kind, 'request_started': exc.request_started}
    def reusable(url, old):
        return bool(old and (old['status'] == 'failed' or old['status'] == 'retained'
                    and receipt_bindings[url] <= set(old.get('receipt_content_sha256', []))))
    def fetch(url):
        _assert_media_active(root, active_candidates)
        old = cache['urls'].get(url)
        # Historical failures without a request flag remain unknown and are
        # never reclassified or retried from their human-readable error text.
        if old and old['status'] == 'failed':
            return old, None, False
        if old and receipt_bindings[url] <= set(old.get('receipt_content_sha256', [])):
            path = root / old['path']
            if not path.is_file() or sha256_file(path) != old['sha256']:
                raise ValueError('MEDIA_RETAINED_IMAGE_CHANGED')
            decode_image(path.read_bytes())
            return old, None, False
        budget_check()
        try:
            body, suffix, size, final = download(url, timeout=limits['media_timeout_seconds'],
                max_bytes=limits['media_max_bytes'], deadline=deadline, revised_budget=True)
        except MediaBudgetExhausted:
            raise
        except MediaDownloadError as exc:
            _assert_media_active(root, active_candidates)
            return failed(exc, 'url'), None, True
        # Retain compatibility with callers supplying an alternate downloader;
        # absent transmission evidence is unknown, never definitely unsubmitted.
        except (OSError, ValueError, http.client.HTTPException) as exc:
            _assert_media_active(root, active_candidates)
            wrapped = MediaDownloadError(exc, None)
            return failed(wrapped, 'url'), None, True
        digest = sha256_bytes(body)
        record = {'status': 'retained', 'path': 'raw/candidate-media/' + digest + suffix,
            'sha256': digest, 'bytes': len(body), 'dimensions': list(size), 'source_url': url,
            'resolved_url': final, 'checked_at': now_iso(),
            'receipt_content_sha256': sorted(receipt_bindings[url])}
        return record, body, True
    def checkpoint(url, record, body):
        nonlocal cache
        with evidence_lock(root):
            _assert_media_active(root, active_candidates)
            latest = read_cache()
            prior = latest['urls'].get(url)
            if prior and prior != cache['urls'].get(url):
                raise ValueError('MEDIA_URL_CACHE_CHANGED_DURING_DOWNLOAD')
            if body is not None:
                path = root / record['path']
                path.parent.mkdir(parents=True, exist_ok=True)
                atomic_write_bytes(path, body)
            latest['urls'][url] = record
            atomic_write_json(cache_path, latest)
            cache = latest
    budget_error = None
    workers = min(4, limits['media_workers'])
    with timed_step(root, 'candidate_media'), ThreadPoolExecutor(max_workers=workers) as pool:
        for position in (0, 1):
            if budget_error:
                break
            pending = deque(dict.fromkeys(rows[position]['url'] for rows in bindings.values() if len(rows) > position
                and (position == 0 or cache['urls'].get(rows[0]['url'], {}).get('status') == 'failed')))
            futures = {}
            while pending or futures:
                while pending and len(futures) < workers and not budget_error:
                    url = pending.popleft()
                    if not reusable(url, cache['urls'].get(url)):
                        try:
                            budget_check()
                        except MediaBudgetExhausted as exc:
                            budget_error = exc
                            stopped.set()
                            break
                    futures[pool.submit(fetch, url)] = url
                if not futures:
                    break
                done, _ = wait(futures, return_when=FIRST_COMPLETED)
                for future in done:
                    url = futures.pop(future)
                    try:
                        record, body, changed = future.result()
                    except MediaBudgetExhausted as exc:
                        budget_error = exc
                        stopped.set()
                        if exc.request_started:
                            checkpoint(url, failed(exc, 'execution_budget'), None)
                        continue
                    if changed:
                        checkpoint(url, record, body)
    # A fresh per-commit index revalidates each original exactly once. The
    # dispatch index cannot serve as proof that the receipt stayed unchanged.
    with evidence_lock(root):
        _assert_media_active(root, active_candidates)
        current_evidence = load_json(root / 'evidence.json')
        current_index, errors = candidate_index(load_json(root / 'normalized-candidates.json'))
        receipt_index = {}
        if errors or any(cid not in current_index or candidate_urls(root, current_index[cid][1],
                current_evidence, receipt_index=receipt_index) != rows for cid, rows in bindings.items()):
            raise ValueError('MEDIA_SOURCE_CHANGED_DURING_DOWNLOAD')
        cache = read_cache()
        supplement_path = root / 'supplemental-evidence.json'
        supplement = load_json(supplement_path) if supplement_path.is_file() else {
            'schema': 'IPR-SUPPLEMENT/1.0', 'evidence': [], 'coverage_notes': []}
        for cid, rows in bindings.items():
            selected = next((row for row in rows if cache['urls'].get(row['url'], {}).get('status') == 'retained'
                and reusable(row['url'], cache['urls'][row['url']])), None)
            if selected is None:
                # The cause stays next to the row: a whole run failing for one reason
                # (a local DNS answering non-public addresses) must be visible at once.
                attempted = [{**row, 'failure': str(cache['urls'][row['url']].get('reason') or '')[:240]}
                             for row in rows if cache['urls'].get(row['url'], {}).get('status') == 'failed']
                cache['candidates'][cid] = {'status': 'needs_info', 'reason': 'No decodable receipt-bound image',
                                             'attempted': attempted}
                continue
            saved = cache['urls'][selected['url']]
            ref = 'MEDIA-' + sha256_json([cid, selected, saved['sha256']])[:24]
            entry = {**saved, **selected, 'evidence_id': ref, 'candidate_id': cid, 'kind': 'candidate_image',
                     'image_role': 'thumbnail' if selected['thumbnail'] else 'representative_image',
                     'not_full_rights_views': True}
            entry.pop('url', None)
            if not any(e['evidence_id'] == ref for e in supplement['evidence']):
                supplement['evidence'].append(entry)
            cache['candidates'][cid] = {'status': 'retained', 'evidence_id': ref, 'sha256': saved['sha256']}
        from assessment_estimate import validate_supplement
        validate_supplement(supplement, root, task=task, evidence=current_evidence)
        atomic_write_json(supplement_path, supplement)
        atomic_write_json(cache_path, cache)
    if budget_error:
        raise budget_error
    return {cid: cache['candidates'][cid] for cid in candidate_ids}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--task-dir', type=Path, required=True)
    parser.add_argument('--candidate-id', action='append', required=True)
    args = parser.parse_args()
    from execution_budget import execution_budget
    with execution_budget(args.task_dir, 'sources', inherit=True) as deadline:
        result = collect(args.task_dir, args.candidate_id, deadline=deadline)
    print(json.dumps(result, ensure_ascii=False))
    try:
        from network_diagnostic import media_failure_advice
        import sys
        for line in media_failure_advice(result):
            print(line, file=sys.stderr)
    except (ImportError, ValueError):
        pass


if __name__ == '__main__':
    main()
