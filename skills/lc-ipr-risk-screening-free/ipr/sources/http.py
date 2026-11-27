"""发请求的公共部分：超时、失败说明脱敏、JSON 解析。只用标准库；代理跟随系统环境变量。"""
from __future__ import annotations

import http.client
import json
import socket
import time
import urllib.error
import urllib.request

from .. import config, faults
from ..outcome import StepFailed

BROWSER_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) "
              "Chrome/130.0.0.0 Safari/537.36")


RETRY_PAUSE = 1.0  # 连不上时隔多久再试那一次（秒）


class SourceError(StepFailed):
    """某个数据源这一次没查成。kind：quota（次数用尽）、auth（key 不对）、http、network、format。"""

    def __init__(self, message: str, kind: str = "http", status: int = 0):
        super().__init__(message)
        self.kind = kind
        self.status = status


MAX_BYTES = 20_000_000  # 单个响应最多读这么多，防止异常的大响应把内存占满


def fetch(url: str, method: str = "GET", headers: dict = None, body=None, timeout: int = 30, opener=None, max_bytes: int = MAX_BYTES) -> tuple:
    """返回 (状态码, 响应头, 原始字节)。网络错误（含中途断流）抛 SourceError；HTTP 错误码照常返回，由调用方判断。"""
    data = None
    headers = dict({"User-Agent": BROWSER_UA, "Accept-Language": "en-US,en;q=0.9"}, **(headers or {}))
    if body is not None:
        data = body if isinstance(body, bytes) else json.dumps(body).encode("utf-8")
        headers.setdefault("Content-Type", "application/json")
    if faults.url_blocked(url):  # 测试开关：演练某个接口连不上
        raise SourceError("连不上或中途断开（测试开关模拟的）", kind="network")
    for attempt in (1, 2):  # 连接被掐断这类一闪而过的故障：自动再试一次（需求 R-009）。等到超时的不重试，免得把时间翻倍
        request = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with (opener or urllib.request.urlopen)(request, timeout=timeout) as response:
                raw = response.read(max_bytes + 1) if max_bytes else response.read()
                if max_bytes and len(raw) > max_bytes:
                    raise SourceError("返回的内容太大，没有读完", kind="format", status=response.status)
                return response.status, dict(response.headers), raw
        except urllib.error.HTTPError as exc:
            try:
                return exc.code, dict(exc.headers or {}), exc.read()
            except (http.client.HTTPException, OSError):
                return exc.code, dict(exc.headers or {}), b""
        except (urllib.error.URLError, http.client.HTTPException, OSError, ValueError) as exc:
            reason = getattr(exc, "reason", None)
            timed_out = isinstance(exc, (socket.timeout, TimeoutError)) or isinstance(reason, (socket.timeout, TimeoutError))
            if attempt == 1 and not timed_out and not isinstance(exc, ValueError):
                time.sleep(RETRY_PAUSE)
                continue
            raise SourceError("连不上或中途断开（%s）" % config.redact(reason or type(exc).__name__), kind="network")


def fetch_json(url: str, method: str = "GET", headers: dict = None, body=None, timeout: int = 30, opener=None) -> tuple:
    """返回 (状态码, 响应头, 解析后的 JSON)。返回的不是 JSON 抛 SourceError。"""
    status, response_headers, raw = fetch(url, method, headers, body, timeout, opener)
    try:
        return status, response_headers, json.loads(raw.decode("utf-8", "replace"))
    except ValueError:
        raise SourceError("返回的不是约定的格式（状态码 %d）" % status, kind="format", status=status)


def download(url: str, dest, timeout: int = 30, max_bytes: int = 15_000_000, opener=None) -> bool:
    """下载一个文件。只接受 http(s)；失败返回 False，不抛。"""
    if not str(url).lower().startswith(("http://", "https://")):
        return False
    try:
        status, _headers, raw = fetch(url, timeout=timeout, opener=opener, max_bytes=max_bytes)
    except SourceError:
        return False
    if status != 200 or not raw:
        return False
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(raw)
    return True
