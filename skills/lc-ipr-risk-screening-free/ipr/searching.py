"""真实的检索（R-004、R-013）：几路同时查，合并去重，按保护期筛掉过期的。

美国的发明和外观以美国专利局的公开检索接口为主（免费、当天授权当天可查），SerpApi 的 Google Patents 为辅（多一种排序，
带现行状态和代表图）；商标查 Signa；图案出处用主图以图搜图（Serper）；维权信号查网页（Serper）。
哪一路没查成都如实记下，不影响其他路。
"""
from __future__ import annotations

import json
import re
import threading
import time
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path

from . import config, jp_marks, numbers
from .sources import euipo, http, ppubs, serpapi, serper, signa

DESIGN_YEARS = 15
PATENT_YEARS = 20
PPUBS_DESIGN_LIMIT = 150
PPUBS_PATENT_LIMIT = 40
PPUBS_CLAIM_LIMIT = 20
PPUBS_CLASS_LIMIT = 40
TRADEMARK_TERMS = 5
# 每一路查的是哪类权利、是不是辅助来源（辅助来源没查成不算这类权利的缺口）
FOREIGN_DESIGN_KEEP = 40  # 外观每个部件最多留几件（日本意匠只有名单没有图，要人工看，宁多勿漏；2026-11-28 实测 20 件会漏掉排第 20 名以后的相关意匠）
WIDE_AT = 300             # 一条检索命中超过这么多件：收窄一次（标题里要有品名）
SERPAPI_BUDGET = 6        # 每单 SerpApi 最多用几次（用户 2026-11-28 同意每单 3~6 次）；主检索优先，补查用剩下的
MAX_PARTS = 2             # 最多按几个部件分开查
PENDING_YEARS = 8         # 已公开未授权的申请只列这么多年内申请的（更早的多半已经有了结论）
UTILITY_YEARS = 10        # 实用新型保护 10 年
PPUBS_PART_LIMIT = 40
PPUBS_APP_LIMIT = 30
JOB_ROUTES = {"foreign_patent": ("patent", False), "foreign_design": ("design", False), "us_parts": ("patent", False),
              "us_applications": ("patent", True), "design_title": ("design", False), "design_serpapi": ("design", True), "design_class": ("design", True),
              "patent_text": ("patent", False), "patent_claims": ("patent", True), "trademark": ("trademark", False),
              "lens": ("artwork", False), "enforcement": ("enforcement", True)}
LENS_KEEP = 30
ENFORCEMENT_KEEP = 8
STOP_WORDS = {"with", "for", "and", "the", "of", "a", "an", "in", "on", "to", "set", "pack", "pcs", "new"}


# ---------------- 检索词 ----------------
def name_phrases(names: list, core_terms: list = ()) -> list:
    """检索用的词组：先是核心品名（外观标题通常就这么短，如 "Badge reel"、"Cat teaser"），再是 3 到 4 个词的完整叫法。
    没有核心品名时，退而取每个叫法的最后两个词。"""
    def words_of(text):
        words = [w for w in re.findall(r"[A-Za-z][A-Za-z0-9\-]*", str(text)) if w.lower() not in STOP_WORDS]
        return [w for part in words for w in part.split("-") if w]

    phrases = [" ".join(words_of(term)[:2]) for term in core_terms or [] if words_of(term)]
    for name in names or []:
        words = words_of(name)
        if not core_terms and len(words) >= 2:
            phrases.append(" ".join(words[-2:]))
        if 3 <= len(words) <= 4:
            phrases.append(" ".join(words))
    seen, out = set(), []
    for phrase in phrases:
        key = ppubs.phrase(phrase)
        if key and key not in seen:
            seen.add(key)
            out.append(phrase)
    return out[:6]


def parts_of(understanding: dict, blind: bool, phrases: list, local: list) -> list:
    """按部件分开的检索词。产品理解给了 parts 就用它；旧格式或理解没成时，整件当一个部件。"""
    parts = []
    for item in ([] if blind else understanding.get("parts") or []):
        if isinstance(item, dict) and (item.get("terms") or item.get("local_terms")):
            parts.append({key: [str(x) for x in item.get(key) or [] if str(x).strip()]
                          for key in ("terms", "local_terms", "design_names", "features", "local_features")})
            parts[-1]["name"] = str(item.get("name") or "")
    if not parts and (phrases or local):
        parts = [{"name": "", "terms": list(phrases), "local_terms": list(local), "design_names": [],
                  "features": [] if blind else list(understanding.get("features") or [])[:4], "local_features": []}]
    return parts[:MAX_PARTS]


def cjk_ok(word: str, least: int) -> bool:
    """日文、中文这类不用空格分词的词：太短的（「袋」「孔」）在全文里什么都能命中，不拿去检索。"""
    return bool(re.search(r"[A-Za-z]", word)) or len(re.sub(r"\s", "", word)) >= least


def part_words(part: dict) -> tuple:
    """(英文品名, 当地品名, 结构词)。英文一律小写：大写的 OR、NOT 会被当成检索语法。
    当地品名至少 3 个字、当地结构词至少 2 个字（2026-11-28 实测：混进「収納袋」「孔」这类，日本检索一下子几千上万件）。"""
    english = list(dict.fromkeys(plain(t).lower() for t in part.get("terms") or [] if plain(t)))
    local = list(dict.fromkeys(w for w in (local_term(t) for t in part.get("local_terms") or []) if w and cjk_ok(w, 3)))
    features = list(dict.fromkeys([plain(f).lower() for f in part.get("features") or [] if plain(f)]
                                  + [w for w in (local_term(f) for f in part.get("local_features") or []) if w and cjk_ok(w, 2)]))
    return english, local, features[:8]


def local_feature_words(part: dict) -> set:
    """产品理解给的当地结构词（按 part_words 的同一套清洗）。德法意西的当地词也是拉丁字母，不能靠"有没有英文字母"来分。"""
    return {w for w in (local_term(f) for f in part.get("local_features") or []) if w and cjk_ok(w, 2)}


def only_local(features: list, local_features=None) -> list:
    """有当地结构词就只留当地的；没给当地结构词（老的产品理解）时按"不含英文字母"分（只对日文、中文有效）。"""
    if local_features is not None:
        return [f for f in features if f in local_features] or features
    return [f for f in features if not re.search(r"[a-z]", f)] or features


def foreign_words(english: list, local: list, features: list, local_features=None) -> tuple:
    """美国以外的检索用哪些词：有当地叫法就只用当地的（英文词会匹配机器翻译的全文，2026-11-28 实测命中数翻几十倍），
    结构词同理；没有当地叫法时才用英文。"""
    words = local or english
    if local:
        features = only_local(features, local_features)
    return words, inside_removed(words, features)


def inside_removed(words: list, features: list) -> list:
    """结构词如果每个品名里都有（「チャック」之于「チャック付き袋」「チャック袋」），"必须同时出现"就等于没加：去掉。
    只在部分品名里出现的留着——对其余品名它照样起作用（2026-11-28 实测：全去掉会漏掉「吊り下げ袋」这一类）。"""
    return [f for f in features if not (words and all(f.lower() in w.lower() for w in words))]


def quoted_group(words: list) -> str:
    words = [w for w in dict.fromkeys(words) if w]
    return "(%s)" % " OR ".join('"%s"' % w for w in words) if words else ""


def part_query(words: list, features: list, narrow: bool = False) -> str:
    """品名一组、结构词一组，两组都要出现（Google Patents 里空格就是"并且"）。narrow：品名必须出现在标题里。"""
    group = quoted_group(words)
    if narrow:
        group = "TI=" + group
    return (group + " " + quoted_group(features)).strip() if features else group


def fallback_names(product: dict) -> list:
    """产品理解没成时：取标题里 for / with / 逗号之前那一段的最后三个词当叫法
    （"2-Pack Rolling Grill Basket for …" → "Rolling Grill Basket"；带连字符的词如 Heavy-Duty 保留）。"""
    head = re.split(r"[,|(]|\s[\-–—]\s|\s(?:for|with|w/)\s", str(product.get("title") or ""), 1, flags=re.I)[0]
    head = re.sub(r"^\s*\d+[\s\-]*(?:pack|packs|pcs|pc|pieces|piece|count|ct)\b", " ", head, flags=re.I)
    words = [w for w in re.findall(r"[A-Za-z][A-Za-z0-9]*", head) if w.lower() not in STOP_WORDS]
    return [" ".join(words[-3:])] if len(words) >= 2 else []


def ppubs_any(phrases: list) -> str:
    return "(%s)" % " OR ".join(ppubs.phrase(p) for p in phrases)


def plain(term) -> str:
    """把一个词整理成能拿去查的样子：去掉重音符号（Pokémon → Pokemon），只留英文、数字和常见符号。"""
    text = unicodedata.normalize("NFKD", str(term or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", re.sub(r"[^A-Za-z0-9 .&'\-]", " ", text)).strip()


def local_term(term) -> str:
    """当地语言的叫法：原样保留文字（德语的变音、日语的假名和汉字），只去掉会被当成检索语法的符号。"""
    text = re.sub(r"[\"“”„«»()\[\]{}:;,=*?~^|<>]", " ", unicodedata.normalize("NFKC", str(term or "")))
    words = [w.lstrip("-") for w in text.split()]
    words = [w.lower() if w in ("OR", "AND", "NOT", "NEAR", "ADJ", "WITH", "SAME") else w for w in words if w.lstrip("-")]
    return " ".join(words)[:40]


def foreign_script(understanding: dict) -> list:
    """产品本体上的文字里不是拉丁字母的（日文、中文…）：现有的商标库按拉丁字母查，这些查不了。
    只看 text_on_product：风险假设的名字是 AI 用中文起的（"骷髅头"），不是产品上的字。"""
    words = list(understanding.get("text_on_product") or [])
    out = []
    for word in words:
        word = re.sub(r"\s+", " ", str(word or "")).strip()
        if word and not re.search(r"[A-Za-z]", word) and re.search(r"[^\W\d_]", word) and word not in out:
            out.append(word[:20])
    return out[:5]


def trademark_terms(understanding: dict, brand: str = "", listing: bool = False) -> tuple:
    """要去商标库查的词，按这个先后：清单上权利人的主要商标 → 产品本体上的文字 → AI 给的名字和检索词
    → （资料入口时）拟用标题和文案里的词。
    默认按自有品牌上架：产品上的文字、AI 给的名字里如果只是原卖家的品牌，不查（换成自己的品牌就没有了）；
    但清单上权利人的商标照查，哪怕它和原卖家品牌同名。返回 (要查的词，最多 TRADEMARK_TERMS 个；排不进去的词；因为是原卖家品牌而没查的词)。"""
    hypotheses = understanding.get("hypotheses") or []
    firm = [mark for item in hypotheses for mark in item.get("watch_marks") or []]
    soft = list(understanding.get("text_on_product") or [])
    for item in hypotheses:
        soft += [item.get("name") or ""] + list(item.get("search_terms") or [])[:1]
    if listing:  # 资料入口：标题和文案是卖家自己要用的，里面当成商品名、卖点名的词也要查
        soft += list(understanding.get("listing_marks") or [])
    own = plain(brand).lower()
    seen, out, branded = set(), [], []
    for term, strict in [(t, False) for t in firm] + [(t, True) for t in soft]:
        term = plain(term)
        if not (2 <= len(term) <= 40 and re.search(r"[A-Za-z]", term)) or term.lower() in seen:
            continue
        if strict and own and term.lower() == own:
            if term.lower() not in {b.lower() for b in branded}:
                branded.append(term)
            continue
        seen.add(term.lower())
        out.append(term)
    return out[:TRADEMARK_TERMS], out[TRADEMARK_TERMS:], branded


# ---------------- 各路检索 ----------------
class Searcher:
    def __init__(self, task, env: dict, usage, say=print, today: date = None, opener=None):
        self.task, self.env, self.usage, self.say = task, env or {}, usage, say
        self.today = today or date.today()
        self.opener = opener
        self.records, self.docs, self.notes = [], [], []
        self.lens, self.enforcement = [], []
        self.manual = []  # 日本这类商标只能人工核对的：要查的词和链接
        self.retry_left = 0  # 这一单还能拿来补查（收窄或放宽）的 SerpApi 次数
        self.serp_used = 0   # 这一单 SerpApi 实际发了几次（硬上限 SERPAPI_BUDGET）
        self.session = ppubs.Session(opener)
        euipo.configure(self.env)
        self.keys, self.why = {}, {}  # 这次能用的 key；不能用的那几路各是什么原因
        self._count = 0
        self._lock = threading.Lock()  # 几路检索同时跑，记账要排队

    def record(self, route: str, source: str, query: str, started: float, docs=None, total=None, error=None, skipped: str = "",
               route_name: str = "", optional: bool = False, empty: bool = False, note: str = "") -> dict:
        """optional=True 表示这一路是锦上添花的（辅助来源、顺着分类号多查的一轮）：它没查成或没取全，不算这类权利的缺口。"""
        with self._lock:
            self._count += 1
            number = self._count
        row = {"id": "S%d" % number, "route": route, "route_name": route_name, "source": source, "query": query,
               "seconds": round(time.monotonic() - started, 1), "optional": optional, "truncated": False}
        if empty:
            row["empty"] = True  # 没有要查的词，所以没有发请求：定级时不能拿它当"查过了"的依据去撑总评
        if skipped:
            row.update(status="skipped", reason=skipped, count="")
        elif error is not None:
            row.update(status="failed", reason=config.redact(error), count="")
        else:
            got = len(docs or [])
            cut = bool(total and total > got)
            row.update(status="ok", reason=note, truncated=cut, count=str(got) if not cut else "%d（共命中 %d 件，只取了前 %d 件）" % (got, total, got))
            if note and not docs:  # 被替换掉的那一次：写真实命中数，不写"0 件"
                row.update(count="共命中 %s 件（已换下一条检索式）" % (total if total is not None else "?"), truncated=False)
        with self._lock:
            self.records.append(row)
        self.keep(row, docs, total)
        return row

    RAW_FIELDS = ("number", "title", "right_type", "owner", "filing_date", "grant_date", "legal_status", "kind", "pending", "via", "url")

    def keep(self, row: dict, docs, total) -> None:
        """每条检索留一份档：检索式、状态、命中数和返回的号码清单，写在任务目录的 raw/ 里，事后能复查、能复现。留档失败不影响检索。"""
        try:
            folder = self.task.dir / "raw"
            folder.mkdir(parents=True, exist_ok=True)
            record = dict(row, total=total, docs=[{k: d.get(k) for k in self.RAW_FIELDS if d.get(k) not in (None, "", [])} for d in docs or []
                                                  if isinstance(d, dict)])
            (folder / ("search-%s.json" % row["id"])).write_text(config.redact(json.dumps(record, ensure_ascii=False, indent=1)), encoding="utf-8")
        except (OSError, TypeError, ValueError):
            pass

    def guarded(self, route: str, source: str, query: str, call, route_name: str = "", optional: bool = False):
        """跑一条检索：成了返回结果，没成记下原因返回 None。任何一路出错都不影响别的路。"""
        started = time.monotonic()
        try:
            result = call()
        except http.SourceError as exc:
            self.record(route, source, query, started, error=exc.message, route_name=route_name, optional=optional)
            return None
        except Exception as exc:  # 意料之外的错误也只算这一路没查成
            self.record(route, source, query, started, error="程序出错（%s）" % type(exc).__name__, route_name=route_name, optional=optional)
            return None
        with self._lock:
            self.usage.add_source_call(source)
        return result, started

    # ---- 美国专利局 ----
    def ppubs_query(self, route: str, query: str, limit: int, sort: str, via: str, optional: bool = False, database: str = "USPAT",
                    out: list = None) -> list:
        """out 给了的话，把这一条的检索记录和命中总数放进去（收窄时要回头改它）。"""
        source = "美国专利局" if database == "USPAT" else "美国专利局（申请公开）"
        got = self.guarded(route, source, query, lambda: self.session.search(query, limit, sort, database), optional=optional)
        if got is None:
            return []
        result, started = got
        docs = [dict(doc, via=via) for doc in result["docs"] if doc["right_type"] == route]
        row = self.record(route, source, query, started, docs=docs, total=result["total"], optional=optional)
        if out is not None:
            out.extend([row, result["total"]])
        return docs

    def design_by_title(self, phrases: list) -> list:
        since = numbers.years_ago(DESIGN_YEARS, self.today)
        query = '%s.ti. AND S.kd. AND @pd>="%s"' % (ppubs_any(phrases), since)
        return self.ppubs_query("design", query, PPUBS_DESIGN_LIMIT, "date_publ desc", "title")

    def design_by_class(self, title_hits: list, phrases: list) -> list:
        """顺着分类号再查一轮：取标题命中的外观里最常见的分类号，查同一分类下标题沾边的外观。"""
        counts = {}
        for doc in title_hits:
            for code in doc.get("classes", [])[:1]:
                counts[code] = counts.get(code, 0) + 1
        if not counts:
            return []
        code = max(counts, key=counts.get)
        words = sorted({w.lower() for p in phrases for w in p.split() if len(w) > 3})
        if not words:
            return []
        since = numbers.years_ago(DESIGN_YEARS, self.today)
        query = '"%s".ccls. AND (%s).ti. AND S.kd. AND @pd>="%s"' % (code, " OR ".join(ppubs.phrase(w) for w in words), since)
        return self.ppubs_query("design", query, PPUBS_CLASS_LIMIT, "date_publ desc", "class", optional=True)

    def patent_by_text(self, phrases: list, features: list = ()) -> list:
        since = numbers.years_ago(PATENT_YEARS, self.today)
        query = '%s.ti,ab. AND (B1 OR B2).kd. AND @pd>="%s"' % (ppubs_any(phrases), since)
        first = []
        docs = self.ppubs_query("patent", query, PPUBS_PATENT_LIMIT, "score desc", "text", out=first)
        features = [f for f in features if ppubs.phrase(f)]
        if first and first[1] > WIDE_AT and features:  # 命中太多：再查一条标题里有品名、并且出现结构词的（美国专利局的接口不计次）
            narrow = '%s.ti. AND %s.ti,ab,clm. AND (B1 OR B2).kd. AND @pd>="%s"' % (ppubs_any(phrases), ppubs_any(features), since)
            second = []
            docs += self.ppubs_query("patent", narrow, PPUBS_PATENT_LIMIT, "score desc", "narrow", out=second)
            if second and second[0].get("status") == "ok":
                first[0].update(optional=True, reason="命中 %d 件太多，已加查一条收窄的检索式（标题里有品名、并且出现结构词）" % first[1])
        return docs

    def us_part(self, part: dict) -> list:
        """美国：主体以外的部件各查一轮（外观按标题，发明按标题摘要并要求出现结构词）。"""
        english, _local, features = part_words(part)
        english = [w for w in english if ppubs.phrase(w)]
        if not english:
            return []
        features = [f for f in features if re.search(r"[a-z]", f) and ppubs.phrase(f)]
        label = part.get("name") or english[0]
        docs = self.ppubs_query("design", '%s.ti. AND S.kd. AND @pd>="%s"' % (ppubs_any(english), numbers.years_ago(DESIGN_YEARS, self.today)),
                                PPUBS_PART_LIMIT, "date_publ desc", "part")
        since = numbers.years_ago(PATENT_YEARS, self.today)
        query = ('%s.ti,ab. AND %s.ti,ab,clm. AND (B1 OR B2).kd. AND @pd>="%s"' % (ppubs_any(english), ppubs_any(features), since) if features
                 else '%s.ti,ab. AND (B1 OR B2).kd. AND @pd>="%s"' % (ppubs_any(english), since))
        docs += self.ppubs_query("patent", query, PPUBS_PART_LIMIT, "score desc", "part")
        return [dict(doc, part=label) for doc in docs]

    def us_applications(self, phrases: list, features: list = ()) -> list:
        """美国：已公开未授权的申请（关注清单用，不评等级）。是辅助的一路：没查成不算发明这一类的缺口。"""
        since = numbers.years_ago(PENDING_YEARS, self.today)
        features = [f for f in features if ppubs.phrase(f)]
        query = ('%s.ti,ab. AND %s.ti,ab,clm. AND @pd>="%s"' % (ppubs_any(phrases), ppubs_any(features), since) if features
                 else '%s.ti,ab. AND @pd>="%s"' % (ppubs_any(phrases), since))
        return self.ppubs_query("patent", query, PPUBS_APP_LIMIT, "score desc", "application", optional=True, database="US-PGPUB")

    def patent_by_claims(self, phrases: list) -> list:
        since = numbers.years_ago(PATENT_YEARS, self.today)
        query = '%s.clm. AND (B1 OR B2).kd. AND @pd>="%s"' % (ppubs_any(phrases), since)
        return self.ppubs_query("patent", query, PPUBS_CLAIM_LIMIT, "score desc", "claims", optional=True)  # 多查的一路：权利要求里提到本品叫法的

    # ---- SerpApi ----
    def design_by_serpapi(self, phrases: list) -> list:
        query = "(%s)" % " OR ".join('"%s"' % p for p in phrases)
        source = "SerpApi（Google Patents）"
        started = time.monotonic()
        key = self.keys.get("serpapi", "")
        if not key:
            self.record("design", source, query, started, skipped=self.why.get("serpapi", "没有配置 SerpApi 的 key"), optional=True)
            return []
        after = "publication:%s" % numbers.years_ago(DESIGN_YEARS, self.today)
        got = self.guarded("design", source, query, lambda: serpapi.patents(key, query, True, "US", after, 100, self.opener), optional=True)
        if got is None:
            return []
        result, started = got
        docs = [dict(doc, via="relevance") for doc in result["docs"]]
        self.record("design", source, query, started, docs=docs, total=result["total"], optional=True)
        return docs

    # ---- 美国以外：发明、实用新型、外观都走 SerpApi 的 Google Patents ----
    def foreign_call(self, routes: list, query: str, design: bool, offices: str, after: str, granted: bool = True, language: str = "",
                     label: str = "", optional: bool = False):
        """查一次；没查成时给 routes 里每类权利各记一条原因，返回 None。这一单的 SerpApi 次数用满了就不发请求（硬上限）。"""
        source = "SerpApi（Google Patents）"
        shown = "%s%s｜查的局：%s" % ("【%s】" % label if label else "", query, "、".join(config.OFFICE_NAMES.get(o, o) for o in offices.split(",")))
        started = time.monotonic()
        key = self.keys.get("serpapi", "")
        error = skipped = None
        result = None
        with self._lock:
            over = self.serp_used >= SERPAPI_BUDGET
            if key and not over:
                self.serp_used += 1
        if not key:
            skipped = self.why.get("serpapi", "没有配置 SerpApi 的 key")
        elif over:
            skipped = "这一单的 SerpApi 次数（%d 次）用完了，这一条没有查" % SERPAPI_BUDGET
        else:
            try:
                result = serpapi.patents(key, query, design, offices, after, 100, self.opener, granted=granted, language=language)
            except http.SourceError as exc:
                error = exc.message
            except Exception as exc:  # 意料之外的错误也只算这一路没查成
                error = "程序出错（%s）" % type(exc).__name__
        if result is None:
            if error is not None:  # 发出去了但没查成：也记一笔，"每单最多 6 次"按发出去的数
                with self._lock:
                    self.usage.add_source_call("SerpApi（没查成）")
            for route in routes:
                self.record(route, source, shown, started, error=error, skipped=skipped or "", optional=optional)
            return None
        with self._lock:
            self.usage.add_source_call(source)
        return result, shown, started

    def take_retry(self) -> bool:
        with self._lock:
            if self.retry_left <= 0:
                return False
            self.retry_left -= 1
            return True

    def adjusted(self, routes: list, words: list, features: list, narrow: bool, design: bool, offices: str, after: str,
                 granted: bool, language: str, label: str):
        """查一个部件：命中太多收窄一次（标题里要有品名），一件没有就去掉结构词放宽一次。补查只用这一单剩下的 SerpApi 次数；
        被替换掉的那一次照样记录，标成辅助（不算缺口）。返回 (结果, 显示的检索式, 开始时间)，没查成返回 None。"""
        query = part_query(words, features, narrow)
        got = self.foreign_call(routes, query, design, offices, after, granted, language, label)
        if got is None:
            return None
        result, shown, started = got
        retry, why = None, ""
        wide = result["total"] > WIDE_AT and not narrow
        empty = result["total"] == 0 and bool(features)
        if (wide or empty) and self.take_retry():
            if wide:
                retry, why = part_query(words, features, True), "命中 %d 件太多，改成标题里要有品名再查一次" % result["total"]
            else:
                retry, why = part_query(words, [], narrow), "带上结构词一件都没有，去掉结构词再查一次"
        elif wide or empty:
            with self._lock:
                self.notes.append("%s这一条%s，但这一单的 SerpApi 次数已经用在各部件的主检索上，没有再%s。" % (
                    "【%s】" % label if label else "", "命中 %d 件太多" % result["total"] if wide else "一件都没有", "收窄" if wide else "放宽"))
        if retry:
            again = self.foreign_call(routes, retry, design, offices, after, granted, language, label, optional=True)  # 补查没成：用原来那次的结果，不算缺口
            if again is not None:
                for route in routes:
                    self.record(route, "SerpApi（Google Patents）", shown, started, docs=[], total=result["total"], optional=True, note=why)
                return again
        return got

    def foreign_patents(self, parts: list) -> list:
        """发明（含已公开未授权的申请）和实用新型一次查回来，按部件分开查；按号码的类别码分到发明、实用新型，申请标成 pending。"""
        country = self.task.country
        offices = config.FOREIGN_PLAN[country]["patent"]
        routes = ["patent"] + (["utility_model"] if (country, "utility_model") not in config.NOT_APPLICABLE else [])
        after = "filing:%s" % numbers.years_ago(PATENT_YEARS, self.today)
        # 不限授权那条：申请公开只要近 8 年的（合并时再筛），但德意西的实用新型只从这一条回来、保护 10 年，所以有实用新型的国家看 10 年
        recent_years = UTILITY_YEARS if "utility_model" in routes else PENDING_YEARS
        recent = "filing:%s" % numbers.years_ago(recent_years, self.today)
        out = []
        for part in parts:
            words, features = foreign_words(*part_words(part), local_feature_words(part) or None)
            if not words:
                continue
            # 单个通用词不许独立成一路：没有结构词可以搭配时，品名必须出现在标题里（不管哪种语言）
            narrow = not features
            label = part.get("name") or ""
            # 两条：已授权的看近 20 年；不限授权的（申请公开、德意西的实用新型）看近 8 年——放到 20 年命中数会涨到几千件
            for granted, window, tag in ((True, after, "已授权"), (False, recent, "近 %d 年含申请" % recent_years)):
                got = self.adjusted(routes, words, features, narrow, False, offices, window, granted, "", "%s·%s" % (label, tag) if label else tag)
                if got is None:
                    continue
                result, shown, started = got
                docs = []
                for doc in result["docs"]:
                    if doc["right_type"] in routes:
                        docs.append(dict(doc, via="relevance", part=label, pending=doc["right_type"] == "patent" and numbers.is_application(doc["number"])))
                for route in routes:
                    mine = [doc for doc in docs if doc["right_type"] == route]
                    self.record(route, "SerpApi（Google Patents）", shown, started, docs=mine,
                                total=result["total"] if len(result["docs"]) < result["total"] else None)
                out += docs
        if config.COUNTRIES[country]["lang"] != "en":
            self.notes.append("原文不是英文的专利和实用新型，比对用的是 Google Patents 的机器翻译，用词可能不准；评到中以上的请对照原文。")
        if "EP" in offices.split(","):
            self.notes.append("欧洲专利（EP 开头）授权后要在各国分别生效、逐年缴费；它在%s是否仍然有效本工具没有核实，评到中以上的请到欧洲专利局登记簿核对。"
                              % config.COUNTRIES[country]["name"])
        return out

    def euipo_designs(self, phrases: list, label: str = ""):
        """欧盟外观走欧盟知识产权局的官方接口（有图）。查成了返回清单（可以是空的）；没查成返回 None，由调用方退回只有名单的来源。"""
        query = euipo.query_of(phrases)
        if not query:
            return None
        shown = ("【%s】" % label if label else "") + query
        got = self.guarded("design", euipo.SOURCE, shown, lambda: euipo.search(phrases, 100, self.opener), optional=True)
        if got is None:
            return None
        result, started = got
        docs = [dict(doc, via="relevance", part=label) for doc in result["docs"]]
        self.record("design", euipo.SOURCE, shown, started, docs=docs, total=result["total"])
        return docs

    def foreign_designs(self, parts: list) -> list:
        country = self.task.country
        office = config.FOREIGN_PLAN[country]["design"]
        if not office:
            return []
        out = []
        for part in parts:
            english, local, features = part_words(part)
            label = part.get("name") or ""
            if office == "EM" and euipo.ready():  # 计划里这一路不用 SerpApi
                if not euipo.query_of(english or local):  # 没有可查的品名：接口和 SerpApi 都不用发
                    continue
                docs = self.euipo_designs(english or local, label)
                if docs is not None:
                    out += docs
                    continue
                if not self.take_retry():  # 欧盟接口没查成：退回 SerpApi 只能用补查剩下的次数，不能挤掉别的部件的主检索
                    self.record("design", "SerpApi（Google Patents）", "【%s】" % label if label else "", time.monotonic(),
                                skipped="欧盟知识产权局的接口没查成，这一单的 SerpApi 次数也用完了，欧盟外观未检索")
                    continue
            english_only = office == "EM" and bool(english)  # 欧盟外观每种语言各一条记录、品名都有英文：只查英文的那一条
            if office == "EM":
                # 欧盟外观的标题只是几个品名：用"几个词都出现"来查，不加结构词（品名串里不会写结构）
                query = " OR ".join("(%s)" % w for w in (english if english_only else local))
                got = self.foreign_call(["design"], query, True, office, "filing:%s" % numbers.years_ago(25, self.today), False,
                                        "ENGLISH" if english_only else "", label) if query else None
            else:
                names = [w for w in (local_term(n) for n in part.get("design_names") or []) if w and cjk_ok(w, 2)]
                words = list(dict.fromkeys(names + local)) or english
                local_features = inside_removed(words, only_local(features, local_feature_words(part) or None))
                got = self.adjusted(["design"], words, local_features, False, True, office, "filing:%s" % numbers.years_ago(25, self.today),
                                    True, "", label) if words else None
            if got is None:
                continue
            result, shown, started = got
            docs, seen = [], set()
            for doc in result["docs"]:
                if doc["right_type"] == "design" and doc["number"] not in seen:  # 同一件的几种语言只算一件
                    seen.add(doc["number"])
                    docs.append(dict(doc, via="relevance", part=label))
            more = result["total"] > len(result["docs"])  # 来源那边还有没取回来的
            self.record("design", "SerpApi（Google Patents）", shown, started, docs=docs[:FOREIGN_DESIGN_KEEP],
                        total=result["total"] if more else len(docs) if len(docs) > FOREIGN_DESIGN_KEEP else None)
            out += docs[:FOREIGN_DESIGN_KEEP]
        return out

    # ---- 商标 ----
    def manual_marks(self, terms: list, blind: bool, branded: list, started: float) -> list:
        """没有可合规检索的商标库的国家（日本）：不发请求，挑出要人工核对的词、给出检索链接，这一类记"未检索"。"""
        words, left_out = jp_marks.collect(self.task["understanding"], self.task["product"], terms, blind)
        own = {plain(jp_marks.clean(b)).lower() for b in branded or []}
        words = [w for w in words if plain(jp_marks.clean(w["term"])).lower() not in own]  # 原卖家的品牌按换成自有品牌算，和商标检索同一口径
        with self._lock:
            self.manual = words
        if words:
            why = "%s；要人工核对的 %d 个词和检索链接见报告" % (jp_marks.WHY_NOT, len(words))
        else:
            why = "%s；也没有挑出要人工核对的词（定了自有品牌后，品牌名也要查）" % jp_marks.WHY_NOT
        if blind:
            why += "；产品理解没有完成，只对照了内置词表"
        self.record("trademark", jp_marks.SOURCE, "、".join(w["term"] for w in words) or "（没有挑出要人工核对的词）", started, skipped=why)
        with self._lock:
            todo = "要人工核对 %d 个词：%s（检索链接见报告\"商标要人工核对的词\"）" % (len(words), "、".join(w["term"] for w in words)) if words else "没有挑出要人工核对的词"
            self.task.add_incomplete("%s商标" % config.COUNTRIES[self.task.country]["name"], "未检索，%s%s" % (
                todo, "；排不进去的：%s" % "、".join(left_out) if left_out else ""), "trademark")
        if branded:
            self.notes.append("商标没有列原卖家的品牌「%s」：按换成自有品牌上架算。如果打算沿用这个品牌名，需要另查。" % "、".join(branded))
        return []

    def trademarks(self, terms: list, left_out: list, blind: bool, branded: list = ()) -> list:
        source = "Signa（商标库）"
        started = time.monotonic()
        if self.task.country in config.TRADEMARK_MANUAL:
            return self.manual_marks(list(terms) + list(left_out), blind, branded, started)
        offices = signa.OFFICES.get(self.task.country, "")
        key = self.keys.get("signa", "")
        country_name = config.COUNTRIES[self.task.country]["name"]
        script = [] if blind else foreign_script(self.task["understanding"])
        if not terms and blind:  # 产品理解没成：不知道产品上有没有文字，不能说"没有要查的"
            self.record("trademark", source, "", started, skipped="产品理解没有完成，不知道产品上有没有文字和标识，商标没有查")
            return []
        if script and not (terms and offices and key):  # 有非拉丁字母的文字，又没有别的词能查成：不能说"没有要查的"
            why = ["产品上的文字（%s）不是拉丁字母，现有的商标库查不了" % "、".join(script)]
            if terms and not offices:
                why.append("Signa 还没有%s的商标库" % country_name)
            elif terms and not key:
                why.append(self.why.get("signa", "没有配置 Signa 的 key"))
            self.record("trademark", source, "、".join(list(terms) + script), started, skipped="；".join(why) + "，未检索")
            return []
        if script:
            with self._lock:
                self.task.add_incomplete("商标检索", "产品上这些不是拉丁字母的文字查不了：%s" % "、".join(script), "trademark")
        if not terms:
            why = "（产品本体上没有文字、标识，也没有可疑的名字，没有需要查的词%s）" % ("" if offices else "；%s的商标库本工具也查不了" % country_name)
            if branded:
                why = "（只有原卖家的品牌「%s」，按自有品牌上架不查；没有别的要查的词）" % "、".join(branded)
                self.notes.append("商标没有查原卖家的品牌「%s」：按换成自有品牌上架算。如果打算沿用这个品牌名，需要另查。" % "、".join(branded))
            self.record("trademark", source, why, started, docs=[], empty=True)
            return []
        if not offices:
            self.record("trademark", source, "、".join(terms), started, skipped="Signa 还没有%s的商标库" % config.COUNTRIES[self.task.country]["name"])
            return []
        if not key:
            self.record("trademark", source, "、".join(terms), started, skipped=self.why.get("signa", "没有配置 Signa 的 key"))
            return []
        if branded:
            self.notes.append("商标没有查原卖家的品牌「%s」：按换成自有品牌上架算。如果打算沿用这个品牌名，需要另查。" % "、".join(branded))
        docs = []
        for term in terms:
            shown = term if self.task.country == "US" else "%s｜查的局：%s" % (term, "、".join(signa.OFFICE_NAMES.get(o, o) for o in offices.split(",")))
            got = self.guarded("trademark", source, shown, lambda t=term: signa.trademarks(key, t, offices, 10, self.opener))
            if got is None:
                continue
            result, began = got
            hits = [dict(doc, matched_term=term) for doc in result]
            self.record("trademark", source, shown, began, docs=hits)
            docs += hits
        if left_out:
            with self._lock:
                self.task.add_incomplete("商标检索", "每单最多查 %d 个词，还有这些没查：%s" % (TRADEMARK_TERMS, "、".join(left_out[:8])), "trademark")
        return docs

    # ---- 图案出处、维权信号 ----
    def image_matches(self) -> None:
        """以图搜图找图案出处。商品图有网址（链接入口）用 Serper（3 点）；没有网址（资料入口）或没有 Serper 的 key 时，
        把主图上传给 SerpApi 再查（用户 2026-11-28 同意；计 SerpApi 1 次，不占检索那 6 次）。"""
        started = time.monotonic()
        key = self.keys.get("serper", "")
        url = next((i.get("url") for i in self.task["product"].get("images") or [] if str(i.get("url") or "").startswith("https://")), "")
        if not url or not key:
            self.lens_by_upload(url, started)
            return
        source = "Serper（以图搜图）"
        got = self.guarded("artwork", source, url, lambda: serper.lens(key, url, self.opener))
        if got is None:
            return
        result, began = got
        self.lens = result[:LENS_KEEP]
        self.record("artwork", source, url, began, docs=result)

    def lens_by_upload(self, url: str, started: float) -> None:
        source = "SerpApi（以图搜图）"
        key = self.keys.get("serpapi", "")
        images_ = [i for i in self.task["product"].get("images") or [] if isinstance(i, dict) and i.get("file")]
        shown = "主图 %s" % Path(str(images_[0]["file"])).name if images_ else ""
        if not key:
            why = self.why.get("serpapi", "没有配置 SerpApi 的 key")
            self.record("artwork", source, shown, started, skipped=("这一单的商品图没有网址，要上传主图给 SerpApi 以图搜图，但" + why) if not url
                        else "没有 Serper 的 key，SerpApi 也用不了（%s）" % why)
            return
        if url:  # 有网址就不用上传
            got = self.guarded("artwork", source, url, lambda: serpapi.lens(key, url=url, country=self.lens_country(), opener=self.opener))
        else:
            if not images_:
                self.record("artwork", source, "", started, skipped="这一单没有可用的商品图，没法以图搜图")
                return
            from . import images as image_tools
            folder = self.task.dir / "work"
            folder.mkdir(parents=True, exist_ok=True)
            picture = image_tools.for_upload(self.task.dir / str(images_[0]["file"]), folder)
            if picture is None:
                self.record("artwork", source, shown, started, skipped="主图压不到 500KB 以内（要装 Pillow），没法上传给 SerpApi 以图搜图")
                return
            got = self.guarded("artwork", source, shown + "（上传给 SerpApi）",
                               lambda: serpapi.lens(key, image_id=serpapi.upload_image(key, picture, self.opener), country=self.lens_country(),
                                                    opener=self.opener))
        if got is None:
            return
        result, began = got
        self.lens = result[:LENS_KEEP]
        self.record("artwork", source, shown or url, began, docs=result)

    def lens_country(self) -> str:
        return "" if self.task.country == "GB" else self.task.country  # 英国在 Google 里的写法不统一：不指定

    def enforcement_signals(self, names: list, hypotheses: list) -> None:
        source = "Serper（网页）"
        key = self.keys.get("serper", "")
        queries = []
        if names:
            queries.append("%s patent infringement lawsuit Amazon sellers" % names[0])
        owner = next((h for h in hypotheses if h.get("owner")), None)
        if owner:
            term = (owner.get("search_terms") or [owner.get("name", "")])[0]
            queries.append("%s lawsuit Amazon sellers %s" % (owner["owner"], term))
        if not queries:
            return
        if not key:
            self.record("enforcement", source, "；".join(queries), time.monotonic(), skipped=self.why.get("serper", "没有配置 Serper 的 key"),
                        route_name="维权信号")
            return
        for query in queries[:2]:
            got = self.guarded("enforcement", source, query, lambda q=query: serper.web(key, q, self.task.country, 10, self.opener),
                               route_name="维权信号")
            if got is None:
                continue
            result, began = got
            self.enforcement += [dict(item, query=query) for item in result[:ENFORCEMENT_KEEP]]
            self.record("enforcement", source, query, began, docs=result, route_name="维权信号")

    # ---- 开跑前：各数据源还剩多少 ----
    def check_capacity(self) -> None:
        """查一遍各家的余量（都是不计次的账户接口），告诉用户；用完了的那一路这次不发请求。"""
        self.keys, self.why = {}, {}
        primary, backup = self.env.get("SERPAPI_API_KEY") or "", self.env.get("SERPAPI_API_KEY_BACKUP") or ""
        serper_key, signa_key = self.env.get("SERPER_API_KEY") or "", self.env.get("SIGNA_API_KEY") or ""
        with ThreadPoolExecutor(max_workers=4) as pool:
            jobs = {"serpapi": pool.submit(serpapi.remaining, primary, self.opener) if primary else None,
                    "backup": pool.submit(serpapi.remaining, backup, self.opener) if backup else None,
                    "serper": pool.submit(serper.balance, serper_key, self.opener) if serper_key else None,
                    "signa": pool.submit(signa.credits, signa_key, self.opener) if signa_key else None}
            left = {}
            for name, job in jobs.items():
                try:
                    left[name] = job.result() if job else None
                except Exception:
                    left[name] = -1  # 查不到余量：照常去查，由那一路自己报错
        said = []
        if primary and left["serpapi"] != 0:
            self.keys["serpapi"] = primary
        elif backup and left["backup"] != 0:
            self.keys["serpapi"] = backup
            said.append("SerpApi 主 key 的次数用完了，改用备用 key" if primary else "SerpApi 用的是备用 key")
            left["serpapi"] = left["backup"]
        elif primary or backup:
            self.why["serpapi"] = "SerpApi 本期的次数用完了" + ("（外观还有美国专利局那一路）" if self.task.country == "US" else "")
        else:
            self.why["serpapi"] = "没有配置 SerpApi 的 key" + ("（外观还有美国专利局那一路）" if self.task.country == "US" else "")
        for name, key, need, label in (("serper", serper_key, 5, "Serper"), ("signa", signa_key, 10, "Signa")):
            if not key:
                self.why[name] = "没有配置 %s 的 key" % label
            elif left[name] is not None and 0 <= left[name] < need:
                self.why[name] = "%s 的点数不够了（还剩 %d）" % (label, left[name])
            else:
                self.keys[name] = key
        numbers_known = ["%s 还剩 %s" % (label, left[name]) for name, label in (("serpapi", "SerpApi"), ("serper", "Serper"), ("signa", "Signa"))
                         if left.get(name) is not None and left[name] >= 0]
        if numbers_known:
            said.append("各接口余量：" + "，".join(numbers_known))
        said += ["这次不查：" + reason for reason in self.why.values()]
        for line in said:
            self.say("  " + line)

    # ---- 总流程 ----
    def run(self) -> dict:
        understanding, product = self.task["understanding"], self.task["product"]
        blind = bool(understanding.get("fallback"))
        names = understanding.get("names") or []
        if blind or not names:
            names = fallback_names(product)
        phrases = name_phrases(names, [] if blind else understanding.get("core_terms") or [])
        hypotheses = understanding.get("hypotheses") or []
        terms, left_out, branded = trademark_terms(understanding, product.get("brand", ""), listing=(self.task["entry"] or {}).get("type") == "input")
        self.check_capacity()
        country_name = config.COUNTRIES[self.task.country]["name"]
        results = {}
        with ThreadPoolExecutor(max_workers=6) as pool:
            jobs = {}
            foreign = self.task.country != "US"
            local = [] if blind else [local_term(n) for n in understanding.get("local_names") or [] if local_term(n)][:3]
            parts = parts_of(understanding, blind, phrases, local)
            main_features = [f for f in part_words(parts[0])[2] if re.search(r"[a-z]", f)] if parts else []
            self.retry_left = max(0, SERPAPI_BUDGET - self.planned_serpapi(parts, foreign, phrases))
            if phrases and not foreign:
                jobs["design_title"] = pool.submit(self.design_by_title, phrases)
                jobs["design_serpapi"] = pool.submit(self.design_by_serpapi, phrases)
                jobs["patent_text"] = pool.submit(self.patent_by_text, phrases, main_features)
                jobs["patent_claims"] = pool.submit(self.patent_by_claims, phrases)
                jobs["us_applications"] = pool.submit(self.us_applications, phrases, main_features)
                if len(parts) > 1:
                    jobs["us_parts"] = pool.submit(lambda: [doc for part in parts[1:] for doc in self.us_part(part)])
            elif parts and foreign:
                jobs["foreign_patent"] = pool.submit(self.foreign_patents, parts)
                if config.FOREIGN_PLAN[self.task.country]["design"]:
                    jobs["foreign_design"] = pool.submit(self.foreign_designs, parts)
            else:
                routes = ["design", "patent"] + (["utility_model"] if foreign and (self.task.country, "utility_model") not in config.NOT_APPLICABLE else [])
                for route in routes:
                    self.record(route, "SerpApi（Google Patents）" if foreign else "美国专利局", "", time.monotonic(),
                                skipped=("没有可用的产品叫法，%s没有检索" % config.RIGHT_NAMES[route]) if foreign
                                else "没有可用的英文叫法，专利和外观没有检索")
            for (code, route), reason in config.COVERAGE_GAPS.items():  # 查不了的本国库逐项写明；没有要查的商标词时不用写
                if code == self.task.country and not (route == "trademark" and not terms):
                    self.record(route, "%s本国库" % country_name, "", time.monotonic(), skipped=reason)
            jobs["trademark"] = pool.submit(self.trademarks, terms, left_out, blind, branded)
            jobs["lens"] = pool.submit(self.image_matches)
            jobs["enforcement"] = pool.submit(self.enforcement_signals, names, hypotheses)
            for name, job in jobs.items():
                results[name] = self.collect(name, job)
            title_hits = results.get("design_title") or []
            class_hits = self.collect("design_class", pool.submit(self.design_by_class, title_hits, phrases)) if title_hits else []
        design_docs = title_hits + (results.get("design_serpapi") or []) + (class_hits or []) + (results.get("foreign_design") or [])
        us_parts = results.get("us_parts") or []
        design_docs += [d for d in us_parts if d["right_type"] == "design"]
        patent_docs = ((results.get("patent_text") or []) + (results.get("patent_claims") or []) + (results.get("foreign_patent") or [])
                       + [d for d in us_parts if d["right_type"] == "patent"] + (results.get("us_applications") or []))
        candidates = self.mark_candidates(self.merge(patent_docs + design_docs + self.marked_docs())) + self.trademark_candidates(results.get("trademark") or []) + self.artwork_candidates(hypotheses)
        if blind:
            self.notes.append("产品理解没有完成，检索词取自标题（%s），可能不准。" % ("、".join(phrases) or "没有取到"))
        pending_ok = any(r["status"] == "ok" and (r["source"] == "美国专利局（申请公开）" or "含申请" in r["query"]) for r in self.records)
        if pending_ok:
            self.notes.append("已公开、还没授权的发明申请也查了（近 %d 年申请的）：授权前不能用来主张权利，相关的列进\"关注清单\"、不评等级；"
                              "授权后对方可能要求公开以后的补偿，上架后要留意它的进展。外观检索的是已登记的%s。" % (
                                  PENDING_YEARS, "；实用新型看近 %d 年申请的（保护期 10 年）" % UTILITY_YEARS
                                  if (self.task.country, "utility_model") not in config.NOT_APPLICABLE else ""))
        elif phrases or parts:
            self.notes.append("已公开、还没授权的发明申请这次没有查成（见检索记录），关注清单可能不全。")
        if len(parts) > 1:
            self.notes.append("按部件分开检索：%s。" % "、".join(p.get("name") or (p.get("terms") or p.get("local_terms") or ["?"])[0] for p in parts))
        extra = [p for p in (understanding.get("parts") or [])[MAX_PARTS:] if isinstance(p, dict)] if not blind else []
        if extra:
            names_left = "、".join(str(p.get("name") or (p.get("terms") or ["?"])[0]) for p in extra)
            self.notes.append("产品理解还列了 %s，没有单独检索（每单最多按 %d 个部件分开查）。" % (names_left, MAX_PARTS))
            with self._lock:
                self.task.add_incomplete("部件 %s" % names_left, "没有单独检索（每单最多按 %d 个部件分开查）" % MAX_PARTS, "patent")
        self.records.sort(key=lambda r: int(r["id"][1:]))
        return {"searches": self.records, "candidates": candidates, "lens": self.lens, "enforcement": self.enforcement, "notes": self.notes,
                "manual_marks": self.manual}

    def planned_serpapi(self, parts: list, foreign: bool, phrases: list) -> int:
        """这一单主检索要用几次 SerpApi（补查只用剩下的）。"""
        if not self.keys.get("serpapi"):
            return 0
        if not foreign:
            return 1 if phrases else 0
        design = config.FOREIGN_PLAN[self.task.country]["design"]
        per_part = 2 + (1 if design and not (design == "EM" and euipo.ready()) else 0)
        return per_part * len(parts)

    def collect(self, name: str, job):
        """取一路的结果。各路自己会记下失败原因；这里再兜一层，免得意料之外的错误让整个检索崩掉。"""
        try:
            return job.result()
        except Exception as exc:
            route, optional = JOB_ROUTES.get(name, ("other", True))
            self.record(route, "程序", "", time.monotonic(), error="这一路检索的程序出错（%s）" % type(exc).__name__, optional=optional,
                        route_name="维权信号" if route == "enforcement" else "")
            return None

    # ---- 合并 ----
    def merge(self, docs: list) -> list:
        """同一件专利不同来源的记录并成一件；按日期推算已过保护期的、来源写明已失效的不要。"""
        docs = self.drop_superseded(docs)
        merged, order = {}, []
        for doc in docs:
            key = numbers.us_key(doc["number"]) or doc["number"]
            if key not in merged:
                merged[key] = dict(doc, id=("D-" if doc["right_type"] == "design" else "P-") + key, sources=[doc["source"]], via=[doc.get("via", "")],
                                   status_from=doc["source"] if doc.get("legal_status") else "")
                order.append(key)
                continue
            kept = merged[key]
            if not kept.get("legal_status") and doc.get("legal_status"):
                kept["status_from"] = doc["source"]
            for field in ("title", "owner", "filing_date", "grant_date", "snippet", "legal_status"):
                kept[field] = kept.get(field) or doc.get(field, "")
            kept["figures"] = (kept.get("figures") or []) or (doc.get("figures") or [])
            kept["classes"] = (kept.get("classes") or []) or (doc.get("classes") or [])
            kept["image_location"] = kept.get("image_location") or doc.get("image_location", "")
            for field in ("pages", "figures_from", "figures_to"):
                kept[field] = kept.get(field) or doc.get(field, 0)
            if doc["source"] not in kept["sources"]:
                kept["sources"].append(doc["source"])
            if doc.get("via") and doc["via"] not in kept["via"]:
                kept["via"].append(doc["via"])
        out, expired, dead = [], 0, 0
        foreign_merge = self.task.country != "US"
        for key in order:
            cand = merged[key]
            expiry = numbers.parse_date(cand.get("expiry", "")) if cand.get("euipo") else None  # 官方登记的届满日（含续展）比推算的准
            expiry = expiry or numbers.expiry(cand["number"], cand["right_type"], cand.get("filing_date", ""), cand.get("grant_date", ""))
            if cand.get("legal_status") == "已失效":  # 来源记载的状态可能不准（欠费后还能恢复、数据库更新晚）：不直接丢，标"状态存疑"照常初筛
                cand["status_doubt"] = "%s 记载已失效" % (cand.get("status_from") or cand["sources"][0])
                dead += 1
            if expiry and expiry < self.today and cand["right_type"] in ("design", "utility_model"):
                expired += 1  # 外观和实用新型的保护期是固定的；发明可能有期限调整，留到读公开页时再看
                continue
            cand["expiry"] = expiry.isoformat() if expiry else ""
            cand["source"] = " + ".join(cand.pop("sources"))
            cand["via"] = [v for v in cand["via"] if v]
            listed_only = cand["right_type"] == "design" and not numbers.us_key(cand["number"]) and not cand.get("euipo")
            kind = config.NO_FIGURE_OFFICES.get(numbers.office_of(cand["number"])) if listed_only else None
            if kind:  # 只有名单、没有图：初筛时由程序直接记"未能比对"，不拿去看图；给一个能看到官方附图的链接
                cand["no_figures"] = True
                cand["figures"] = []
                cand["url"] = numbers.official_link(cand["number"]) or cand.get("url", "")
            out.append(cand)
        if expired:
            self.notes.append("按授权日推算已过保护期的外观%s %d 件，没有列入候选。" % ("和实用新型" if foreign_merge else "", expired))
        if dead:
            self.notes.append("来源记载已失效的 %d 件，仍列入候选照常初筛：来源记载的状态可能不准，没有核官方。" % dead)
        return out

    def marked_docs(self) -> list:
        """本商品页面和竞品页面上标注的专利号：直接列为候选（它们说明那款产品就受这些权利保护）。"""
        self.marked = {}
        country = self.task.country
        allowed = {"US"} if country == "US" else set(config.FOREIGN_PLAN[country]["patent"].split(",")) | {config.FOREIGN_PLAN[country]["design"]}
        elsewhere = []
        sources = [("本商品页面", self.task["product"].get("marking") or [])]
        sources += [("竞品 %s" % (c.get("asin") or c.get("input", "")), c.get("marking") or []) for c in self.task.data.get("competitors") or []
                    if isinstance(c, dict) and c.get("status") == "ok"]
        docs = []
        for who, texts in sources:
            for right, number in numbers.marked_numbers(" ".join(str(t) for t in texts)):
                if numbers.office_of(number) not in allowed:  # 别国的权利不在目的国生效：只写进说明
                    elsewhere.append("%s（%s）" % (number, who))
                    continue
                if number in self.marked:
                    continue
                self.marked[number] = who
                docs.append({"right_type": right, "number": number, "title": "", "source": "%s的标注" % who, "via": "marked",
                             "url": "https://patents.google.com/patent/%s/%s" % (number, "ja" if number.startswith("JP") else "en")})
        if docs:
            self.notes.append("页面上标注的专利号 %d 件直接列为候选：%s。" % (len(docs), "、".join("%s（%s）" % (n, w) for n, w in self.marked.items())))
        if elsewhere:
            self.notes.append("页面上还标注了别国的号码，不是%s的权利，没有列入：%s。" % (config.COUNTRIES[country]["name"], "、".join(dict.fromkeys(elsewhere))))
        return docs

    def mark_candidates(self, candidates: list) -> list:
        for cand in candidates:
            who = (getattr(self, "marked", {}) or {}).get(cand.get("number"))
            if who:
                cand["marked_by"] = who
        return candidates

    def drop_superseded(self, docs: list) -> list:
        """申请公开：已经有授权文本的（同一个申请）去掉，申请太早的去掉（多半已有结论），其余标 pending 留着。"""
        granted = [d for d in docs if d.get("right_type") == "patent" and not d.get("pending")]
        app_numbers = {d.get("app_number") for d in granted if d.get("app_number")}
        same_family = {(numbers.office_of(d["number"]), d.get("filing_date"), (d.get("owner") or "").lower(), (d.get("title") or "").lower().strip())
                       for d in granted if d.get("filing_date")}
        cutoff = numbers.years_ago(PENDING_YEARS, self.today)
        kept, old, superseded = [], 0, 0
        for doc in docs:
            if doc.get("right_type") == "patent" and doc.get("pending"):
                filed = re.sub(r"\D", "", doc.get("filing_date") or "")
                family = (numbers.office_of(doc["number"]), doc.get("filing_date"), (doc.get("owner") or "").lower(), (doc.get("title") or "").lower().strip())
                if (doc.get("app_number") and doc["app_number"] in app_numbers) or (doc.get("filing_date") and family in same_family):
                    superseded += 1
                    continue
                if filed and filed < cutoff:
                    old += 1
                    continue
            kept.append(doc)
        if superseded:
            self.notes.append("申请公开里有 %d 件已经有了授权文本，按授权的那件算。" % superseded)
        if old:
            self.notes.append("申请日在 %d 年以前、还没授权的申请公开 %d 件，没有列入（多半已经有了结论）。" % (PENDING_YEARS, old))
        return kept

    def trademark_candidates(self, docs: list) -> list:
        out, seen = [], set()
        for doc in docs:
            key = (doc.get("office"), doc.get("number"))
            if not doc.get("number") or key in seen:
                continue
            seen.add(key)
            out.append(dict(doc, id="TM-%s-%s" % (doc.get("office") or "X", re.sub(r"[^A-Za-z0-9]", "", doc["number"]))))
        return out

    def artwork_candidates(self, hypotheses: list) -> list:
        """图案、角色这类假设各算一个"版权图案"候选，初筛时结合以图搜图和维权信号决定要不要深查。"""
        out = []
        for index, item in enumerate(h for h in hypotheses if h.get("kind") in ("图案", "角色", "标识")):
            out.append({"id": "ART-%d" % (index + 1), "right_type": "artwork", "number": "", "title": str(item.get("name") or ""),
                        "owner": str(item.get("owner") or ""), "url": "", "watchlist": bool(item.get("watchlist")),
                        "source": "产品理解" + ("和常见维权方清单" if item.get("watchlist") else ""),
                        "snippet": " ".join(x for x in (str(item.get("reason") or ""), str(item.get("watch_note") or "")) if x)})
        return out
