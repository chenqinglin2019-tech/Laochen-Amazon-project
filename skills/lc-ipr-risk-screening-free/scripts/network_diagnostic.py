"""Name a local "fake-IP" proxy before a run depends on it (standard library only, DNS lookups only).

Candidate images are fetched only from public addresses. A transparent proxy in fake-IP mode (Clash, Surge, ...)
answers every name from the benchmarking block 198.18.0.0/15, so every image is refused with the same cause and the
run loses minutes finding out. This module resolves a few fixed names, classifies the answers with the same rule
the downloader uses and says what to change. It sends no request to any of those sites and reads no credential.
"""
from __future__ import annotations

import ipaddress
import socket
import threading

SCHEMA = 'IPR-NETWORK-CHECK/1.0'
# Image hosts of the sources this skill collects from, plus the patent office viewer. Retail sites cannot be
# listed; a fake-IP proxy answers all of them the same way, which these names already show.
HOSTS = ('m.media-amazon.com', 'images-na.ssl-images-amazon.com', 'encrypted-tbn0.gstatic.com',
         'patentimages.storage.googleapis.com', 'patents.google.com', 'ppubs.uspto.gov', 'www.amazon.com')
ADVICE_FAKE_IP = [
    '本机代理处于 fake-IP 模式（域名被解析到 198.18.0.0/15）。候选图片只允许从公网地址下载，会被全部拒绝。',
    'Clash / Clash Verge：把 dns.enhanced-mode 改为 redir-host，或为相关域名加入 fake-ip-filter。',
    'Surge：关闭增强模式，或在 [General] 中用 always-real-ip 列出相关域名（例如 *.media-amazon.com、'
    '*.ssl-images-amazon.com、*.gstatic.com、*.googleapis.com、*.uspto.gov）。',
    '零售站图片域名无法穷举：建议在本次排查期间整体关闭 fake-IP，改完后重新运行 setup_skill.py --check-network。',
]
ADVICE_UNRESOLVED = ['这些域名无法解析：请检查网络、DNS 或代理设置后重试。']
# r9: since F3 (r5d4) a confirmed fake-IP proxy is supported; the advice above stays for downloads that were refused
ADVICE_FAKE_IP_COMPATIBLE = ['已检测到本机 fake-IP 代理（域名解析到 198.18.0.0/15）。程序已自动兼容：公开图片与页面经代理下载，'
                             '无需修改代理设置。',
                             '只有运行结果里出现"候选图片下载被拒"时才需要调整：' + ADVICE_FAKE_IP[1], ADVICE_FAKE_IP[2]]
ADVICE_PROXY = ['已检测到系统或环境变量里的 HTTP(S) 代理（未使用 fake-IP）。公开图片与页面将经该代理下载，无需修改设置。']
ADVICE_GOOGLE_UNREACHABLE = [
    '本机连不上 Google 专利网站和专利图片服务器（patents.google.com、patentimages.storage.googleapis.com）。'
    '外观附图和专利页面都会取不到，排查结果会缺图、不可靠，所以在建任务、花检索额度之前停下。',
    '请打开代理软件，并开启 TUN（增强）模式或"系统代理"，确认浏览器能打开 https://patents.google.com 后，用同一条命令重跑。',
]
REACH_HOSTS = ('patents.google.com', 'patentimages.storage.googleapis.com')


def _resolve(host, timeout, resolver):
    """Addresses of one name, or the error class name; never blocks longer than timeout."""
    done, box = threading.Event(), []

    def work():
        try:
            box.append(sorted({row[4][0] for row in resolver(host, 443, type=socket.SOCK_STREAM)}))
        except OSError as exc:
            box.append(exc)
        except Exception as exc:  # a resolver stub must never crash the diagnostic
            box.append(exc)
        finally:
            done.set()

    threading.Thread(target=work, daemon=True).start()
    if not done.wait(max(0.1, timeout)):
        return None, 'DNS_TIMEOUT'
    if isinstance(box[0], BaseException):
        return None, type(box[0]).__name__
    return box[0], None


def _classify(address):
    from candidate_media import address_class
    ip = ipaddress.ip_address(address)
    return 'public' if ip.is_global else address_class(address)


def proxy_settings():
    """The HTTP(S) proxy urllib (and so this skill's downloads) would use: where it came from, scheme, host and port.
    No user name, password or path is reported."""
    import urllib.request
    from urllib.parse import urlsplit
    try:
        environment = urllib.request.getproxies_environment()
        proxies = urllib.request.getproxies()
    except Exception as exc:
        return {'configured': False, 'error': type(exc).__name__}
    value = proxies.get('https') or proxies.get('http')
    if not value:
        return {'configured': False}
    parsed = urlsplit(value if '://' in value else 'http://' + value)
    source = 'environment' if (environment.get('https') or environment.get('http')) == value else 'system'
    return {'configured': parsed.scheme in ('http', 'https') and bool(parsed.hostname), 'source': source,
            'scheme': parsed.scheme, 'host': parsed.hostname, 'port': parsed.port}


def reachability(hosts=REACH_HOSTS, *, timeout=6.0, connect=None):
    """r9: a TLS handshake with each host through the same channel the downloads use (address rule, fake-IP rule,
    the user's proxy). Sends no HTTP request and reads no credential."""
    rows = []
    for host in hosts:
        try:
            if connect is not None:
                connect(host, timeout)
            else:
                from candidate_media import PublicConnection, public_address
                _, address = public_address('https://%s/' % host, timeout=timeout)
                connection = PublicConnection(host, address, timeout)
                try:
                    connection.connect()
                finally:
                    connection.close()
            rows.append({'host': host, 'reachable': True})
        except Exception as exc:
            rows.append({'host': host, 'reachable': False, 'error': type(exc).__name__ + ':' + str(exc)[:80]})
    return rows


def diagnose(hosts=HOSTS, *, timeout=3.0, resolver=socket.getaddrinfo, reach=False, connect=None):
    rows = []
    for host in hosts:
        addresses, error = _resolve(host, timeout, resolver)
        if addresses is None:
            rows.append({'host': host, 'status': 'unresolved', 'error': error, 'addresses': []})
            continue
        classes = sorted({_classify(address) for address in addresses})
        rows.append({'host': host, 'status': 'public' if classes == ['public'] else 'non_public',
                     'addresses': addresses[:4], 'classes': classes})
    fake = [row['host'] for row in rows if any(c.startswith('benchmarking') for c in row.get('classes', []))]
    other = [row['host'] for row in rows if row['status'] == 'non_public' and row['host'] not in fake]
    unresolved = [row['host'] for row in rows if row['status'] == 'unresolved']
    if fake:
        status, advice = 'fake_ip_detected', ADVICE_FAKE_IP_COMPATIBLE
    elif other:
        status, advice = 'non_public_address', ['这些域名解析到了非公网地址，候选图片下载会被拒绝；请检查本机 hosts 文件、'
                                               '公司 DNS 或代理设置。']
    elif unresolved and len(unresolved) == len(rows):
        status, advice = 'unresolved', ADVICE_UNRESOLVED
    elif unresolved:
        status, advice = 'partly_unresolved', ADVICE_UNRESOLVED
    else:
        status, advice = 'ok', []
    proxy = proxy_settings()
    if status == 'ok' and proxy.get('configured'):
        status, advice = 'proxy_without_fake_ip', ADVICE_PROXY
    result = {'schema': SCHEMA, 'status': status, 'hosts': rows, 'advice': advice,
              'affected_hosts': sorted(set(fake) | set(other)), 'unresolved_hosts': unresolved,
              'proxy': proxy, 'source_request': 'not_run', 'credentials': 'not_read'}
    if reach:
        # r9: only a handshake; both Google hosts unreachable means no drawing or page can be read this run
        result['reachability'] = reachability(timeout=max(timeout, 6.0), connect=connect)
        if result['reachability'] and not any(row['reachable'] for row in result['reachability']):
            result.update(status='google_unreachable', advice=ADVICE_GOOGLE_UNREACHABLE)
    return result


def notice(result) -> str:
    """One Chinese line for the pipeline output, or '' (r9)."""
    if not isinstance(result, dict):
        return ''
    status = result.get('status')
    advice = [line for line in result.get('advice') or [] if isinstance(line, str)]
    if status in ('fake_ip_detected', 'proxy_without_fake_ip'):
        return advice[0] if advice else ''          # informational: handled automatically, nothing to change
    if status in ('google_unreachable', 'non_public_address', 'unresolved', 'partly_unresolved'):
        return ''.join(advice)
    return ''


def media_failure_advice(candidates):
    """One advice block when many retained image downloads failed for the fake-IP cause, else []."""
    count, hosts = 0, set()
    for row in (candidates or {}).values():
        for attempt in (row.get('attempted') or []) if isinstance(row, dict) else []:
            failure = str(attempt.get('failure') or '')
            if 'MEDIA_PUBLIC_ADDRESS_REQUIRED:benchmarking' in failure:
                count += 1
                from urllib.parse import urlsplit
                host = urlsplit(str(attempt.get('url') or '')).hostname
                if host:
                    hosts.add(host)
    if not count:
        return []
    head = '候选图片下载被拒绝 %d 次（%d 个域名被本机代理解析到 198.18.0.0/15）。' % (count, len(hosts))
    return [head] + ADVICE_FAKE_IP[1:]
