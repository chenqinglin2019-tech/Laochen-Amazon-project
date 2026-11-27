"""真实的检索（R-004、R-013）：几路同时查，合并去重，按保护期筛掉过期的。

美国的发明和外观以美国专利局的公开检索接口为主（免费、当天授权当天可查），SerpApi 的 Google Patents 为辅（多一种排序，
带现行状态和代表图）；商标查 Signa；图案出处用主图以图搜图（Serper）；维权信号查网页（Serper）。
哪一路没查成都如实记下，不影响其他路。
"""
from __future__ import annotations

import re
import threading
import time
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from datetime import date

from . import config, numbers
from .sources import euipo, http, ppubs, serpapi, serper, signa

DESIGN_YEARS = 15
PATENT_YEARS = 20
PPUBS_DESIGN_LIMIT = 150
PPUBS_PATENT_LIMIT = 40
PPUBS_CLAIM_LIMIT = 20
PPUBS_CLASS_LIMIT = 40
TRADEMARK_TERMS = 3
# 每一路查的是哪类权利、是不是辅助来源（辅助来源没查成不算这类权利的缺口）
FOREIGN_DESIGN_KEEP = 20  # 没有附图、只能列名单的外观最多列几件
UTILITY_YEARS = 10
JOB_ROUTES = {"foreign_patent": ("patent", False), "foreign_utility": ("utility_model", False), "foreign_design": ("design", False), "design_title": ("design", False), "design_serpapi": ("design", True), "design_class": ("design", True),
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


def trademark_terms(understanding: dict, brand: str = "") -> tuple:
    """要去商标库查的词，按这个先后：清单上权利人的主要商标 → 产品本体上的文字 → AI 给的名字和检索词。
    默认按自有品牌上架：产品上的文字、AI 给的名字里如果只是原卖家的品牌，不查（换成自己的品牌就没有了）；
    但清单上权利人的商标照查，哪怕它和原卖家品牌同名。返回 (要查的词，最多 TRADEMARK_TERMS 个；排不进去的词；因为是原卖家品牌而没查的词)。"""
    hypotheses = understanding.get("hypotheses") or []
    firm = [mark for item in hypotheses for mark in item.get("watch_marks") or []]
    soft = list(understanding.get("text_on_product") or [])
    for item in hypotheses:
        soft += [item.get("name") or ""] + list(item.get("search_terms") or [])[:1]
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
        self.session = ppubs.Session(opener)
        euipo.configure(self.env)
        self.keys, self.why = {}, {}  # 这次能用的 key；不能用的那几路各是什么原因
        self._count = 0
        self._lock = threading.Lock()  # 几路检索同时跑，记账要排队

    def record(self, route: str, source: str, query: str, started: float, docs=None, total=None, error=None, skipped: str = "",
               route_name: str = "", optional: bool = False, empty: bool = False) -> dict:
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
            row.update(status="ok", reason="", truncated=cut, count=str(got) if not cut else "%d（共命中 %d 件，只取了前 %d 件）" % (got, total, got))
        with self._lock:
            self.records.append(row)
        return row

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
    def ppubs_query(self, route: str, query: str, limit: int, sort: str, via: str, optional: bool = False) -> list:
        got = self.guarded(route, "美国专利局", query, lambda: self.session.search(query, limit, sort), optional=optional)
        if got is None:
            return []
        result, started = got
        docs = [dict(doc, via=via) for doc in result["docs"] if doc["right_type"] == route]
        self.record(route, "美国专利局", query, started, docs=docs, total=result["total"], optional=optional)
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

    def patent_by_text(self, phrases: list) -> list:
        since = numbers.years_ago(PATENT_YEARS, self.today)
        query = '%s.ti,ab. AND (B1 OR B2).kd. AND @pd>="%s"' % (ppubs_any(phrases), since)
        return self.ppubs_query("patent", query, PPUBS_PATENT_LIMIT, "score desc", "text")

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
    @staticmethod
    def text_query(phrases: list, local: list) -> str:
        """发明和实用新型的检索式：全文里出现整个词组的，或者标题、摘要里几个词都出现的（核心品名和第一个当地叫法）。"""
        terms = [p.lower() for p in phrases] + list(local)   # 英文叫法一律小写：大写的 OR、NOT 会被当成检索语法
        loose = [p.lower() for p in phrases[:2]] + list(local[:1])
        parts = ['"%s"' % t for t in terms] + ["%s=(%s)" % (field, t) for t in loose for field in ("TI", "AB")]
        return "(%s)" % " OR ".join(parts)

    def foreign_call(self, routes: list, query: str, design: bool, offices: str, after: str, granted: bool = True, language: str = ""):
        """查一次；没查成时给 routes 里每类权利各记一条原因，返回 None。"""
        source = "SerpApi（Google Patents）"
        shown = "%s｜查的局：%s" % (query, "、".join(config.OFFICE_NAMES.get(o, o) for o in offices.split(",")))
        started = time.monotonic()
        key = self.keys.get("serpapi", "")
        error = skipped = None
        result = None
        if not key:
            skipped = self.why.get("serpapi", "没有配置 SerpApi 的 key")
        else:
            try:
                result = serpapi.patents(key, query, design, offices, after, 100, self.opener, granted=granted, language=language)
            except http.SourceError as exc:
                error = exc.message
            except Exception as exc:  # 意料之外的错误也只算这一路没查成
                error = "程序出错（%s）" % type(exc).__name__
        if result is None:
            for route in routes:
                self.record(route, source, shown, started, error=error, skipped=skipped or "")
            return None
        with self._lock:
            self.usage.add_source_call(source)
        return result, shown, started

    def foreign_patents(self, phrases: list, local: list) -> list:
        """已授权的发明。实用新型不另查的国家（日本）一起回来（号码以 U、Y 结尾），按类别各记一条检索记录。"""
        country = self.task.country
        plan = config.FOREIGN_PLAN[country]
        offices = plan["patent"]
        routes = ["patent"] + (["utility_model"] if not plan["utility"] and (country, "utility_model") not in config.NOT_APPLICABLE else [])
        query = self.text_query(phrases, local)
        got = self.foreign_call(routes, query, False, offices, "filing:%s" % numbers.years_ago(PATENT_YEARS, self.today))
        if got is None:
            return []
        result, shown, started = got
        docs = [dict(doc, via="relevance") for doc in result["docs"] if doc["right_type"] in routes]
        for route in routes:
            mine = [doc for doc in docs if doc["right_type"] == route]
            self.record(route, "SerpApi（Google Patents）", shown, started, docs=mine, total=result["total"] if len(result["docs"]) < result["total"] else None)
        if config.COUNTRIES[country]["lang"] != "en":
            self.notes.append("原文不是英文的专利和实用新型，比对用的是 Google Patents 的机器翻译，用词可能不准；评到中以上的请对照原文。")
        if "EP" in offices.split(","):
            self.notes.append("欧洲专利（EP 开头）授权后要在各国分别生效、逐年缴费；它在%s是否仍然有效本工具没有核实，评到中以上的请到欧洲专利局登记簿核对。"
                              % config.COUNTRIES[country]["name"])
        return docs

    def foreign_utility(self, phrases: list, local: list) -> list:
        """实用新型单独查的国家：只查本国局、不加"只要已授权"，留下号码以 U、Y 结尾的。"""
        office = config.FOREIGN_PLAN[self.task.country]["utility"]
        query = self.text_query(phrases, local)
        got = self.foreign_call(["utility_model"], query, False, office, "filing:%s" % numbers.years_ago(UTILITY_YEARS, self.today), granted=False)
        if got is None:
            return []
        result, shown, started = got
        docs = [dict(doc, via="relevance") for doc in result["docs"] if doc["right_type"] == "utility_model"]
        self.record("utility_model", "SerpApi（Google Patents）", shown, started, docs=docs,
                    total=result["total"] if len(result["docs"]) < result["total"] else None)
        return docs

    def euipo_designs(self, phrases: list):
        """欧盟外观走欧盟知识产权局的官方接口（有图）。查成了返回清单（可以是空的）；没查成返回 None，由调用方退回只有名单的来源。"""
        query = euipo.query_of(phrases)
        if not query:
            return None
        got = self.guarded("design", euipo.SOURCE, query, lambda: euipo.search(phrases, 100, self.opener), optional=True)
        if got is None:
            return None
        result, started = got
        docs = [dict(doc, via="relevance") for doc in result["docs"]]
        self.record("design", euipo.SOURCE, query, started, docs=docs, total=result["total"])
        return docs

    def foreign_designs(self, phrases: list, local: list) -> list:
        country = self.task.country
        office = config.FOREIGN_PLAN[country]["design"]
        if not office:
            return []
        if office == "EM" and euipo.ready():
            docs = self.euipo_designs(phrases)
            if docs is not None:
                return docs
        english = office == "EM" and bool(phrases)  # 欧盟外观每种语言各一条记录、品名都有英文：只查英文的那一条（没有英文叫法时才用当地叫法）
        # 外观的标题只是几个品名：用"几个词都出现"来查，不用整句
        query = " OR ".join("(%s)" % p for p in [p.lower() for p in phrases] + ([] if english else list(local)))
        since = numbers.years_ago(25, self.today)
        got = self.foreign_call(["design"], query, True, office, "filing:%s" % since, granted=office != "EM", language="ENGLISH" if english else "")
        if got is None:
            return []
        result, shown, started = got
        docs, seen = [], set()
        for doc in result["docs"]:
            if doc["right_type"] == "design" and doc["number"] not in seen:  # 同一件的几种语言只算一件
                seen.add(doc["number"])
                docs.append(dict(doc, via="relevance"))
        more = result["total"] > len(result["docs"])  # 来源那边还有没取回来的
        self.record("design", "SerpApi（Google Patents）", shown, started, docs=docs[:FOREIGN_DESIGN_KEEP],
                    total=result["total"] if more else len(docs) if len(docs) > FOREIGN_DESIGN_KEEP else None)
        return docs[:FOREIGN_DESIGN_KEEP]

    # ---- 商标 ----
    def trademarks(self, terms: list, left_out: list, blind: bool, branded: list = ()) -> list:
        source = "Signa（商标库）"
        started = time.monotonic()
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
        source = "Serper（以图搜图）"
        started = time.monotonic()
        key = self.keys.get("serper", "")
        url = next((i.get("url") for i in self.task["product"].get("images") or [] if str(i.get("url") or "").startswith("https://")), "")
        if not url:
            self.record("artwork", source, "", started, skipped="这一单的商品图没有网址（资料入口），没法以图搜图")
            return
        if not key:
            self.record("artwork", source, url, started, skipped=self.why.get("serper", "没有配置 Serper 的 key"))
            return
        got = self.guarded("artwork", source, url, lambda: serper.lens(key, url, self.opener))
        if got is None:
            return
        result, began = got
        self.lens = result[:LENS_KEEP]
        self.record("artwork", source, url, began, docs=result)

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
        terms, left_out, branded = trademark_terms(understanding, product.get("brand", ""))
        self.check_capacity()
        country_name = config.COUNTRIES[self.task.country]["name"]
        results = {}
        with ThreadPoolExecutor(max_workers=6) as pool:
            jobs = {}
            foreign = self.task.country != "US"
            local = [] if blind else [local_term(n) for n in understanding.get("local_names") or [] if local_term(n)][:3]
            if phrases and not foreign:
                jobs["design_title"] = pool.submit(self.design_by_title, phrases)
                jobs["design_serpapi"] = pool.submit(self.design_by_serpapi, phrases)
                jobs["patent_text"] = pool.submit(self.patent_by_text, phrases)
                jobs["patent_claims"] = pool.submit(self.patent_by_claims, phrases)
            elif (phrases or local) and foreign:
                jobs["foreign_patent"] = pool.submit(self.foreign_patents, phrases, local)
                if config.FOREIGN_PLAN[self.task.country]["utility"]:
                    jobs["foreign_utility"] = pool.submit(self.foreign_utility, phrases, local)
                if config.FOREIGN_PLAN[self.task.country]["design"]:
                    jobs["foreign_design"] = pool.submit(self.foreign_designs, phrases, local)
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
        patent_docs = ((results.get("patent_text") or []) + (results.get("patent_claims") or []) + (results.get("foreign_patent") or [])
                       + (results.get("foreign_utility") or []))
        candidates = self.merge(patent_docs + design_docs) + self.trademark_candidates(results.get("trademark") or []) + self.artwork_candidates(hypotheses)
        if blind:
            self.notes.append("产品理解没有完成，检索词取自标题（%s），可能不准。" % ("、".join(phrases) or "没有取到"))
        self.notes.append("只检索已授权的专利和外观；还没授权的申请公开不能用来主张权利，没有检索。" if not foreign else
                          "发明只检索已授权的（申请公开不能用来主张权利）；实用新型和欧盟外观登记即生效，检索的是已登记的。")
        self.records.sort(key=lambda r: int(r["id"][1:]))
        return {"searches": self.records, "candidates": candidates, "lens": self.lens, "enforcement": self.enforcement, "notes": self.notes}

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
        merged, order = {}, []
        for doc in docs:
            key = numbers.us_key(doc["number"]) or doc["number"]
            if key not in merged:
                merged[key] = dict(doc, id=("D-" if doc["right_type"] == "design" else "P-") + key, sources=[doc["source"]], via=[doc.get("via", "")])
                order.append(key)
                continue
            kept = merged[key]
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
            if cand.get("legal_status") == "已失效":
                dead += 1
                continue
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
            self.notes.append("来源写明已失效的 %d 件，没有列入候选。" % dead)
        return out

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
