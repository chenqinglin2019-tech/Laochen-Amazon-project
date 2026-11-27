"""常见维权方清单的对照（纯程序）：AI 列出的风险假设或页面文字里出现清单上的名字、图案时，点名权利人。"""
from __future__ import annotations

import json
import re
from pathlib import Path

LIST_FILE = Path(__file__).resolve().parent / "data" / "enforcers.json"


def load(path: Path = None) -> list:
    try:
        data = json.loads((path or LIST_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return [e for e in data.get("entries") or [] if isinstance(e, dict) and e.get("owner") and isinstance(e.get("aliases"), list)]


def _hit(alias: str, text: str) -> bool:
    alias = alias.strip().lower()
    if not alias:
        return False
    if re.search(r"[a-z]", alias):  # 英文按整词比，免得 "mario" 命中 "marionette"
        return re.search(r"(?<![a-z0-9])%s(?![a-z0-9])" % re.escape(alias), text) is not None
    return alias in text


def page_aliases(entry: dict) -> list:
    """对页面文字只用不会误伤的词：两个词以上的、中文的，以及条目里点名的独特单词（page_words）。
    像 stitch、peanuts、marvel 这种日常用词，只在 AI 已经把它当成图案或角色列出来时才算。"""
    distinct = {str(w).lower() for w in entry.get("page_words") or []}
    return [a for a in entry["aliases"] if " " in str(a).strip() or not re.search(r"[a-z]", str(a).lower()) or str(a).lower() in distinct]


def match(text: str, entries: list = None, page: bool = False) -> list:
    """返回在这段文字里命中的清单条目（每个权利人最多一条），带上命中的那个词。page=True 表示这是页面文字。"""
    text = (text or "").lower()
    hits = []
    for entry in entries if entries is not None else load():
        word = next((a for a in (page_aliases(entry) if page else entry["aliases"]) if _hit(str(a), text)), None)
        if word:
            hits.append(dict(entry, matched=word))
    return hits


def apply(hypotheses: list, page_text: str, entries: list = None) -> list:
    """给 AI 的风险假设补上清单里的权利人；页面文字里直接出现清单名字而 AI 没列的，补一条。返回新的假设清单。"""
    entries = entries if entries is not None else load()
    out, named = [], set()
    for item in hypotheses:
        item = dict(item)
        # 名字是 AI 认定的图案或角色，对照全部别名；说明、检索词和它写的权利人里只找独特的词
        blob = " ".join([str(item.get("owner", "")), str(item.get("reason", "")), " ".join(str(t) for t in item.get("search_terms") or [])])
        hits = match(str(item.get("name", "")), entries) or match(blob, entries, page=True)
        hits = hits or [e for e in entries if str(item.get("owner") or "").strip().lower() == e["owner"].lower()]
        if hits:
            hit = hits[0]
            item["watchlist"] = True
            item["watch_marks"] = [str(m) for m in hit.get("marks") or []]
            item["watch_note"] = "常见维权方清单命中「%s」：%s（%s）%s" % (hit.get("matched", hit["owner"]), hit["owner"], hit.get("rights", ""),
                                                           "；" + hit["note"] if hit.get("note") else "")
            if not str(item.get("owner") or "").strip():
                item["owner"] = hit["owner"]
            named.add(hit["owner"])
        out.append(item)
    for hit in match(page_text, entries, page=True):
        if hit["owner"] in named:
            continue
        out.append({"kind": "文字", "name": hit["matched"], "owner": hit["owner"],
                    "reason": "页面文字里出现了「%s」" % hit["matched"], "search_terms": [hit["matched"]], "watchlist": True,
                    "watch_marks": [str(m) for m in hit.get("marks") or []],
                    "watch_note": "常见维权方清单命中「%s」：%s（%s）%s" % (hit["matched"], hit["owner"], hit.get("rights", ""),
                                                                "；" + hit["note"] if hit.get("note") else "")})
        named.add(hit["owner"])
    return out
