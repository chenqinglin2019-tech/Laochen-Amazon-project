"""Google Patents 的公开页面（免费）：按号码取一件专利的状态、到期日、权利要求、附图、分类和相似文献。"""
from __future__ import annotations

import html as html_lib
import re

from . import http

URL = "https://patents.google.com/patent/%s/en"


def _text(fragment: str) -> str:
    return re.sub(r"\s+", " ", html_lib.unescape(re.sub(r"<[^>]+>", " ", fragment or ""))).strip()


def _prop(page: str, name: str) -> str:
    match = re.search(r'itemprop="%s"[^>]*>(.*?)</' % re.escape(name), page, re.S)
    return _text(match.group(1)) if match else ""


def fetch(number: str, opener=None) -> dict:
    """取不到（没收录、被拦）抛 SourceError。"""
    if not re.fullmatch(r"[A-Z]{2}[A-Z0-9]{4,16}", number or ""):
        raise http.SourceError("专利号写法不对：%s" % number, kind="format")
    status, _headers, raw = http.fetch(URL % number, timeout=30, opener=opener)
    if status == 404:
        raise http.SourceError("Google Patents 还没有收录 %s" % number, kind="missing", status=404)
    if status != 200:
        raise http.SourceError("Google Patents 返回状态码 %d" % status, status=status)
    page = parse(raw.decode("utf-8", "replace"), number)
    if not page["title"] and not page["legal_status"]:  # 200 但不是专利页（同意页、拦截页）
        raise http.SourceError("Google Patents 返回的不是 %s 的专利页" % number, kind="format", status=status)
    return page


# 机器翻译的页面（日本、德国等原文不是英文的）权利要求是另一种写法，从属项没有标记，只能看文字里有没有引用别的权利要求
REFERS = re.compile(r"\b(?:claims?|anspr[uü]ch(?:e|en)?|revendications?|rivendicazion[ei]|reivindicaci(?:ón|ones))\s*\d"
                    r"|\b(?:preceding|previous|foregoing|above|aforementioned)\s+claims?\b|\b(?:any|one)\s+of\s+(?:the\s+)?claims\b"
                    r"|\bvorhergehenden\s+anspr|\brevendications\s+pr[ée]c[ée]dentes|請求項\s*[0-9０-９]", re.I)


def translated_claims(body: str) -> list:
    """<claim num="1"><claim-text><span class="notranslate"><span class="google-src-text">原文</span>译文</span>…：去掉原文留译文。"""
    out = []
    for match in re.finditer(r'<claim\b[^>]*\bnum="0*(\d+)"[^>]*>(.*?)</claim>', body, re.S):
        text = _text(re.sub(r'<span class="google-src-text">.*?</span>', " ", match.group(2), flags=re.S))
        if not text:
            continue
        if out and REFERS.search(text[:400]):  # 第一项总是独立的；后面的开头就引用别的权利要求的是从属项
            continue
        out.append({"number": int(match.group(1)), "text": text[:3000]})
    return out


def parse(page: str, number: str = "") -> dict:
    status = re.search(r'itemprop="legalStatusIfi"[^>]*>\s*<span itemprop="status">(.*?)</span>', page, re.S)
    expiry = re.search(r'<time itemprop="date" datetime="([\d-]+)">[^<]*</time>\s*<span itemprop="title">(?:Anticipated|Adjusted) expiration', page)
    images = []
    for block in re.findall(r'<li itemprop="images"[^>]*>(.*?)</li>', page, re.S):
        full = re.search(r'itemprop="full" content="([^"]+)"', block) or re.search(r'itemprop="thumbnail" src="([^"]+)"', block)
        if full and full.group(1) not in images:
            images.append(full.group(1))
    independent = []
    claims = re.search(r'<section itemprop="claims".*?</section>', page, re.S)
    if claims:
        body = claims.group(0)
        # 从属权利要求的块带 claim-dependent；其余编号的就是独立权利要求
        mark = r'<div id="(?:CLM-|c-[a-z]{2}-\d+-)'  # 美国页是 CLM-00001，欧洲专利页是 c-en-01-0001
        for match in re.finditer(mark + r'0*(\d+)"[^>]*class="claim">(.*?)(?=' + mark + r'\d+"|</section>)', body, re.S):
            start = match.start()
            if "claim-dependent" in body[max(0, start - 60):start]:
                continue
            text = _text(match.group(2))
            if text and int(match.group(1)) not in {c["number"] for c in independent}:  # 欧洲专利可能英、德、法各列一遍：同一项只要第一遍
                independent.append({"number": int(match.group(1)), "text": text[:3000]})
        if not independent:
            independent = translated_claims(body)
    similar = []
    for row in re.findall(r'<tr itemprop="similarDocuments"[^>]*>(.*?)</tr>', page, re.S):
        found = re.search(r'itemprop="publicationNumber">([^<]+)<', row)
        title = re.search(r'itemprop="title">(.*?)</', row, re.S)
        if found:
            similar.append({"number": found.group(1).strip(), "title": _text(title.group(1)) if title else ""})
    codes = [c for c in re.findall(r'itemprop="Code">([^<]+)<', page) if len(c) >= 6]
    abstract = re.search(r'<section itemprop="abstract".*?</section>', page, re.S)
    title = re.search(r"<title>\s*[A-Z0-9]+\s*-\s*(.*?)\s*-\s*Google Patents", page, re.S)
    return {
        "number": number,
        "title": _text(title.group(1)) if title else "",
        "owner": _prop(page, "assigneeCurrent") or _prop(page, "assigneeOriginal"),
        "legal_status": _text(status.group(1)) if status else "",
        "expiry": expiry.group(1) if expiry else "",
        "filing_date": (re.search(r'itemprop="filingDate" datetime="([\d-]+)"', page) or [None, ""])[1],
        "grant_date": (re.search(r'itemprop="publicationDate" datetime="([\d-]+)"', page) or [None, ""])[1],
        "abstract": _text(re.sub(r"<h2>.*?</h2>", "", abstract.group(0), flags=re.S))[:800] if abstract else "",
        "independent_claims": independent,
        "images": images,
        "cpc": list(dict.fromkeys(codes))[-8:],
        "similar": similar,
    }


STATUS_NAMES = {"active": "有效", "expired - fee related": "已失效（欠费）", "expired - lifetime": "已届满", "expired": "已失效",
                "abandoned": "已放弃", "withdrawn": "已撤回", "pending": "审查中", "ceased": "已终止"}


def status_name(raw: str) -> str:
    return STATUS_NAMES.get((raw or "").strip().lower(), raw or "")


def is_dead(raw: str) -> bool:
    return (raw or "").strip().lower().startswith(("expired", "abandoned", "withdrawn", "ceased"))
