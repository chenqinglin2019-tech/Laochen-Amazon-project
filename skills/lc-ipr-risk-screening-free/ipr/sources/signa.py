"""Signa：按文字查商标（美国、欧盟、英国等）。一页结果 10 个点数。只要现在有效或在申请中的。"""
from __future__ import annotations

import urllib.parse

from . import http

BASE = "https://api.signa.so"
OFFICE_NAMES = {"US": "美国", "EM": "欧盟商标", "GB": "英国", "FR": "法国", "IT": "意大利", "ES": "西班牙"}
OFFICES = {"US": "US", "GB": "GB", "FR": "FR,EM", "IT": "IT,EM", "ES": "ES,EM", "DE": "EM", "JP": ""}  # 德国、日本本国库 Signa 还没有


def credits(key: str, opener=None) -> int:
    if not key:
        return 0
    try:
        status, _headers, data = http.fetch_json(BASE + "/v1/organization/credits", headers={"Authorization": "Bearer " + key}, timeout=15, opener=opener)
        return int(float(data.get("balance"))) if status == 200 and isinstance(data, dict) else -1
    except (http.SourceError, TypeError, ValueError):
        return -1


def _pick(item: dict, *names):
    for name in names:
        value = item.get(name)
        if isinstance(value, dict):
            value = value.get("name") or value.get("display_name") or value.get("text")
        if isinstance(value, list) and value:
            first = value[0]
            value = first.get("name") if isinstance(first, dict) else first
        if value not in (None, "", [], {}):
            return str(value)
    return ""


def trademarks(key: str, text: str, offices: str, limit: int = 10, opener=None) -> list:
    params = {"q": text, "offices": offices, "status_primary": "active,pending", "limit": str(limit)}
    status, _headers, data = http.fetch_json(BASE + "/v1/trademarks?" + urllib.parse.urlencode(params),
                                             headers={"Authorization": "Bearer " + key}, timeout=30, opener=opener)
    if status in (401, 403):
        raise http.SourceError("Signa 的 key 无效或没有权限", kind="auth", status=status)
    if status in (402, 429):
        raise http.SourceError("Signa 的点数用完了或请求太频繁", kind="quota", status=status)
    if status != 200 or not isinstance(data, dict):
        raise http.SourceError("Signa 返回状态码 %d" % status, status=status)
    if not isinstance(data.get("data"), list):
        raise http.SourceError("Signa 返回的内容里没有检索结果", kind="format", status=status)
    out = []
    for item in data.get("data") or []:
        if not isinstance(item, dict) or not item.get("mark_text"):
            continue
        state = item.get("status") if isinstance(item.get("status"), dict) else {}
        classes = item.get("nice_classes") or item.get("classes") or []
        out.append({
            "right_type": "trademark",
            "number": str(item.get("registration_number") or item.get("application_number") or item.get("id") or ""),
            "title": str(item.get("mark_text")),
            "owner": _pick(item, "owner_name", "owner", "owners", "applicant", "applicants", "holder"),
            "filing_date": str(item.get("filing_date") or "")[:10],
            "grant_date": str(item.get("registration_date") or "")[:10],
            "legal_status": {"active": "有效", "pending": "申请中"}.get(str(state.get("primary") or ""), str(state.get("primary") or "")),
            "url": str(item.get("office_url") or ""),
            "snippet": "类别：%s；类型：%s" % ("、".join(str(c) for c in classes[:8]) if isinstance(classes, list) else classes,
                                        item.get("mark_feature_type") or ""),
            "office": str(item.get("office_code") or ""),
            "source": "Signa（商标库）",
        })
    return out
