"""日本商标的人工核对。日本没有可以合规地用程序按文字检索商标的来源（J-PlatPat 禁止程序自动访问，
WIPO 品牌库禁止自动查询，Signa 还没有日本），所以程序只做三件事：挑出要查的词、对照内置词表提醒、
给出人工打开的检索链接。报告里商标这一类写"未检索"，不写"低"。"""
from __future__ import annotations

import json
import re
import unicodedata
import urllib.parse
from pathlib import Path

LIST_FILE = Path(__file__).resolve().parent / "data" / "jp_marks.json"
WIPO_SEARCH = "https://branddb.wipo.int/en/similarname/results"
JPLATPAT = "https://www.j-platpat.inpit.go.jp/"
MAX_WORDS = 8
SOURCE = "人工核对（日本商标）"
WHY_NOT = "日本商标没有可以合规地用程序按文字检索的来源（J-PlatPat 禁止程序自动访问，WIPO 品牌库禁止自动查询，Signa 还没有日本的商标库），未检索"


def load(path: Path = None) -> list:
    try:
        data = json.loads((path or LIST_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return [e for e in data.get("entries") or [] if isinstance(e, dict) and e.get("term")]


def clean(word) -> str:
    """一个要查的词：全角半角统一，去掉括号、引号这类符号，原文字（日语、英文）保留。"""
    text = unicodedata.normalize("NFKC", str(word or ""))
    text = re.sub(r"[\"'“”‘’「」『』【】()\[\]{}<>《》®™©]", " ", text)
    return re.sub(r"\s+", " ", text).strip(" ・,，、。:：;；")[:30]


def _key(word: str) -> str:
    return clean(word).casefold()


def _hit(alias: str, text: str) -> bool:
    alias = clean(alias).casefold()
    if not alias:
        return False
    if re.search(r"[a-z]", alias):  # 英文按整词比
        return re.search(r"(?<![a-z0-9])%s(?![a-z0-9])" % re.escape(alias), text) is not None
    return alias in text


def find_entry(word: str, entries: list):
    key = _key(word)
    for entry in entries:
        if any(_key(a) == key for a in [entry["term"]] + list(entry.get("aliases") or [])):
            return entry
        if not re.search(r"[a-z]", key) and _key(entry["term"]) in key:  # 日语复合词里包含词表上的词（スクイーズ保護袋）
            return entry
    return None


def page_hits(text: str, entries: list) -> list:
    """页面文字里出现的词表条目。"""
    text = unicodedata.normalize("NFKC", text or "").casefold()
    return [e for e in entries if any(_hit(a, text) for a in [e["term"]] + list(e.get("aliases") or []))]


def wipo_link(word: str) -> str:
    """WIPO 品牌库的检索结果页（品牌名"包含这个词"）。格式照 2026-11-27 人工查询时留下的真实网址。只给人点开，程序不访问。"""
    structure = {"_id": "q1", "boolean": "AND", "bricks": [{"_id": "q2", "key": "brandName", "value": word, "strategy": "Simple"}]}
    shape = json.dumps(structure, ensure_ascii=False, separators=(",", ":"))
    return "%s?sort=score%%20desc&start=0&rows=30&asStructure=%s&fg=_void_" % (WIPO_SEARCH, urllib.parse.quote(shape, safe=":,"))


def links(word: str) -> list:
    return [{"label": "WIPO 品牌库（已填好这个词，筛选 Country of filing: Japan）", "url": wipo_link(word)},
            {"label": "J-PlatPat（进去点 商標 → 商標検索）", "url": JPLATPAT}]


def page_text(product: dict) -> str:
    return "\n".join([str(product.get("title") or "")] + [str(b) for b in product.get("bullets") or []] + [str(product.get("description") or "")])


def collect(understanding: dict, product: dict, terms: list, blind: bool, entries: list = None) -> tuple:
    """要人工核对的词，按这个先后：产品本体上的文字和风险假设里的名字 → 拟用标题和文案里的词（产品理解挑的）
    → 页面文字里出现的词表上的词。返回 (词清单，排不进去的词)。"""
    entries = load() if entries is None else entries
    found = []

    def add(word, why):
        word = clean(word)
        if len(word) < 2 or any(_key(item["term"]) == _key(word) for item in found):
            return
        found.append({"term": word, "why": why})

    understanding = understanding or {}
    if not blind:
        for word in understanding.get("text_on_product") or []:
            add(word, "产品本体上的文字")
        for item in understanding.get("hypotheses") or []:
            for word in list(item.get("watch_marks") or []) + list(item.get("search_terms") or [])[:1]:
                add(word, "风险假设：%s" % (item.get("name") or ""))
    for word in terms or []:  # 已经按商标检索的规则挑出来的拉丁字母词（和上面多半重复，重复的不再加）
        add(word, "产品上的文字或风险假设")
    if not blind:
        for word in understanding.get("listing_marks") or []:
            add(word, "拟用标题或文案里的词")
    for entry in page_hits(page_text(product), entries):
        if not any(find_entry(item["term"], entries) is entry for item in found):  # 已经有含这个词的（スクイーズ保護袋）就不再单列
            add(entry["term"], "页面文字里出现")
    for item in found:
        entry = find_entry(item["term"], entries)
        if entry:
            item.update(owner=entry.get("owner", ""), plain=entry.get("plain", ""), note=entry.get("note", ""), source=entry.get("source", ""))
        item["links"] = links(item["term"])
    return found[:MAX_WORDS], [item["term"] for item in found[MAX_WORDS:]]
