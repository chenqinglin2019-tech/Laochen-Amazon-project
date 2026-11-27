"""欧盟知识产权局的官方接口（要自己申请的账号，免费）：按品名查欧盟外观，按视图取图。
Google Patents 上的欧盟外观没有图；有这个账号时欧盟外观走这里，才能看图初筛和比对。"""
from __future__ import annotations

import json
import re
import threading
import time
import urllib.parse

from . import http

TOKEN_URL = "https://euipo.europa.eu/cas-server-webapp/oidc/accessToken"
BASE = "https://api.euipo.europa.eu/design-search"
SOURCE = "欧盟知识产权局（官方接口）"
DEAD = ("EXPIRED", "LAPSED", "SURRENDERED", "INVALID", "CANCELLED", "WITHDRAWN", "REFUSED", "REMOVED", "ENDED")

_state = {"id": "", "secret": "", "token": "", "until": 0.0, "failed_until": 0.0, "failure": ""}
FAILED_PAUSE = 120  # 通行证没取到：这么多秒内不再去取
_lock = threading.Lock()


def configure(env: dict) -> None:
    """记下账号（只在内存里）。账号变了就把旧的通行证丢掉。"""
    client, secret = str((env or {}).get("EUIPO_CLIENT_ID") or ""), str((env or {}).get("EUIPO_CLIENT_SECRET") or "")
    with _lock:
        if (client, secret) != (_state["id"], _state["secret"]):
            _state.update(id=client, secret=secret, token="", until=0.0, failed_until=0.0, failure="")


def ready() -> bool:
    return bool(_state["id"] and _state["secret"])


def _token(opener=None, stale: str = "") -> str:
    """stale：刚被接口拒掉的那张通行证。别的线程已经换了新的就直接用新的，不重复去取。"""
    with _lock:
        if _state["token"] and time.time() < _state["until"] and _state["token"] != stale:
            return _state["token"]
        if not ready():
            raise http.SourceError("没有配置欧盟知识产权局的账号", kind="auth")
        if time.time() < _state["failed_until"]:  # 刚才没取到：先不再试，免得几十件外观各撞一次
            raise http.SourceError(_state["failure"] or "欧盟知识产权局的通行证刚才没有取到", kind="auth")
        try:
            return _fetch_token(opener)
        except http.SourceError as exc:
            _state.update(token="", until=0.0, failed_until=time.time() + FAILED_PAUSE, failure=exc.message)
            raise


def _fetch_token(opener=None) -> str:
    """去取一张新的通行证。调用方已经拿着锁。"""
    body = urllib.parse.urlencode({"grant_type": "client_credentials", "client_id": _state["id"], "client_secret": _state["secret"],
                                   "scope": "uid"}).encode("utf-8")
    status, _headers, data = http.fetch_json(TOKEN_URL, "POST", {"Content-Type": "application/x-www-form-urlencoded"}, body, 30, opener)
    token = str(data.get("access_token") or "") if isinstance(data, dict) else ""
    if status != 200 or not token:
        raise http.SourceError("欧盟知识产权局的账号没有通过验证（状态码 %d）" % status, kind="auth", status=status)
    try:
        life = int(data.get("expires_in") or 3600)
    except (TypeError, ValueError):
        life = 3600
    _state.update(token=token, until=time.time() + max(60, life - 120), failed_until=0.0, failure="")
    return token


def _get(path: str, accept: str, opener=None, timeout: int = 30) -> tuple:
    """带通行证取一次；通行证失效（401）换一张再取一次。"""
    stale = ""
    for _attempt in (1, 2):
        token = _token(opener, stale)
        # Accept-Language 只认单个语言代码（en、de…）：写成浏览器那种 "en-US,en;q=0.9" 会被当成参数错误退回 400
        headers = {"Authorization": "Bearer " + token, "X-IBM-Client-Id": _state["id"], "Accept": accept, "Accept-Language": "en"}
        status, response_headers, raw = http.fetch(BASE + path, headers=headers, timeout=timeout, opener=opener)
        if status != 401:
            break
        stale = token
    if status == 429:
        raise http.SourceError("欧盟知识产权局的接口暂时不让查了（请求太快，或者今天的次数用完了）", kind="quota", status=status)
    return status, response_headers, raw


def words_of(phrase: str) -> list:
    """一个英文叫法里拿去查品名的词：小写、去掉复数的 s，太短的不要。"""
    words = [w[:-1] if len(w) > 5 and w.endswith("s") and not w.endswith("ss") else w for w in re.findall(r"[a-z][a-z0-9]+", str(phrase or "").lower())]
    words = [w for w in dict.fromkeys(words) if len(w) >= 3]
    longer = [w for w in words if len(w) >= 4]  # 三个字母的词前后加通配太宽（pen 会命中 pendant、opener）：有别的词时不用它
    return (longer or words)[:4]


def query_of(phrases: list) -> str:
    """几个叫法之间是"或"，一个叫法里的几个词要都出现在品名里（RSQL：逗号是或，分号是与）。"""
    groups = []
    for phrase in phrases:
        words = words_of(phrase)
        group = "(%s)" % ";".join("productIndications==*%s*" % w for w in words)
        if words and group not in groups:
            groups.append(group)
    return ",".join(groups[:4])


def search(phrases: list, limit: int = 100, opener=None) -> dict:
    """返回 {"total": …, "docs": […]}，新申请的在前。零结果是正常结果。"""
    query = query_of(phrases)
    if not query:
        return {"total": 0, "docs": []}
    params = {"query": query, "page": "0", "size": str(max(10, min(100, limit))), "sort": "applicationDate:desc"}
    status, _headers, raw = _get("/designs?" + urllib.parse.urlencode(params), "application/json", opener, 45)
    try:
        data = json.loads(raw.decode("utf-8", "replace"))
    except ValueError:
        raise http.SourceError("欧盟知识产权局返回的不是约定的格式（状态码 %d）" % status, kind="format", status=status)
    if status != 200 or not isinstance(data, dict) or not isinstance(data.get("designs"), list):
        raise http.SourceError("欧盟知识产权局返回状态码 %d" % status, status=status)
    docs = [doc for doc in (normalize(item) for item in data["designs"] if isinstance(item, dict)) if doc]
    try:
        total = int(data.get("totalElements"))
    except (TypeError, ValueError):
        total = len(docs)
    return {"total": total, "docs": docs}


def is_dead(state: str) -> bool:
    """按整词看：EXPIRED、SURRENDERED 这类算失效；INVALIDITY_PROCEDURE_PENDING（被提无效、还在审）仍然有效。"""
    words = set(re.split(r"[^A-Z]+", str(state or "").upper()))
    return bool(words & set(DEAD)) and "PENDING" not in words


def normalize(item: dict):
    number = str(item.get("designNumber") or "")
    match = re.fullmatch(r"(\d{9})-(\d{4})", number)
    if not match:
        return None
    state = str(item.get("status") or "").upper()
    owners = [str(a.get("name") or "") for a in item.get("applicants") or [] if isinstance(a, dict) and a.get("name")]
    return {
        "right_type": "design",
        "number": "EM%s%sS" % (match.group(1).lstrip("0"), match.group(2)),   # 和 Google Patents 的写法一个样子（015027734-0001 → EM150277340001S）
        "euipo": number,
        "title": "",                              # 品名在详情里，补材料时取
        "owner": "；".join(owners[:2]),
        "filing_date": str(item.get("applicationDate") or "")[:10],
        "grant_date": str(item.get("registrationDate") or "")[:10],
        "expiry": str(item.get("expiryDate") or "")[:10],
        "url": "https://euipo.europa.eu/eSearch/#details/designs/" + number,
        "snippet": "",
        "legal_status": "已失效" if is_dead(state) else "有效" if state.startswith("REGISTERED") else "",
        "classes": [str(c) for c in item.get("locarnoClasses") or []][:4],
        "figures": [],
        "source": SOURCE,
    }


def detail(number: str, opener=None) -> dict:
    """一件外观的英文品名和视图张数。取不到抛 SourceError。"""
    status, _headers, raw = _get("/designs/" + number, "application/json", opener)
    try:
        data = json.loads(raw.decode("utf-8", "replace"))
    except ValueError:
        data = None
    if status != 200 or not isinstance(data, dict):
        raise http.SourceError("欧盟知识产权局没有给出 %s 的详情（状态码 %d）" % (number, status), status=status)
    terms, any_terms = [], []
    for row in data.get("productIndications") or []:
        if not isinstance(row, dict):
            continue
        found = [str(t).strip() for t in row.get("terms") or [] if str(t).strip()]
        any_terms = any_terms or found
        if str(row.get("language") or "").lower() == "en":
            terms = found
    terms = terms or any_terms  # 没有英文的就用它给的第一种语言
    views = [v for v in data.get("views") or [] if isinstance(v, dict)]
    return {"title": "; ".join(dict.fromkeys(terms))[:200], "views": len(views)}


def view(number: str, order: int, dest, opener=None) -> bool:
    """下载第 order 个视图。失败返回 False，不抛。"""
    try:
        status, headers, raw = _get("/designs/%s/views/%d" % (number, order), "*/*", opener)
    except http.SourceError:
        return False
    kind = next((str(v) for k, v in headers.items() if k.lower() == "content-type"), "")
    if status != 200 or not raw or not kind.lower().startswith("image/"):
        return False
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(raw)
    return True
