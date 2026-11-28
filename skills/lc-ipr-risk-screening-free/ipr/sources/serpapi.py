"""SerpApi：Google Patents 检索（按相关度排序，带现行状态和代表图）。每次成功的检索计 1 次，账户查询不计次。"""
from __future__ import annotations

import re
import urllib.parse
import uuid
from pathlib import Path

from .. import numbers
from . import http

BASE = "https://serpapi.com"


def remaining(key: str, opener=None) -> int:
    """这个 key 还剩几次；查不到返回 -1。"""
    if not key:
        return 0
    try:
        status, _headers, data = http.fetch_json(BASE + "/account.json?" + urllib.parse.urlencode({"api_key": key}), timeout=15, opener=opener)
    except http.SourceError:
        return -1
    if status != 200 or not isinstance(data, dict):
        return -1
    try:
        return int(data.get("total_searches_left"))
    except (TypeError, ValueError):
        return -1


def patents(key: str, query: str, design: bool, country: str = "US", after: str = "", limit: int = 100, opener=None,
            granted: bool = True, language: str = "") -> dict:
    """country 可以是几个局（"DE,EP"）。granted=False 不加"只要已授权"的筛选：欧盟外观没有授权日，加了一条都查不到。
    返回 {"total": …, "docs": […]}；零结果是正常结果，不是失败。"""
    params = {"engine": "google_patents", "api_key": key, "q": query, "country": country,
              "type": "DESIGN" if design else "PATENT", "num": str(max(10, min(100, limit)))}
    if granted:
        params["status"] = "GRANT"
    if language:  # 欧盟外观每种语言各有一条记录：只要英文的，不然 100 条里其实只有三四件
        params["language"] = language
    if after:
        params["after"] = after
    status, _headers, data = http.fetch_json(BASE + "/search.json?" + urllib.parse.urlencode(params), timeout=45, opener=opener)
    error = str(data.get("error") or "") if isinstance(data, dict) else ""
    if status in (401, 403):
        raise http.SourceError("SerpApi 的 key 无效", kind="auth", status=status)
    if status == 429 or "run out of searches" in error.lower() or "exceeded" in error.lower():
        raise http.SourceError("SerpApi 本期的次数用完了", kind="quota", status=status)
    if "hasn't returned any results" in error:
        return {"total": 0, "docs": []}
    if status != 200 or not isinstance(data, dict) or error:
        raise http.SourceError("SerpApi 返回状态码 %d%s" % (status, "：" + error[:120] if error else ""), status=status)
    if not isinstance(data.get("organic_results"), list):
        raise http.SourceError("SerpApi 返回的内容里没有检索结果", kind="format", status=status)
    docs = [doc for doc in (normalize(item, design, country) for item in data["organic_results"] if isinstance(item, dict)) if doc]
    info = data.get("search_information") if isinstance(data.get("search_information"), dict) else {}
    try:
        total = int(info.get("total_results"))
    except (TypeError, ValueError):
        total = len(docs)
    return {"total": total, "docs": docs}


def _check(status: int, data, what: str) -> None:
    error = str(data.get("error") or "") if isinstance(data, dict) else ""
    if status in (401, 403):
        raise http.SourceError("SerpApi 的 key 无效", kind="auth", status=status)
    if status == 429 or "run out of searches" in error.lower() or "exceeded" in error.lower():
        raise http.SourceError("SerpApi 本期的次数用完了", kind="quota", status=status)
    if status != 200 or not isinstance(data, dict) or error:
        raise http.SourceError("SerpApi %s返回状态码 %d%s" % (what, status, "：" + error[:120] if error else ""), status=status)


def upload_image(key: str, path, opener=None) -> str:
    """把本地图片传给 SerpApi（POST /image，multipart，字段 image 和 api_key；≤500KB 的 jpg/png/webp），返回 image_id（10 分钟内有效）。
    用户 2026-11-28 同意上传主图（图在对方那里保存一段时间）。"""
    path = Path(path)
    boundary = "----lcipr" + uuid.uuid4().hex
    kind = {".png": "image/png", ".webp": "image/webp"}.get(path.suffix.lower(), "image/jpeg")
    body = b"".join([
        ("--%s\r\nContent-Disposition: form-data; name=\"api_key\"\r\n\r\n%s\r\n" % (boundary, key)).encode("utf-8"),
        ("--%s\r\nContent-Disposition: form-data; name=\"image\"; filename=\"product%s\"\r\nContent-Type: %s\r\n\r\n"
         % (boundary, path.suffix.lower() or ".jpg", kind)).encode("utf-8"),
        path.read_bytes(),
        ("\r\n--%s--\r\n" % boundary).encode("utf-8")])
    status, _headers, data = http.fetch_json(BASE + "/image", "POST", {"Content-Type": "multipart/form-data; boundary=" + boundary},
                                             body, timeout=60, opener=opener)
    _check(status, data, "上传图片时")
    image_id = str(data.get("image_id") or "")
    if not image_id:
        raise http.SourceError("SerpApi 上传图片后没有给出图片编号", kind="format", status=status)
    return image_id


def lens(key: str, image_id: str = "", url: str = "", country: str = "", opener=None) -> list:
    """Google Lens 以图搜图（每次计 1 次）：返回长得像的网页 [{title, source, link, image}]，和 Serper 的格式一样。"""
    params = {"engine": "google_lens", "api_key": key, "type": "visual_matches"}
    if image_id:
        params["image_id"] = image_id
    else:
        params["url"] = url
    if country:
        params["country"] = country.lower()
    status, _headers, data = http.fetch_json(BASE + "/search.json?" + urllib.parse.urlencode(params), timeout=60, opener=opener)
    if isinstance(data, dict) and "hasn't returned any results" in str(data.get("error") or ""):
        return []
    _check(status, data, "以图搜图")
    return [{"title": str(i.get("title") or "")[:200], "source": str(i.get("source") or "")[:60], "link": str(i.get("link") or ""),
             "image": str(i.get("thumbnail") or i.get("image") or "")}
            for i in data.get("visual_matches") or [] if isinstance(i, dict)]


def normalize(item: dict, design: bool, country: str):
    raw = str(item.get("publication_number") or "")
    if country == "US":
        number = numbers.us_display(raw) if numbers.us_key(raw) else raw
    else:
        number = re.sub(r"[^A-Za-z0-9]", "", raw).upper()
    if not number:
        return None
    statuses = item.get("country_status") if isinstance(item.get("country_status"), dict) else {}
    state = str(statuses.get(country if country == "US" else numbers.office_of(number)) or "")  # 看发这件专利的那个局记的状态
    figures = [str(f.get("full") or f.get("thumbnail")) for f in item.get("figures") or [] if isinstance(f, dict) and (f.get("full") or f.get("thumbnail"))]
    return {
        "right_type": ("design" if design else "patent") if country == "US" else numbers.kind_type(number, design),
        "number": number,
        "title": str(item.get("title") or "").strip(),
        "owner": str(item.get("assignee") or ""),
        "filing_date": str(item.get("filing_date") or "")[:10],
        "grant_date": str(item.get("grant_date") or "")[:10],
        "url": str(item.get("patent_link") or "https://patents.google.com/patent/%s/en" % number),
        "snippet": str(item.get("snippet") or "")[:400],
        "legal_status": {"ACTIVE": "有效", "NOT_ACTIVE": "已失效"}.get(state, ""),
        "figures": ([str(item["thumbnail"])] if item.get("thumbnail") else []) + figures[:8],
        "source": "SerpApi（Google Patents）",
    }
