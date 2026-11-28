"""美国专利局 Patent Public Search 的检索接口：官方、免费、当天授权当天可查。不需要 key。
一单发四五条查询，另按页取几十张外观附图。这是公开检索网站自己用的接口，官方没有公布使用条款，量大时可能被限。"""
from __future__ import annotations

import re
import threading
import urllib.parse

from .. import numbers
from . import http

BASE = "https://ppubs.uspto.gov/api"
HEADERS = {"Origin": "https://ppubs.uspto.gov", "Referer": "https://ppubs.uspto.gov/pubwebapp/"}
# 按页取附图（PNG）。2026-11-26 晚上专利局把这个接口从 image-ppubs.uspto.gov 换到了下面第一个地址（老地址从那以后一律回 403；
# 新地址是从它网页的脚本里读出来的，2026-11-27 实测一页 1 秒多）。它没有公开文档，哪天再换，先试第一个、不行试下一个。
IMAGE_URLS = ["https://ppubs.uspto.gov/api/image/convert",
              "https://image-ppubs.uspto.gov/dirsearch-public/image-conversion/convert"]
IMAGE_URL = IMAGE_URLS[0]


IMAGE_DENY_LIMIT = 6  # 取图接口连着被拒这么多次，就认定它这会儿不给图
# 一单一个进程：这个状态整个进程共用（补材料、补图再看、深查取材料各开各的会话）。
# 连着被拒到 IMAGE_DENY_LIMIT 次，这一次运行就不再去试，免得白等。
# denied：连着被拒了几次；refused：这一次运行里一共被拒了几次；use：现在用第几个地址；ok：这一次运行里取成了几张（只是记个数）
IMAGE_STATE = {"denied": 0, "blocked": False, "refused": 0, "use": 0, "ok": 0}


def image_blocked() -> bool:
    return IMAGE_STATE["blocked"]


class Session:
    """一次任务开一个会话，后面的查询共用。"""

    def __init__(self, opener=None):
        self.opener = opener
        self.token = ""
        self.case_id = None
        self.failed = ""  # 开过一次没开成就记下原因，后面不再反复去开

        self._lock = threading.Lock()

    def open(self) -> None:
        """几个线程共用一个会话：只开一次；开不成的话后面的调用直接报同一个原因。"""
        with self._lock:
            if self.token:
                return
            if self.failed:
                raise http.SourceError(self.failed)
            try:
                status, headers, data = http.fetch_json(BASE + "/users/me/session", "POST", HEADERS, body=-1, timeout=30, opener=self.opener)
            except http.SourceError as exc:
                self.failed = "美国专利局检索接口" + exc.message
                raise http.SourceError(self.failed, kind=exc.kind)
            token = next((v for k, v in headers.items() if k.lower() == "x-access-token"), "")
            if status != 200 or not token or not isinstance(data, dict) or not isinstance(data.get("userCase"), dict):
                self.failed = "美国专利局检索接口没有给出会话（状态码 %d）" % status
                raise http.SourceError(self.failed, status=status)
            self.case_id, self.token = data["userCase"].get("caseId"), token

    def search(self, query: str, limit: int = 100, sort: str = "date_publ desc", database: str = "USPAT") -> dict:
        """返回 {"total": 命中总数, "docs": [整理后的记录]}。database：USPAT 是授权的，US-PGPUB 是申请公开。"""
        if not self.token:
            self.open()
        body = {"start": 0, "pageCount": limit, "sort": sort, "docFamilyFiltering": "familyIdFiltering", "searchType": 1,
                "familyIdEnglishOnly": True, "familyIdFirstPreferred": "US-PGPUB", "familyIdSecondPreferred": "USPAT",
                "familyIdThirdPreferred": "FPRS", "showDocPerFamilyPref": "showEnglish", "queryId": 0, "tagDocSearch": False,
                "query": {"caseId": self.case_id, "hl_snippets": "2", "op": "OR", "q": query, "queryName": query, "highlights": "0",
                          "qt": "brs", "spellCheck": False, "viewName": "tile", "plurals": True, "britishEquivalents": True,
                          "databaseFilters": [{"databaseName": database, "countryCodes": []}], "searchType": 1,
                          "ignorePersist": True, "userEnteredQuery": query}}
        status, _headers, data = http.fetch_json(BASE + "/searches/searchWithBeFamily", "POST", dict(HEADERS, **{"X-Access-Token": self.token}),
                                                 body=body, timeout=40, opener=self.opener)
        if status == 429:
            raise http.SourceError("美国专利局检索接口说请求太频繁", kind="quota", status=status)
        if status != 200 or not isinstance(data, dict):
            raise http.SourceError("美国专利局检索接口返回状态码 %d" % status, status=status)
        if not isinstance(data.get("patents"), list) and not isinstance(data.get("numFound"), int):
            raise http.SourceError("美国专利局检索接口返回的内容不是检索结果", kind="format", status=status)
        docs = [doc for doc in (normalize(item) for item in data.get("patents") or [] if isinstance(item, dict)) if doc]
        return {"total": int(data.get("numFound") or len(docs)), "docs": docs}

    def page_image(self, location: str, page: int, dest, certain: bool = True) -> bool:
        """把一件专利的第 page 页（从 1 数）存成 PNG。location 是检索结果里给的存放位置。失败返回 False。
        certain：这一页确定存在（第一张附图页，或者在专利局写明的页数范围内）。不确定的页（页数未知时往后探的）回 404 是正常的，
        不算"接口不给图"。"""
        if not re.fullmatch(r"[A-Za-z0-9/_\-]{6,80}", location or "") or not 1 <= page <= 400:
            return False
        if IMAGE_STATE["blocked"]:
            return False
        status, raw, answer = 0, b"", None
        for attempt in (1, 2):
            try:
                if not self.token:
                    self.open()
            except http.SourceError:
                return False
            first = IMAGE_STATE["use"] if 0 <= IMAGE_STATE["use"] < len(IMAGE_URLS) else 0
            order = list(range(first, len(IMAGE_URLS))) + list(range(0, first))  # 上次哪个地址能用就从哪个开始；被拒（403、404）换下一个
            status, raw, answer = 0, b"", None
            for index in order:
                url = "%s?%s" % (IMAGE_URLS[index], urllib.parse.urlencode({"url": "%s/%08d.tif" % (location, page), "requestToken": self.token}))
                try:
                    status, _headers, raw = http.fetch(url, headers=HEADERS, timeout=40, opener=self.opener)
                except http.SourceError:
                    if answer is None:
                        return False  # 头一个地址就连不上：不算被拒
                    break             # 后备的地址连不上：按前面那个地址的回答算
                answer = status if answer is None else answer  # 记住最先试的那个地址怎么回的
                if status == 200 and raw.startswith(b"\x89PNG"):
                    IMAGE_STATE["use"] = index
                    break
                if status not in (403, 404):
                    break
            if answer == 401 and attempt == 1:  # 会话的 token 不认了（开了太久）：重开一次会话再试
                self.token = ""
                continue
            break
        if not (status == 200 and raw.startswith(b"\x89PNG")):
            # 403 是明确不给。404 要看这一页是不是确定存在：确定存在却说没有，多半是接口又换了地址；不确定的页没有是正常的
            if answer == 403 or (answer == 404 and certain):
                IMAGE_STATE["denied"] += 1
                IMAGE_STATE["refused"] += 1
                if IMAGE_STATE["denied"] >= IMAGE_DENY_LIMIT:
                    IMAGE_STATE["blocked"] = True
            return False
        IMAGE_STATE["denied"] = 0
        IMAGE_STATE["ok"] += 1
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(raw)
        return True


def _number(value) -> int:
    return int(value) if str(value if value is not None else "").isdigit() else 0


def _first(value) -> str:
    if isinstance(value, list):
        value = value[0] if value else ""
    return "" if value is None else str(value)


def normalize(item: dict):
    raw = _first(item.get("publicationReferenceDocumentNumber"))
    key = numbers.us_key(raw)
    kind = _first(item.get("kindCode")).upper()
    application = re.fullmatch(r"(?:US)?(\d{11})", re.sub(r"[^A-Za-z0-9]", "", raw).upper())
    if not key and not (application and kind.startswith("A")):
        return None
    design = bool(key) and key.startswith("D")
    number = numbers.us_display(raw, kind) if key else "US%s%s" % (application.group(1), kind or "A1")
    classes = [c for c in [_first(item.get("mainClassificationCode"))] + re.split(r"[;,]\s*", _first(item.get("uspcFullClassificationFlattened"))) if c]
    return {
        "right_type": "design" if design else "patent",
        "number": number,
        "title": re.sub(r"<[^>]+>", "", _first(item.get("inventionTitle"))).strip(),
        "owner": _first(item.get("assigneeName")) or _first(item.get("applicantName")),
        "filing_date": _first(item.get("applicationFilingDate"))[:10],
        "grant_date": _first(item.get("datePublished"))[:10],
        "url": "https://patents.google.com/patent/%s/en" % number,
        "classes": list(dict.fromkeys(classes))[:6],
        "cpc": [c for c in re.split(r"[;,]\s*", _first(item.get("cpcInventiveFlattened"))) if c][:6],
        "image_location": _first(item.get("imageLocation")),
        "pages": _number(item.get("pageCount")),
        "figures_from": _number(item.get("drawingsStart")),  # 附图从第几页开始、到第几页（引用文献多的，第 2 页还是文字）
        "figures_to": _number(item.get("drawingsEnd")),
        "app_number": re.sub(r"[^0-9]", "", _first(item.get("applicationNumber"))),
        "pending": not key,  # 申请公开（还没授权）
        "source": "美国专利局",
    }


def phrase(words: str) -> str:
    """把一个英文叫法写成这个接口的"相邻词"语法：单词之间 ADJ，较长的词截去词尾以兼容单复数和 -ing。"""
    parts = []
    for word in re.findall(r"[A-Za-z0-9]+", words or ""):
        word = word.lower()
        if word.isdigit() or len(word) <= 3:
            parts.append(word)
        else:
            # 去掉常见词尾再截词，兼容单复数和 -ing；词干至少留 4 个字母，ss 结尾的词（glass、press）不动
            stem = word if word.endswith("ss") else re.sub(r"(ing|ers|er|es|s)$", "", word)
            parts.append((stem if len(stem) >= 4 else word) + "$4")
    return "(%s)" % " ADJ ".join(parts) if len(parts) > 1 else (parts[0] if parts else "")
