#!/usr/bin/env python3
"""禁限售合规排查 CLI（lc-amazon-compliance-screening）。Python 3.9+；xlsx 需要 openpyxl。

  python3 scripts/csc.py quick  --title "..." [--bullet "..."]... [--url <链接>] [--sites US,UK] [--out <目录>]   （单个商品快速初判）
  python3 scripts/csc.py table  --input 商品表.xlsx [--out 结果.xlsx] [--site US] [--pages pages.json]   （整表初判，表尾加列）
  python3 scripts/csc.py init   --input product.json --sites US,DE,JP [--fulfillment FBA] --task <新目录>
  python3 scripts/csc.py match  --task <目录> --profile <画像.json>
  python3 scripts/csc.py review --task <目录> --file <处置.json>
  python3 scripts/csc.py render --task <目录>
  python3 scripts/csc.py status --task <目录>
"""
import argparse
import hashlib
import json
import pathlib
import shutil
import sys
import time
import csc_runtime as runtime
from auth_gate import AuthError, require_auth

if sys.version_info < (3, 9):
    raise SystemExit("Python 3.9+ required; Python 3.12 recommended.")

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import compliance_engine as ce  # noqa: E402
import csc_table as ct  # noqa: E402
from compliance_engine.common import KIND_ZH, SITE_ZH  # noqa: E402

PACK_PATH = HERE.parent / "data" / "rulepack.json"
BUSINESS_PATH = HERE.parent / "data" / "business.json"
IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
MAX_IMAGES = 12


def out(obj, code=0):
    print(json.dumps(obj, ensure_ascii=False, indent=1))
    sys.exit(code)


def read_json(path):
    return runtime.read_json(path)


def write_json(path, obj):
    tmp = pathlib.Path(str(path) + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(path)


def strip_private(obj):
    """Drop helper keys (starting with "_") from analyst-written JSON."""
    if isinstance(obj, dict):
        return {k: strip_private(v) for k, v in obj.items() if not str(k).startswith("_")}
    if isinstance(obj, list):
        return [strip_private(v) for v in obj]
    return obj


def load_task(task):
    task = pathlib.Path(task)
    state = task / "task.json"
    if not state.exists():
        out({"ok": False, "error": f"不是任务目录：{task}（先运行 init）"}, 2)
    return task, read_json(state)


def cmd_init(a):
    pack = ce.RulePack.load(PACK_PATH)
    sites = [s.strip().upper() for s in a.sites.split(",") if s.strip()]
    bad = [s for s in sites if s not in ce.SITES]
    if not sites or bad:
        out({"ok": False, "error": f"站点无效：{bad or '空'}；可选 {','.join(ce.SITES)}"}, 2)
    src = read_json(a.input)
    task = pathlib.Path(a.task)
    if task.exists() and any(task.iterdir()):
        out({"ok": False, "error": f"任务目录已存在且非空：{task}；请换一个新目录"}, 2)
    (task / "images").mkdir(parents=True, exist_ok=True)
    images = []
    paths = list(src.get("images") or []) + list(a.image or [])
    base = pathlib.Path(a.input).resolve().parent
    for p in paths[:MAX_IMAGES]:
        p = pathlib.Path(p)
        if not p.is_absolute():
            p = base / p
        if not p.is_file() or p.suffix.lower() not in IMAGE_EXT:
            out({"ok": False, "error": f"图片不存在或格式不支持：{p}"}, 2)
        iid = f"img-{len(images) + 1}"
        dest = task / "images" / f"{iid}{p.suffix.lower()}"
        shutil.copyfile(p, dest)
        images.append({"id": iid, "role": "main" if not images else "gallery", "file": f"images/{dest.name}",
                       "sha256": hashlib.sha256(dest.read_bytes()).hexdigest()})
    product = {k: src.get(k) for k in ("title", "bullets", "description", "brand", "asin", "url", "source_site", "notes")}
    if not str(product.get("title") or "").strip():
        out({"ok": False, "error": "资料缺少 title（商品标题或一句话描述）"}, 2)
    product["bullets"] = [str(b) for b in (product.get("bullets") or [])]
    facts = ce.make_facts(product, images, sites, a.fulfillment, user=src.get("user") or {})
    write_json(task / "facts.json", facts)
    write_json(task / "profile.template.json", ce.profile_template(pack, facts))
    state = {"schema": "csc-task-v1", "created_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "sites": sites,
             "step": "initialized", "ruleset": pack.summary(), "engine": ce.ENGINE_VERSION,
             "attempts": {"profile": 0, "review": 0}}
    write_json(task / "task.json", state)
    out({"ok": True, "task": str(task), "sites": sites, "images": [i["file"] for i in images],
         "facts_digest": facts["facts_digest"], "ruleset": pack.version,
         "next": "打开 images/ 里的每张图，阅读 facts.json，照 profile.template.json 填好画像后运行 match"})


def cmd_match(a):
    task, state = load_task(a.task)
    pack = ce.RulePack.load(PACK_PATH)
    facts = read_json(task / "facts.json")
    raw = strip_private(read_json(a.profile))
    state["attempts"]["profile"] += 1
    profile, errors = ce.validate_profile(pack, facts, raw)
    if errors:
        write_json(task / "task.json", state)
        out({"ok": False, "step": "profile", "attempt": state["attempts"]["profile"], "errors": errors}, 2)
    m = ce.match(pack, profile, facts, state["sites"])
    write_json(task / "profile.json", profile)
    write_json(task / "candidates.json", m)
    write_json(task / "review.template.json", ce.review_template(m, state["sites"]))
    state["step"] = "matched"
    write_json(task / "task.json", state)
    summary = {}
    for c in m["candidates"]:
        s = summary.setdefault(c["site"], {})
        s[c["kind"]] = s.get(c["kind"], 0) + 1
    questions = sorted({q for c in m["candidates"] for q in c.get("questions") or []})
    out({"ok": True, "candidates": summary, "to_review": sum(1 for c in m["candidates"] if c["kind"] != "general"),
         "open_questions": questions[:30],
         "next": "逐条处置 review.template.json 里的候选（规则原文见 rulepack 或 references），存为新文件后运行 review"})


def cmd_review(a):
    task, state = load_task(a.task)
    if state["step"] not in ("matched", "reviewed", "rendered"):
        out({"ok": False, "error": "请先运行 match"}, 2)
    pack = ce.RulePack.load(PACK_PATH)
    facts = read_json(task / "facts.json")
    profile = read_json(task / "profile.json")
    m = read_json(task / "candidates.json")
    review = strip_private(read_json(a.file))
    state["attempts"]["review"] += 1
    errors = ce.validate_review(pack, m, review, profile, facts, state["sites"])
    if errors:
        write_json(task / "task.json", state)
        out({"ok": False, "step": "review", "attempt": state["attempts"]["review"], "errors": errors}, 2)
    images_viewed = bool(facts.get("images"))
    assessment = ce.assess(pack, m, review, profile, state["sites"],
                           {s: {"images_viewed": images_viewed,
                                "gaps": ["未查询亚马逊账号级审核状态（Skill 不调用 SP-API）"]} for s in state["sites"]})
    write_json(task / "review.json", review)
    write_json(task / "assessment.json", assessment)
    state["step"] = "reviewed"
    write_json(task / "task.json", state)
    out({"ok": True, "report_mode": assessment["report_mode"],
         "sites": {r["site"]: {"verdict": r["verdict"], "fba": r["fba"], "confidence": r["confidence"]}
                   for r in assessment["sites"]}, "next": "运行 render 生成报告"})


def cmd_render(a):
    task, state = load_task(a.task)
    if state["step"] not in ("reviewed", "rendered"):
        out({"ok": False, "error": "请先通过 review"}, 2)
    pack = ce.RulePack.load(PACK_PATH)
    facts = read_json(task / "facts.json")
    profile = read_json(task / "profile.json")
    assessment = read_json(task / "assessment.json")
    business_results = {r["site"]: _formal_mark(pack, profile, facts, r) for r in assessment["sites"]}
    view = ce.build_view(pack, facts, assessment, assessment["report_mode"], profile,
                         {"engine": ce.ENGINE_VERSION, "business_results": business_results,
                          "coverage_note_zh": "本 Skill 未查询亚马逊账号级审核状态；上架前请在后台 Add Products 查看该商品是否显示「申请销售」。"})
    write_json(task / "report_data.json", view)
    (task / "report.html").write_text(ce.render_html(view), encoding="utf-8")
    (task / "report.md").write_text(ce.render_markdown(view), encoding="utf-8")
    runtime.write_csv(task / "findings.csv", ce.render_csv(view))
    state["step"] = "rendered"
    write_json(task / "task.json", state)
    out({"ok": True, "report": str(task / "report.html"), "markdown": str(task / "report.md"),
         "csv": str(task / "findings.csv"), "mode": view["mode"],
         "classification_complete": view["classification_complete"], **_summary(view["sites"]),
         "sites": [{"site": s["site"], "mark": s["mark"], "detail": s["detail"],
                    "verdict_zh": s["verdict_zh"], "decision_zh": s["decision_zh"]} for s in view["sites"]]})


def _business_tables():
    try:
        return read_json(BUSINESS_PATH)
    except (OSError, ValueError):
        return {}


def _apply_category(pack, prof, cat):
    """The agent's classification (closed family list + traits) replaces keyword families; traits become attributes."""
    prof["families"] = [{"id": f, "evidence": ["agent"]} for f in cat.get("families") or [] if f in pack.families]
    attrs = prof["attributes"]

    def put(k, v):
        attrs.setdefault(k, {"value": v, "status": "inferred", "evidence": ["agent"]})
    if cat.get("children") is not None:
        put("user.primarily_children", bool(cat["children"]))
    if cat.get("battery") == "lithium":
        put("battery.included", True)
        put("battery.chemistry", ["li_ion"])
    elif cat.get("battery") == "other":
        put("battery.included", True)
    elif cat.get("battery") == "none":
        put("battery.included", False)
    if cat.get("wireless") is False:
        put("radio.technologies", [])
    if cat.get("mains") is True:
        put("power.source", ["mains_ac"])
    if cat.get("primary_form") in ("liquid", "paste_gel", "other"):
        put("substance.primary_form", cat["primary_form"])


def _screen(pack, product, site, cat=None, typical=None):
    """Quick screen of one site. A ban/approval threshold the text leaves open (blade length, laser power, e-mobility
    power/speed) is filled with the category's usual value and the site is screened again, so the row still gets a
    definite mark; the reason column names the assumed value."""
    text = " ".join([str(product.get("title") or "")] + [str(b) for b in product.get("bullets") or []]
                    + [str(product.get("description") or "")])
    nums = ct.extract_numbers(text)
    nums.update(typical or {})
    catalog = {"profile_attributes": {a: v for a, (v, _q) in nums.items()}} if nums else None
    facts = ce.make_facts(product, [], [site], "unknown", catalog=catalog)
    if cat:
        import importlib  # the package re-exports functions named match/profile, so import the modules by path
        _m, _p, _r = (importlib.import_module("compliance_engine." + n) for n in ("match", "profile", "review"))
        prof = _p.quick_profile(pack, facts)
        _apply_category(pack, prof, cat)
        m = _m.match(pack, prof, facts, [site], {site: []}, quick=True)
        s = {"site": site, "profile": prof, "match": m, "result": _r.quick_assess(pack, m, prof, site, None),
             "families": [f["id"] for f in prof["families"]]}
    else:
        s = ce.quick_screen(pack, facts, site)
    s["numbers"] = nums
    s["cat"] = cat
    for c in s["match"]["candidates"]:
        rule = pack.rules.get(c.get("rule_id") or "")
        if rule and c["kind"] == "possible":
            # waits on a number AND the product is the kind that number is about (a knife rule does not wait on a
            # toy just because "has a blade" is unknown)
            trig = json.dumps(rule["triggers"])
            unknown = set(c.get("unknown_attrs") or [])
            fams = set(s["families"])
            # a missing *threshold* (length, power, speed) is worth asking about; a missing mechanism alone is not:
            # switchblades and the like are named in titles and caught by keywords
            c["_numeric_rule"] = bool(unknown & ct.THRESHOLDS) and any(
                f'"attr": "{a}"' in trig and fams & fs
                for a in ct.NUMERIC for prefix, fs in ct.NUMERIC_FAMILIES.items() if a.startswith(prefix))
    if nums:
        from compliance_engine.match import _Eval
        bare = dict(s["profile"], attributes={k: v for k, v in s["profile"]["attributes"].items() if k not in nums})
        ev = _Eval(pack, bare)
        for c in s["match"]["candidates"]:
            rule = pack.rules.get(c.get("rule_id") or "")
            # the number decided it: triggered now, not triggered (or undecidable) without the numbers
            if rule and c["kind"] == "triggered" and ev.cond(rule["triggers"]) is not True:
                c["_numeric_decisive"] = True
    if typical is None:
        waiting = ct.numeric_flags(s)[1]
        wanted = {a for c in waiting for a in c.get("unknown_attrs") or []} & ct.THRESHOLDS
        typ = ct.typical_numbers(text, s["families"], (nums.get("blade.mechanism") or (None,))[0], wanted - set(nums))
        if typ:
            again, facts = _screen(pack, product, site, cat, typ)
            hit = {c["rule_id"] for c in again["match"]["candidates"] if c["kind"] == "triggered"}
            again["typical"] = typ
            again["spared"] = [c for c in waiting if c["rule_id"] not in hit]
            return again, facts
    return s, facts


def _mark(screen, pack, tables):
    table = tables.get(screen["site"])
    c = ct.business(screen, table, screen.get("cat"), pack) if table else ct.classify(screen, pack)
    return ct.finalize_mark({k: v for k, v in c.items() if k not in ("paid", "describe", "maybe")}, screen.get("cat"))


def _formal_mark(pack, profile, facts, result):
    """Display the business policy alongside, never in place of, the reviewed legal/FBA verdict."""
    from compliance_engine.profile import texts
    attrs = profile.get("attributes") or {}
    value = lambda key: None if (attrs.get(key) or {}).get("status") == "unknown" else (attrs.get(key) or {}).get("value")
    shape = attrs.get("substance.primary_form") or {}
    evidence = texts(facts)
    cat = {"primary_form": value("substance.primary_form") or "unknown",
           "form_evidence": shape.get("note") or "；".join(evidence.get(r, r) for r in shape.get("evidence") or []),
           "children": value("user.primarily_children"),
           "wireless": None if value("radio.technologies") is None else bool(value("radio.technologies")),
           "mains": None if value("power.source") is None else "mains_ac" in value("power.source"),
           "battery": (None if value("battery.included") is None else "none" if value("battery.included") is False
                       else "lithium" if "li_ion" in (value("battery.chemistry") or []) else "other")}
    if not shape:
        cat.pop("primary_form")  # Legacy saved profiles must not silently pass the new classification gate.
    families = [f["id"] for f in profile.get("families") or []]
    table = _business_tables().get(result["site"])
    mark, detail, paid, supplier = ct.table_mark(table, families, cat, pack) if table else ("未发现限制", "本规则库未匹配到限制", [], [])
    if result["verdict"] in ("prohibited", "approval_required"):
        mark = "禁售" if result["verdict"] == "prohibited" else "需平台审核"
        detail = mark + "：" + ct.reasons_of(result.get("applied") or []) + "。原合规要求：" + detail
    elif result["verdict"] == "needs_info":
        mark = "无法判断"
        detail = "完整排查尚有待补信息。已有合规要求：" + detail
    c = {"mark": mark, "detail": detail, "paid_items": paid, "factory_items": supplier}
    return ct.finalize_mark(c, cat)


def _summary(rows):
    from collections import Counter
    return {"requirement_counts": {kind: dict(Counter(item for row in rows for item in dict.fromkeys(row.get(kind) or [])))
                                    for kind in ("paid_items", "factory_items")},
            "logistics_count": sum(bool(row.get("logistics_restricted")) for row in rows),
            "logistics_products": [{k: row[k] for k in ("row", "title", "url", "site", "mark", "detail") if k in row}
                                   for row in rows if row.get("logistics_restricted")]}


class _Fetcher:
    """Best-effort page reader with a breaker: after 3 failures in a row it stops trying (Amazon usually serves a
    captcha to scripts); the agent then reads the remaining pages with its own web tool and passes --pages."""
    def __init__(self, mode, budget):
        self.mode, self.budget, self.fails, self.last, self.used = mode, budget, 0, 0.0, 0

    def get(self, url):
        if self.mode == "never" or not url or self.used >= self.budget or self.fails >= 3:
            return None, "未尝试读取商品页"
        self.last = ct.politeness(self.last)
        self.used += 1
        page, err = ct.fetch_page(url)
        self.fails = 0 if page else self.fails + 1
        return page, err


def _merge_page(product, page):
    p = dict(product)
    if page.get("title") and not str(p.get("title") or "").strip():
        p["title"] = page["title"]
    elif page.get("title") and page["title"] not in p["title"]:
        p["description"] = " ".join(filter(None, [page["title"], p.get("description")]))
    p["bullets"] = list(p.get("bullets") or []) + [str(b) for b in page.get("bullets") or []]
    p["description"] = " ".join(filter(None, [p.get("description"), page.get("description")]))
    if page.get("final_url") or page.get("url"):
        p["url"] = page.get("final_url") or page["url"]
    return p


def cmd_quick(a):
    """Screen complete text with agent-supplied semantic categories; URL-only input first yields page evidence."""
    pack = ce.RulePack.load(PACK_PATH)
    src = read_json(a.input) if a.input else {}
    for k in ("title", "description", "brand", "asin", "url", "notes"):
        if getattr(a, k, None):
            src[k] = getattr(a, k)
    if a.bullet:
        src["bullets"] = a.bullet
    product = {k: src.get(k) for k in ("title", "bullets", "description", "brand", "asin", "url", "source_site", "notes")}
    product["bullets"] = [str(b) for b in (product.get("bullets") or [])]
    cat = _read_category(a.category) if a.category else None
    if ct.category_error(cat):
        out({"ok": False, "error": ct.category_error(cat)}, 2)
    tables = _business_tables()
    page_note = None
    if a.page:
        product = _merge_page(product, read_json(a.page))
        page_note = "已读取商品页"
    url_site, url_err = ct.site_of_url(product.get("url"))
    if product.get("url") and not a.page and (not str(product.get("title") or "").strip() or not url_site):
        page, err = _Fetcher(a.fetch, 1).get(product["url"])
        if page:
            product, page_note = _merge_page(product, page), "已读取商品页"
            cat = None  # Fresh page evidence must be classified before a final conclusion is emitted.
        else:
            page_note = err
    if not str(product.get("title") or "").strip():
        out({"ok": False, "error": "缺少标题：请用网页工具读出标题和五点后用 --title/--bullet 或 --page 传入",
             "page": page_note}, 2)
    url_site, url_err = ct.site_of_url(product.get("url"))
    if product.get("url") and not url_site and not a.sites:
        out({"ok": False, "error": url_err or "无法从商品链接识别站点，请提供完整链接或指定 --sites",
             "product_for_classification": product, "page": page_note}, 2)
    sites = [s.strip().upper() for s in (a.sites or url_site or ",".join(ce.SITES)).split(",") if s.strip()]
    bad = [s for s in sites if s not in ce.SITES]
    if not sites or bad:
        out({"ok": False, "error": f"站点无效：{bad or '空'}；可选 {','.join(ce.SITES)}"}, 2)
    screens = [_screen(pack, product, s, cat)[0] for s in sites]
    business_results = {x["site"]: _mark(x, pack, tables) for x in screens}
    facts = ce.make_facts(product, [], sites, a.fulfillment)
    profile = screens[0]["profile"]
    results = [x["result"] for x in screens]
    view = ce.build_view(pack, facts, {"sites": results}, "quick", profile,
                         {"engine": ce.ENGINE_VERSION, "business_results": business_results,
                          "coverage_note_zh": "快速初判根据标题、亮点、产品卖点及描述做语义分类和规则匹配，没有看图；"
                                              "物流运输强限制为选品口径，不等于危险品或法定禁运。未完成主体形态分类的输出仅为中间稿。"})
    files = {}
    if a.out:
        d = pathlib.Path(a.out)
        d.mkdir(parents=True, exist_ok=True)
        write_json(d / "facts.json", facts)
        write_json(d / "quick_result.json", view)
        (d / "report.html").write_text(ce.render_html(view), encoding="utf-8")
        (d / "report.md").write_text(ce.render_markdown(view), encoding="utf-8")
        runtime.write_csv(d / "findings.csv", ce.render_csv(view))
        files = {"report": str(d / "report.html"), "markdown": str(d / "report.md"), "csv": str(d / "findings.csv")}
    rows, general = [], {}
    for s, x in zip(view["sites"], screens):
        c = business_results[x["site"]]
        general[s["site"]] = [f"[{q.get('kind_zh')}] {q['name_zh']}" for q in s.get("general_obligations") or []]
        rows.append({
            **c, "site": s["site"], "site_zh": s["site_zh"],
            "verdict": s["verdict"], "verdict_zh": s["verdict_zh"], "fba_zh": s["fba_zh"],
            "why": [f"{x['rule_id']} {x['topic_zh']}" for x in (s.get("applied") or [])][:a.limit],
            "requirements": [f"[{q.get('kind_zh')}] {q['name_zh']}" for q in (s.get("requirements") or [])][:a.limit],
            "reminders": [r.get("text_zh") or r.get("topic_zh") or str(r) for r in (s.get("reminders") or [])][:5],
            "open_questions": (s.get("open_questions") or [])[:5]})
    hint = []
    if not ct.category_complete(cat):
        hint.append("主体形态尚未语义分类，本次为中间稿；按 product_for_classification 分类，再用 --page 和 --category 重跑")
    if url_err:
        hint.append(url_err)
    if cat is None and any(s in tables for s in sites):
        hint.append("没有传 --category：品类按关键词识别，可能漏判。请按 `csc.py families` 的清单判断品类和特征后用 --category 重跑")
    elif not profile["families"] and cat is None:
        hint.append("没有从文字里识别出产品类别，「未发现限制」的可信度很低；请读取商品页补充五点/描述，或走完整排查")
    if any(r["mark"] in ("禁售", "需平台审核") for r in rows):
        hint.append("标记和原因就是结论，原样答复用户，不要改档或追加待确认问题；用户对某站有疑问时才走完整排查")
    out({"ok": True, "mode": "quick", "ruleset": pack.version, "page": page_note,
         "classification_complete": ct.category_complete(cat),
         **({"product_for_classification": product} if not ct.category_complete(cat) else {}),
         **_summary(rows),
         "families": [pack.families.get(f["id"], {}).get("zh", f["id"]) for f in profile["families"]],
         "claims": [c["id"] for c in profile["claims"]], "sites": rows,
         "general_obligations_note": "各站通用义务（账号层面做一次，不计入标记）见报告「该站通用义务」",
         **files, "next": hint})


def cmd_table(a):
    """Screen every row of a product table; append 判定站点 / 禁限售标记 / 原因/所需认证 and save a new file."""
    import collections
    pack = ce.RulePack.load(PACK_PATH)
    try:
        kind, sheet, rows = ct.read_table(a.input, a.sheet)
    except (ValueError, KeyError, OSError) as e:
        out({"ok": False, "error": f"读不了表格：{e}"}, 2)
    if not rows:
        out({"ok": False, "error": "表格是空的"}, 2)
    h = a.header_row - 1 if a.header_row else ct.find_header(rows)
    try:
        cols = ct.detect_columns(rows[h], {"title": a.title_col, "url": a.url_col, "bullets": a.bullets_col,
                                           "site": a.site_col, "description": a.description_col})
    except ValueError as e:
        out({"ok": False, "error": str(e)}, 2)
    if "title" not in cols and "url" not in cols:
        out({"ok": False, "error": "表头里找不到标题列或链接列；用 --title-col / --url-col 指定（列名或列字母）",
             "header": rows[h]}, 2)
    default_site = (a.site or "").upper() or None
    if default_site and default_site not in ce.SITES:
        out({"ok": False, "error": f"--site 无效：{default_site}；可选 {','.join(ce.SITES)}"}, 2)
    pages = read_json(a.pages) if a.pages else {}
    cats = read_json(a.categories) if a.categories else {}
    if not isinstance(cats, dict):
        out({"ok": False, "error": "categories 必须是按行号索引的 JSON 对象"}, 2)
    for row, cat in cats.items():
        error = ct.category_error(cat)
        if error:
            out({"ok": False, "error": f"第 {row} 行：{error}"}, 2)
    tables = _business_tables()
    uncategorized = []
    fetcher = _Fetcher(a.fetch, a.max_fetch)
    new_cols, general, todo = {}, collections.OrderedDict(), []
    result_rows, resolved_pages = [], {}
    counts = collections.Counter()
    for i in range(h + 1, len(rows)):
        r = rows[i]
        if not any(str(v).strip() for v in r):
            continue
        get = lambda f: [str(r[j]).strip() for j in cols.get(f, []) if j < len(r) and str(r[j]).strip()]  # noqa: E731
        url = (get("url") or [""])[0]
        product = {"title": (get("title") or [""])[0], "url": url or None,
                   "bullets": [b for cell in get("bullets") for b in cell.splitlines() if b.strip()],
                   "description": (get("description") or [""])[0] or None}
        page = pages.get(str(i + 1)) or (pages.get(url) if url else None)
        note = ""
        cat = cats.get(str(i + 1))
        if page:
            product, note = _merge_page(product, page), "（已读取商品页）"
        site, err = ct.site_of_url(product.get("url"))
        if not page and (not product["title"] or not site) and url:
            got, ferr = fetcher.get(url)
            if got:
                product, note = _merge_page(product, got), "（已读取商品页）"
                resolved_pages[str(i + 1)] = got
                cat = None  # A supplied category cannot predate newly retrieved evidence.
            else:
                todo.append({"row": i + 1, "url": url, "reason": ferr})
                note = f"（只按表格文字判断：{ferr}）" if product["title"] else ""
        if not ct.category_complete(cat):
            uncategorized.append({"row": i + 1, **product})
        site, err = ct.site_of_url(product.get("url"))
        site = site or ct.norm_site((get("site") or [""])[0]) or default_site
        if not site or site not in ce.SITES:
            msg = err or (f"站点不在覆盖范围（{site}）" if site else "看不出站点：没有亚马逊链接，也没有站点列；可用 --site 指定默认站点")
            new_cols[i] = ["", "无法判断", msg]
            counts["无法判断"] += 1
            continue
        screen = _screen(pack, product, site, cat)[0] if product["title"] else None
        if screen is None:
            new_cols[i] = [SITE_ZH[site], "无法判断", "表格里没有标题，商品页也没读到；请补标题或读取商品页后重跑"]
            counts["无法判断"] += 1
            continue
        c = _mark(screen, pack, tables)
        result_rows.append({"row": i + 1, "title": product["title"], "url": product.get("url"), "site": site, **c})
        new_cols[i] = [SITE_ZH[site], c["mark"], c["detail"] + note]
        counts[c["mark"]] += 1
        g = general.setdefault(site, collections.OrderedDict())
        for q in screen["result"].get("general_obligations") or []:
            g.setdefault((KIND_ZH.get(q.get("kind"), q.get("kind")), q["name_zh"]), q.get("detail_zh") or "")
    header = ["判定站点", "禁限售标记", "原因/所需认证（各站通用义务见「通用义务」表）"]
    notes = [["站点", "类型", "事项（账号层面做一次，不计入每个商品的标记）", "说明"]]
    for site, items in general.items():
        notes += [[SITE_ZH[site], k, n, d] for (k, n), d in items.items()]
    notes += [[], ["说明", f"规则库 {pack.version}；生成于 {time.strftime('%Y-%m-%d %H:%M')}"],
              ["标记", "禁售 › 需平台审核 › 物流运输强限制 › 需要付费认证 › 需工厂提供证书 › 需单独描述 › 未发现限制（一行显示最重的一档，其余事项附在后面）；缺少资料的行为「无法判断」"],
              ["物流运输强限制", ct.LOGISTICS_NOTE],
              ["分类状态", "已完成语义分类" if not uncategorized else "中间稿：主体形态未全部分类，不能作为最终筛查表交付"],
              ["判定方式", "粗筛每行都给结论：文字没写的参数和特征按该品类最常见的配置判断（如固定刃刀刃长约 10 cm、充电小电器为内置锂电），原因列写明「按常见规格/按常见情形判定」及超出时的结果；"
                          "禁售规则尚待核实但商品明确属于该情形的，按禁售处理并注明「政策依据待核实」"],
              ["口径", "需要付费认证 = 必须以你的名义办理或每个 Listing 都要做的付费事项；需工厂提供证书 = 产品级证书向工厂要，工厂没有才需付费；保险不计入。"
                       + ("有业务口径表的站点（%s）按口径表定档，表外的禁售/审核仍按规则库" % "、".join(SITE_ZH[x] for x in tables)
                          if tables else "")],
              ["局限", "快速初判只看标题/五点/描述，不看图；没写的数值按常见规格假设；"
                       "未查亚马逊账号级审核状态。不构成法律意见。"]]
    out_path = pathlib.Path(a.out or (str(pathlib.Path(a.input).with_suffix("")) + "_禁限售" +
                                      (".csv" if kind == "csv" else ".xlsx")))
    if out_path.resolve() == pathlib.Path(a.input).resolve():
        out({"ok": False, "error": "输出文件不能覆盖原表"}, 2)
    extra = [("通用义务", notes, [12, 14, 70, 50])]
    mode = ct.write_table(a.input, kind, sheet, h, rows, header, new_cols, extra, str(out_path))
    files = {"table": str(out_path)}
    if resolved_pages:
        rp = out_path.with_name(out_path.stem + "_已读页面.json")
        write_json(rp, resolved_pages)
        files["pages_read"] = str(rp)
    if kind == "csv":
        side = out_path.with_name(out_path.stem + "_通用义务.csv")
        with open(side, "w", encoding="utf-8-sig", newline="") as fh:
            import csv as _csv
            _csv.writer(fh).writerows([[ct._csv_safe(v) for v in r] for r in notes])
        files["general_obligations"] = str(side)
    if uncategorized:
        cp = out_path.with_name(out_path.stem + "_待分类.json")
        write_json(cp, uncategorized)
        files["categories_todo"] = str(cp)
    if todo:
        tp = out_path.with_name(out_path.stem + "_待读页面.json")
        write_json(tp, todo)
        files["pages_todo"] = str(tp)
    out({"ok": True, "rows": sum(counts.values()), "marks": dict(counts), "written_as": mode, **files,
         "classification_complete": not uncategorized, **_summary(result_rows),
         "pages_fetched": fetcher.used, "pages_todo_count": len(todo), "uncategorized": len(uncategorized),
         "next": [x for x in [
             ("有 %d 行还没有分类：运行 `csc.py families` 看品类清单，按 *_待分类.json 逐行判断品类和特征，存为 "
              "categories.json 后加 --categories 重跑（不分类时按关键词识别，漏判多）" % len(uncategorized)) if uncategorized else "",
             ("有 %d 行只按标题判断或没读到商品页：用网页工具打开 *_待读页面.json 里的链接，把标题/五点/描述写成 "
              "{\"行号\": {\"title\": ..., \"bullets\": [...], \"description\": ...}} 存为 pages.json，"
              "加 --pages pages.json 重跑" % len(todo)) if todo else ""] if x]})


def _read_category(value):
    """--category: a JSON object or a path to one: {families, children, battery, wireless, mains}."""
    v = value.strip()
    try:
        return json.loads(v) if v.startswith("{") else read_json(v)
    except (OSError, ValueError) as e:
        out({"ok": False, "error": f"--category 不是有效的 JSON：{e}"}, 2)


def cmd_families(a):
    pack = ce.RulePack.load(PACK_PATH)
    out({"ok": True,
         "families": {f: v["zh"] for f, v in pack.families.items() if f != "packaging_any"},
         "traits": {"children": "主要供 12 岁及以下儿童使用：true / false / null（看不出）",
                    "primary_form": "商品主体形态：liquid 液体 / paste_gel 膏霜凝胶 / other 其他 / unknown 无法判断；由模型综合全部文字判断",
                    "form_evidence": "形态原文片段或语义依据，已知形态必填；常见形态推断另写 assume",
                    "battery": "lithium（内置可充电锂电/USB 充电）/ button（纽扣/硬币电池，含遥控器里的 CR2032、LR44）/ other（干电池、镍氢）/ none / null",
                    "wireless": "蓝牙、Wi-Fi、射频遥控、App 控制、无线发射：true / false / null",
                    "mains": "插墙上插座供电：true / false / null"},
         "flags": {k: v for t in _business_tables().values() for k, v in
                   ((f, e["ask_zh"]) for f, e in (t.get("flags") or {}).items() if e.get("ask_zh"))},
         "shape": {"<行号>": {"families": ["lighting"], "children": False, "battery": "lithium",
                              "primary_form": "other", "form_evidence": "商品是灯具，不以液体或膏体为主体",
                              "wireless": False, "mains": False, "flags": ["seasonal_lighting"],
                              "assume": "未写电池类型，按 USB 充电的内置锂电判定"}},
         "rules_zh": ["按商品「是什么」选 0–3 个品类，不按「配合什么用」；参考亚马逊类目节点",
                      "必须综合标题、亮点、产品卖点及描述判断商品主体形态，不按液体/膏等单词机械匹配；发泥面霜精油命中，空瓶工具固体香皂造型摆件不命中，仅附带少量液体的器具也不命中",
                      "旧分类缺 primary_form 时进入补分类，不能默认为 other；明确 unknown 保留无法判断，不冒充完成的形态结论",
                      "玩具只给供儿童玩耍的；装饰摆件、日历、贴纸、成人手工包、普通工具多半没有品类（空列表）",
                      "护肤/彩妆/洗护/美甲/香水等涂抹到身上的产品 → cosmetics；化妆刷、梳子、睫毛夹等美妆工具不是 cosmetics（没有品类）",
                      "宣称治疗/缓解疼痛的外用品 → drug_otc",
                      "削皮器、切果器等厨房工具 → food_contact，不算 knife_blade；knife_blade 只给刀具本身",
                      "电动工具的配件（锯片、磨片、钻头、转接头）不是 power_tool（没有品类）；电动工具本身才是",
                      "flags 只填上面 flags 清单里明确适用的 ID（如装饰灯串、吹风机、延长线），没有就省略",
                      "看不出的特征按该品类最常见的配置填，不留 null：USB 充电/可充电的小电器、个护、玩具 → battery lithium；"
                      "带遥控器 → button；插头供电的家电 → mains true；玩具、童装、儿童餐具 → children true",
                      "按常见配置填了文字里没写的特征时，在 assume 里用一句中文写明假设（如「未写电池类型，按内置锂电判定」），会写进原因列",
                      "武器、偷拍设备、仿警灯、烟花等会导致禁售的品类，只在文字明确说明时才给（如 spy/hidden camera、police/emergency vehicle light）；"
                      "否则按普通品类（消费电子、灯具）判"]})


def cmd_status(a):
    task, state = load_task(a.task)
    out({"ok": True, "task": str(task), **state})


def cmd_doctor(a):
    import platform
    checks, errors, warnings = {}, [], []
    checks["python"] = {"version": platform.python_version(), "executable": sys.executable,
                        "supported": sys.version_info >= (3, 9)}
    checks["platform"] = platform.platform()
    try:
        excel = runtime.require_excel()
        checks["excel"] = {"available": True, "version": excel.__version__}
    except ValueError as exc:
        checks["excel"] = {"available": False, "required": a.require_excel}
        (errors if a.require_excel else warnings).append(str(exc))
    try:
        manifest, count = runtime.verify_manifest(HERE.parent)
        pack = ce.RulePack.load(PACK_PATH)
        if pack.version != manifest.get("rulepack") or pack.digest != manifest.get("rulepack_digest"):
            raise ValueError("规则包版本或摘要与发行清单不一致")
        business = read_json(BUSINESS_PATH)
        if not isinstance(business, dict) or not set(ce.SITES).issubset(business):
            raise ValueError("业务口径表缺少覆盖站点")
        checks["distribution"] = {"valid": True, "files": count, "version": manifest.get("package_version"),
                                  "rulepack": pack.version, "rules": len(pack.rules)}
    except (OSError, ValueError, KeyError, TypeError) as exc:
        checks["distribution"] = {"valid": False}
        errors.append(str(exc) + "；请重新解压完整发行包，不要手工修改规则文件")
    out({"ok": not errors, "checks": checks, "errors": errors, "warnings": warnings,
         "install_args": [sys.executable, "-m", "pip", "install", "-r", str(HERE.parent / "requirements.txt")],
         "note": "doctor 只检查当前环境，不代表已在其他操作系统验证；不自动安装依赖"}, 2 if errors else 0)


def _main():
    ap = argparse.ArgumentParser(description="禁限售合规排查")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("init"); p.add_argument("--input", required=True); p.add_argument("--sites", required=True)
    p.add_argument("--fulfillment", default="unknown", choices=["FBA", "FBM", "unknown"])
    p.add_argument("--task", required=True); p.add_argument("--image", action="append")
    p = sub.add_parser("match"); p.add_argument("--task", required=True); p.add_argument("--profile", required=True)
    p = sub.add_parser("review"); p.add_argument("--task", required=True); p.add_argument("--file", required=True)
    p = sub.add_parser("render"); p.add_argument("--task", required=True)
    p = sub.add_parser("status"); p.add_argument("--task", required=True)
    p = sub.add_parser("quick"); p.add_argument("--input"); p.add_argument("--title"); p.add_argument("--bullet", action="append")
    for k in ("description", "brand", "asin", "url", "notes", "out"):
        p.add_argument("--" + k)
    p.add_argument("--sites", help="默认全部 10 站")
    p.add_argument("--fulfillment", default="unknown", choices=["FBA", "FBM", "unknown"])
    p.add_argument("--limit", type=int, default=8, help="每站最多列出的原因/要求条数（完整内容见报告）")
    p.add_argument("--page", help="商品页内容 JSON：{title, bullets, description}（由网页工具读取）")
    p.add_argument("--fetch", default="auto", choices=["auto", "never"], help="缺少标题或链接站点不明时尝试读取商品页，读取后须语义分类")
    p.add_argument("--category", help='品类与特征 JSON 或文件，含 families、children、battery、wireless、mains、primary_form、form_evidence')
    p = sub.add_parser("table"); p.add_argument("--input", required=True); p.add_argument("--out")
    p.add_argument("--sheet"); p.add_argument("--header-row", type=int); p.add_argument("--site", help="没有链接/站点列时的默认站点")
    for k in ("title", "url", "bullets", "site", "description"):
        p.add_argument(f"--{k}-col")
    p.add_argument("--pages", help="网页工具读取的商品页内容：{行号或链接: {title, bullets, description}}")
    p.add_argument("--fetch", default="auto", choices=["auto", "never"])
    p.add_argument("--max-fetch", type=int, default=50)
    p.add_argument("--categories", help="逐行分类：{行号: {families, children, battery, wireless, mains, primary_form, form_evidence}}")
    sub.add_parser("families")
    p = sub.add_parser("doctor", help="检查运行环境、Excel 依赖及发行文件完整性")
    p.add_argument("--require-excel", action="store_true", help="将 Excel 依赖缺失视为错误；不加则仅警告")
    a = ap.parse_args()
    if a.cmd != "doctor":
        require_auth()
    {"init": cmd_init, "match": cmd_match, "review": cmd_review, "render": cmd_render, "status": cmd_status,
     "quick": cmd_quick, "table": cmd_table, "families": cmd_families, "doctor": cmd_doctor}[a.cmd](a)


def main():
    runtime.configure_stdio()
    try:
        _main()
    except AuthError as exc:
        out({"ok": False, "reason": exc.reason, "error": str(exc)}, 1)
    except PermissionError as exc:
        out({"ok": False, "error": f"文件被占用或目录不可写：{exc.filename or exc}；请关闭 Excel 中的文件，或更换可写输出位置"}, 2)
    except (OSError, ValueError) as exc:
        out({"ok": False, "error": str(exc)}, 2)


if __name__ == "__main__":
    main()
