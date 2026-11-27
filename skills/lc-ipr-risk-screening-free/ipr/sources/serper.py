"""Serper：以图搜图（Google Lens，一次 3 个点数）和网页检索（一次 1 个点数）。免费账户不支持带引号和 OR 的检索式。"""
from __future__ import annotations

from . import http

BASE = "https://google.serper.dev"


def _post(key: str, path: str, body: dict, opener=None) -> dict:
    status, _headers, data = http.fetch_json(BASE + path, "POST", {"X-API-KEY": key}, body=body, timeout=40, opener=opener)
    message = str(data.get("message") or "") if isinstance(data, dict) else ""
    if status in (401, 403):
        raise http.SourceError("Serper 的 key 无效或没有权限", kind="auth", status=status)
    if status == 429 or "credit" in message.lower():
        raise http.SourceError("Serper 的点数用完了", kind="quota", status=status)
    if status != 200 or not isinstance(data, dict):
        raise http.SourceError("Serper 返回状态码 %d%s" % (status, "：" + message[:120] if message else ""), status=status)
    return data


def balance(key: str, opener=None) -> int:
    if not key:
        return 0
    try:
        status, _headers, data = http.fetch_json(BASE + "/account", headers={"X-API-KEY": key}, timeout=15, opener=opener)
        return int(data.get("balance")) if status == 200 and isinstance(data, dict) else -1
    except (http.SourceError, TypeError, ValueError):
        return -1


def lens(key: str, image_url: str, opener=None) -> list:
    """以图搜图：返回长得像的网页 [{title, source, link, image}]。"""
    data = _post(key, "/lens", {"url": image_url}, opener)
    return [{"title": str(i.get("title") or "")[:200], "source": str(i.get("source") or "")[:60], "link": str(i.get("link") or ""),
             "image": str(i.get("imageUrl") or i.get("thumbnailUrl") or "")}
            for i in data.get("organic") or [] if isinstance(i, dict)]


def web(key: str, query: str, country: str = "us", limit: int = 10, opener=None) -> list:
    data = _post(key, "/search", {"q": query, "gl": country.lower(), "num": limit}, opener)
    return [{"title": str(i.get("title") or "")[:200], "link": str(i.get("link") or ""), "snippet": str(i.get("snippet") or "")[:300],
             "date": str(i.get("date") or "")}
            for i in data.get("organic") or [] if isinstance(i, dict)]
