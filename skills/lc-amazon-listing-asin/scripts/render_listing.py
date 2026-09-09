#!/usr/bin/env python3
"""Render offline Markdown/HTML from one run's JSON without calling a backend."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import html
import importlib.util
import json
import os
from pathlib import Path
import re
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[1]
FILES = {
    "profile": "01_product_profile.json", "kw_raw": "02_kw_raw.json",
    "kw_removed": "03_kw_removed.json", "kw_filtered": "03_kw_filtered.json",
    "kw_tagged": "04_kw_tagged.json", "title_keywords": "05_title_keywords.json",
    "qa": "06_qa.json", "listing": "07_listing.json", "validation": "08_validation.json",
    "review": "08_semantic_review.json", "backend": "08_backend_validation.json",
    "kw_pending": "03_kw_pending.json", "keyword_decisions": "03_keyword_decisions.json",
}
FIELDS = ("bullets", "description", "search_terms")
LABELS = {
    "title": "Title", "item_highlight": "Item Highlight", "bullets": "Bullet Points",
    "description": "Description", "search_terms": "Search Terms", "claims": "声明引用",
    "applies_to": "适用范围", "buyer_question": "买家问题", "selling_point": "核心卖点",
    "visual_evidence": "画面证据", "scene_intent": "使用场景与意图", "overlay_text": "图中文字",
    "native_text": "原生模块文案",
    "fact_ids": "事实引用", "measurement_ids": "参数引用", "source_image_ids": "素材引用",
    "body_refs": "正文对应位置", "mobile_check": "移动端检查", "production_notes": "制作说明",
    "role": "图片角色", "direction": "画面方向", "correction": "修正说明",
    "sku": "SKU", "variant_id": "子体编号", "attributes": "全部属性",
}


class ReportError(ValueError):
    """Invalid source data; never silently render a success report."""


def reject_constant(value):
    raise ValueError(f"JSON 不支持数值 {value}")


def read_json(path: Path, required: bool = False):
    if not path.exists():
        if required:
            raise ReportError(f"缺少必需文件：{path.name}")
        return None, None
    try:
        raw = path.read_bytes()
        value = json.loads(raw.decode("utf-8-sig"), parse_constant=reject_constant)
    except (OSError, UnicodeError, ValueError) as exc:
        raise ReportError(f"无法读取有效 JSON：{path.name}（{exc}）") from exc
    if not isinstance(value, (dict, list)):
        raise ReportError(f"{path.name} 的根节点必须是对象或数组")
    return value, raw


def script_json(value) -> str:
    """JSON script elements are raw text: escape markup delimiters, not HTML entities."""
    return (json.dumps(value, ensure_ascii=False, allow_nan=False)
            .replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
            .replace("\u2028", "\\u2028").replace("\u2029", "\\u2029"))


def as_text(value) -> str:
    if value is None:
        return "未提供"
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)
    return str(value)


def md_escape(value) -> str:
    text = html.escape(as_text(value), quote=False)
    return re.sub(r"([\\`*_{}\[\]#!|~])", r"\\\1", text)


class Document:
    """Build Markdown and escaped HTML together; user copy is always plain text."""

    def __init__(self, report_view=False):
        self.md = []
        self.html = []
        self.report_view = report_view

    def heading(self, text, level=2, anchor=None):
        self.md.append("#" * level + " " + md_escape(text))
        cls = "listing-title" if level == 2 else "listing-h3"
        identifier = f' id="{html.escape(anchor, quote=True)}"' if anchor else ""
        self.html.append(f'<h{level} class="{cls}"{identifier}>{html.escape(as_text(text))}</h{level}>')

    def value(self, value):
        if self.report_view and isinstance(value, (dict, list)):
            value = readable(value)
        if isinstance(value, (dict, list)):
            serialized = as_text(value)
            fence = "~" * max(3, max((len(m.group()) + 1 for m in re.finditer(r"~+", serialized)), default=3))
            self.md.append(f"{fence}json\n{serialized}\n{fence}")
            self.html.append(f'<pre class="source-json">{html.escape(serialized)}</pre>')
        else:
            self.md.append(md_escape(value))
            if self.report_view:
                self.html.extend("<p>" + html.escape(paragraph).replace("\n", "<br>") + "</p>" for paragraph in as_text(value).split("\n\n") if paragraph.strip())
            else:
                self.html.append("<p>" + html.escape(as_text(value)).replace("\n", "<br>") + "</p>")

    def field(self, key, value, level=3):
        if key == "claims":
            if self.report_view:
                return
            details = Document()
            details.heading(LABELS[key], level)
            details.value(value)
            _, content = details.result()
            self.html.append('<details class="source-details"><summary>声明引用与事实依据</summary>' + content + '</details>')
            return
        self.heading(LABELS.get(key, key), level)
        if key == "bullets" and isinstance(value, list):
            self.md.append("\n".join("- " + md_escape(item).replace("\n", "\n  ") for item in value) or "未提供")
            items = []
            for item in value:
                text = html.escape(as_text(item))
                if self.report_view:
                    text = re.sub(r"【([^】]+)】", r'<strong class="k2">【\1】</strong>', text)
                items.append("<li>" + text.replace("\n", "<br>") + "</li>")
            self.html.append("<ul>" + "".join(items) + "</ul>")
        elif key == "search_terms" and self.report_view and isinstance(value, str):
            self.md.append(md_escape(value))
            self.html.append('<div class="search-terms-list">' + ''.join('<span class="search-term">' + html.escape(word) + '</span>' for word in value.split()) + '</div>')
        else:
            self.value(value)

    def note(self, label, value):
        if value is None or value == "" or value == []:
            return
        text = readable(value)
        self.md.append(md_escape(label + "：" + text))
        self.html.append("<p><strong>" + html.escape(label) + "：</strong>" + html.escape(text).replace("\n", "<br>") + "</p>")

    def details(self, label, value):
        if self.report_view:
            return
        self.html.append('<details class="source-details"><summary>' + html.escape(label) + '</summary><pre class="source-json">' + html.escape(as_text(value)) + '</pre></details>')

    def navigation(self, links, label):
        if self.report_view:
            return
        self.html.append('<nav class="listing-nav" aria-label="' + html.escape(label, quote=True) + '">' + "".join('<a href="#' + html.escape(target, quote=True) + '">' + html.escape(title) + '</a>' for target, title in links) + '</nav>')

    def copy(self, value, parent=False, level=3):
        for field in ("title", "item_highlight") + (() if parent else FIELDS):
            self.field(field, value.get(field), level)
        if "claims" in value:
            self.field("claims", value["claims"], level)

    def result(self):
        return "\n\n".join(self.md) + "\n", "\n".join(self.html)


def ensure_object(value, label):
    if not isinstance(value, dict):
        raise ReportError(f"{label} 必须是对象")
    return value


def ensure_array(value, label):
    if not isinstance(value, list):
        raise ReportError(f"{label} 必须是数组")
    return value


def canonical_fingerprint(value):
    if value is None:
        return None
    canonical = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def effective_status(validation, fingerprints, gaps, evidence_fingerprints=None):
    issues = []
    if validation is None:
        return {"status": "incomplete", "label": "尚未完成验收", "issues": ["缺少 08_validation.json；生成报告不代表验收通过。"] + gaps}
    ensure_object(validation, "08_validation.json")
    recorded = validation.get("fingerprints")
    if not isinstance(recorded, dict) or any(recorded.get(key) != value for key, value in fingerprints.items()) or any(key not in recorded for key in fingerprints):
        issues.append("验收未绑定当前产品画像、Listing 或 QA 文件，或文件已变更；必须重新验收。")
    recorded_evidence = validation.get("evidence_fingerprints")
    if not evidence_fingerprints or any(value is None for value in evidence_fingerprints.values()):
        issues.append("缺少原始语义复审或后端验收记录；不能仅凭汇总声明通过。")
    if not isinstance(recorded_evidence, dict) or recorded_evidence != evidence_fingerprints:
        issues.append("原始语义复审或后端验收记录与汇总不匹配；必须重新验收。")
    declared = validation.get("status")
    stages = [validation.get(key) for key in ("local", "semantic", "backend", "keywords")]
    stage_statuses = [stage.get("status") if isinstance(stage, dict) else stage for stage in stages]
    errors = validation.get("issues", [])
    ensure_array(errors, "08_validation.json.issues")
    has_errors = any(isinstance(issue, dict) and issue.get("severity") == "error" for issue in errors)
    has_incomplete = any(isinstance(issue, dict) and issue.get("severity") == "incomplete" for issue in errors)
    if declared == "failed" or any(value in ("failed", "fail") for value in stage_statuses) or has_errors:
        status = "failed"
    elif declared == "passed" and all(value == "passed" for value in stage_statuses) and not issues and not gaps and not has_incomplete:
        status = "passed"
    else:
        status = "incomplete"
        if declared != "passed" or any(value != "passed" for value in stage_statuses):
            issues.append("本地、筛词、语义复审、后端检查尚未全部通过；不能交付为已通过。")
    issues.extend(gaps)
    for issue in errors:
        if isinstance(issue, dict):
            issues.append(f"{as_text(issue.get('path', ''))}：{as_text(issue.get('message', ''))} [{as_text(issue.get('code', ''))}]")
        else:
            issues.append(as_text(issue))
    return {"status": status, "label": {"passed": "验收通过", "failed": "验收失败", "incomplete": "尚未完成验收"}[status], "issues": issues}


def readable(value):
    """Explain structured values without leaking machine JSON into the copy file."""
    if isinstance(value, list):
        return "；".join(readable(item) for item in value) or "无"
    if isinstance(value, dict):
        return "；".join(str(key) + "：" + readable(item) for key, item in value.items()) or "无"
    return as_text(value)


def a_plus_plans(listing):
    if "a_plus_plan" in listing and "aplus_plan" in listing and listing["a_plus_plan"] != listing["aplus_plan"]:
        raise ReportError("a_plus_plan 与旧字段 aplus_plan 内容冲突")
    return listing.get("a_plus_plan", listing.get("aplus_plan"))


def ordered_variants(profile, listing, gaps):
    supplied = ensure_array(profile.get("variants", []), "profile.variants")
    output = ensure_array(listing.get("variants", []), "listing.variants")
    for item in supplied + output:
        ensure_object(item, "variants[]")
    ordered, consumed = [], set()
    for source in supplied:
        matches = [(i, item) for i, item in enumerate(output) if i not in consumed and item.get("variant_id") == source.get("variant_id")]
        if not matches:
            ordered.append((source, {}))
            gaps.append(f"子体缺少输出：{source.get('variant_id')}")
        for index, item in matches:
            consumed.add(index)
            ordered.append((source, item))
    for index, item in enumerate(output):
        if index not in consumed:
            ordered.append(({}, item))
            gaps.append(f"Listing 包含画像未列出的子体：{item.get('variant_id')}")
    if not ordered:
        gaps.append("系列没有子体。")
    return ordered


def variant_attributes(profile, source, item):
    source_attrs = ensure_object(source.get("attributes", {}), "profile.variants[].attributes")
    attrs = ensure_object(item.get("attributes", {}), "listing.variants[].attributes")
    dimensions = ensure_array(profile.get("variation_dimensions", []), "variation_dimensions")
    labels = []
    for key in dict.fromkeys(dimensions + list(source_attrs) + list(attrs)):
        value = attrs.get(key)
        if value is None and key in source_attrs:
            original = source_attrs[key]
            value = original.get("display", original.get("value")) if isinstance(original, dict) else original
        labels.append(as_text(key) + "：" + readable(value))
    return " · ".join(labels)


def variant_identity(doc, profile, source, item):
    sku = item.get("sku", source.get("sku"))
    if doc.report_view:
        identity = variant_attributes(profile, source, item)
        doc.value(("SKU：" + as_text(sku) + " · " if sku is not None else "") + identity)
        return
    doc.note("SKU", sku if sku is not None else "未提供；使用上述内部编号")
    if "sku" in source and "sku" in item and source["sku"] != item["sku"]:
        doc.note("画像 SKU（与输出不一致）", source["sku"])
    if source.get("asin") is not None:
        doc.note("ASIN", source["asin"])
    doc.note("全部变体属性", variant_attributes(profile, source, item) or "未提供")


def source_catalog(profile):
    catalog = {"fact_ids": {}, "measurement_ids": {}, "source_image_ids": {}}
    for node in [profile] + profile.get("variants", []):
        for collection, reference, identity in (("facts", "fact_ids", "fact_id"), ("measurements", "measurement_ids", "measurement_id"), ("images", "source_image_ids", "image_id")):
            for record in node.get(collection, []):
                if isinstance(record, dict) and record.get(identity):
                    catalog[reference][record[identity]] = record
    return catalog


def explain_references(plan, catalog, key):
    output = []
    for reference in plan.get(key, []):
        record = catalog[key].get(reference)
        if record is None:
            output.append("引用未找到：" + str(reference))
            continue
        if key == "source_image_ids":
            output.append(readable(record.get("source", record.get("path", "素材路径未提供"))))
            continue
        source = record.get("source_ref")
        if key == "measurement_ids":
            value = record.get("display_text")
            if not value:
                value = " ".join(as_text(record.get(field, "")) for field in ("display_value", "display_unit")).strip()
            if not value:
                value = " ".join(as_text(record.get(field, "")) for field in ("value", "unit")).strip()
            label = readable(record.get("label", "规格"))
            output.append(label + "：" + value + ("（来源：" + readable(source) + "）" if source else ""))
        else:
            output.append(readable(record.get("value")) + ("（来源：" + readable(source) + "）" if source else ""))
    return output


def body_locations(value):
    def label(reference):
        reference = str(reference)
        reference = re.sub(r"bullets\[(\d+)\]", lambda match: "五点第" + str(int(match[1]) + 1) + "条", reference)
        return reference.replace("item_highlight", "Item Highlight").replace("description", "长描").replace("search_terms", "搜索词").replace("title", "标题")
    return [label(item) for item in value] if isinstance(value, list) else label(value)


def render_media_details(doc, plan, catalog, mode, include_scope=True):
    if doc.report_view:
        direction = plan.get("direction") or plan.get("visual_evidence")
        selling = plan.get("selling_point")
        sentences = [as_text(direction)] if direction else []
        if selling and as_text(selling) not in as_text(direction or ""):
            sentences.append(as_text(selling))
        if sentences:
            doc.value(" ".join(sentences))
        if plan.get("overlay_text"):
            doc.note("上图文案", plan["overlay_text"])
        if plan.get("native_text"):
            doc.note("模块文案", plan["native_text"])
        if plan.get("status") == "pending" and plan.get("production_notes"):
            doc.note("制作前确认", plan["production_notes"])
        if plan.get("asset_type") == "text":
            doc.value("本模块为纯文字，不计入 A+ 图片数量。")
        return
    if plan.get("status") not in (None, "ready", "complete", "completed"):
        doc.note("策划状态", plan.get("status"))
    if plan.get("asset_type") == "text":
        doc.note("模块形式", "纯文字模块，不计入 A+ 图片数量")
    if include_scope:
        applies = plan.get("applies_to")
        doc.note("适用范围", ("全系列共用" if mode == "family" else "本产品") if applies == ["all"] else applies)
    for key in ("direction", "selling_point", "buyer_question", "visual_evidence", "scene_intent", "overlay_text", "native_text", "correction"):
        doc.note(LABELS.get(key, key), plan.get(key))
    doc.note("事实依据", explain_references(plan, catalog, "fact_ids"))
    doc.note("规格参数", explain_references(plan, catalog, "measurement_ids"))
    doc.note("实物素材", explain_references(plan, catalog, "source_image_ids"))
    if plan.get("body_refs"):
        doc.note("正文对应位置", body_locations(plan["body_refs"]))
    for key in ("mobile_check", "production_notes"):
        doc.note(LABELS[key], plan.get(key))
    doc.details("事实引用与制作校验明细", {key: value for key, value in plan.items() if key not in ("variant_bindings",)})


def binding_for(plan, variant_id):
    bindings = ensure_array(plan.get("variant_bindings", []), "variant_bindings")
    matches = [binding for binding in bindings if ensure_object(binding, "variant_bindings[]").get("variant_id") == variant_id]
    if len(matches) > 1:
        raise ReportError(f"图片 {plan.get('plan_id')} 对子体 {variant_id} 存在重复绑定")
    return matches[0] if matches else None


def render_binding(doc, plan, variant_id, catalog):
    binding = binding_for(plan, variant_id)
    if doc.report_view:
        if not binding:
            doc.value("缺少该子体的参数与素材绑定，尚不能制作。" if plan.get("variant_bindings") else "沿用共用创意及其文案。")
            return
        for key, label in (("overlay_text", "本款上图文案"), ("native_text", "本款模块文案")):
            if binding.get(key):
                doc.note(label, binding[key])
        if binding.get("direction"):
            doc.value(binding["direction"])
        if binding.get("status") == "pending" and binding.get("production_notes"):
            doc.note("制作前确认", binding["production_notes"])
        return
    if not binding:
        explanation = "缺少该子体的参数与素材绑定，尚不能制作。" if plan.get("variant_bindings") else "无专属参数替换；沿用本图已列出的全系列事实与素材。"
        doc.note("替换说明", explanation)
        return
    if binding.get("status") not in (None, "ready", "complete", "completed"):
        doc.note("该子体策划状态", binding["status"])
    doc.note("替换画面", binding.get("direction"))
    doc.note("替换后的上图文案", binding.get("overlay_text", plan.get("overlay_text")))
    doc.note("替换后的原生模块文案", binding.get("native_text", plan.get("native_text")))
    for key, label in (("fact_ids", "该子体事实"), ("measurement_ids", "该子体规格"), ("source_image_ids", "该子体实物素材")):
        effective = {key: binding.get(key, plan.get(key, []))}
        doc.note(label, explain_references(effective, catalog, key))
    doc.note("画面证据", binding.get("visual_evidence"))
    if binding.get("body_refs"):
        doc.note("该子体正文位置", body_locations(binding["body_refs"]))
    doc.note("该子体制作说明", binding.get("production_notes"))
    doc.details("子体绑定与事实引用", binding)


def media_label(plan, fallback, aplus=False):
    keys = ("module", "image") if aplus or plan.get("role") == "aplus" else ("image", "module")
    return next((plan[key] for key in keys if plan.get(key)), plan.get("plan_id", fallback))


def render_media(doc, profile, listing, ordered, gaps):
    mode = listing.get("listing_mode", profile.get("listing_mode", "single"))
    catalog = source_catalog(profile)
    images = listing.get("image_plan")
    a_plus = a_plus_plans(listing)
    sets = listing.get("image_sets")
    if sets is None:
        gaps.append("旧版图片策划未按新版套数、数量与复用规则核验；兼容展示不代表新版验收通过。")
        for plans, heading in ((images, "附图策划"), (a_plus, "A+ 整体策划")):
            doc.heading(heading, anchor="image-plans" if heading == "附图策划" else "a-plus-plans")
            if not isinstance(plans, list):
                doc.value(readable(plans))
                continue
            for number, plan in enumerate(plans, 1):
                if not isinstance(plan, dict):
                    doc.value(readable(plan))
                    continue
                label = media_label(plan, f"方案 {number}", aplus=heading == "A+ 整体策划")
                doc.heading(label, 3)
                render_media_details(doc, plan, catalog, mode)
                for binding in plan.get("variant_bindings", []):
                    doc.heading("子体参数替换 · " + as_text(binding.get("variant_id")), 4)
                    render_binding(doc, plan, binding.get("variant_id"), catalog)
        return
    ensure_object(sets, "image_sets")
    shared = ensure_object(sets.get("shared", {}), "image_sets.shared")
    group_variants = ensure_array(sets.get("variants", []), "image_sets.variants")
    catalog_plans = {}
    for key, plans in (("image_plan", images), ("a_plus_plan", a_plus)):
        for plan in ensure_array(plans, key):
            ensure_object(plan, key + "[]")
            identifier = plan.get("plan_id")
            if not isinstance(identifier, str) or not identifier:
                raise ReportError(key + "[] 缺少 plan_id")
            if identifier in catalog_plans:
                raise ReportError("重复图片编号：" + identifier)
            catalog_plans[identifier] = plan
    used = set()

    def referenced(identifier):
        if not isinstance(identifier, str) or identifier not in catalog_plans:
            gaps.append("图片方案引用不存在：" + as_text(identifier))
            doc.note("缺少图片策划", identifier)
            return None
        used.add(identifier)
        return catalog_plans[identifier]

    def full_image(identifier, label, level, anchor=None, show_bindings=False):
        plan = referenced(identifier)
        doc.heading(media_label(plan, label) if plan else label, level, anchor=anchor)
        if plan:
            render_media_details(doc, plan, catalog, mode)
            if show_bindings:
                for number, (source, item) in enumerate(ordered, 1):
                    variant_id = item.get("variant_id", source.get("variant_id"))
                    if binding_for(plan, variant_id):
                        doc.heading(f"子体替换 {number:02d} · {variant_id}", min(level + 1, 6))
                        variant_identity(doc, profile, source, item)
                        render_binding(doc, plan, variant_id, catalog)
        return plan

    def secondary_ids(group):
        return ensure_array(group.get("secondary", []), "image_sets.secondary")

    a_plus_ids = ensure_array(shared.get("a_plus", []), "image_sets.shared.a_plus")
    doc.heading("附图策划", anchor="image-plans")
    if mode == "family":
        doc.navigation([("shared-images", "全系列共用方案")] + [(f"variant-images-{index}", "子体 " + as_text(item.get("variant_id", source.get("variant_id")))) for index, (source, item) in enumerate(ordered, 1)], "图片方案导航")
        doc.heading("方案 A｜全系列共用", 3, anchor="shared-images")
        doc.note("主图使用方式", "统一构图模板；实际主图按当前子体展示真实外观、数量和配件。")
    level = 4 if mode == "family" else 3
    full_image(shared.get("main"), "图1（主图）", level, show_bindings=mode == "family")
    for index, identifier in enumerate(secondary_ids(shared), 2):
        full_image(identifier, f"图{index}（附图）", level, show_bindings=listing.get("media_strategy") != "shared_secondary")

    group_by_variant = {}
    for group in group_variants:
        ensure_object(group, "image_sets.variants[]")
        identifier = group.get("variant_id")
        if identifier in group_by_variant:
            raise ReportError("重复子体图片方案：" + as_text(identifier))
        group_by_variant[identifier] = group
    expected = {item.get("variant_id", source.get("variant_id")) for source, item in ordered}
    if set(group_by_variant) - expected:
        gaps.append("图片方案包含未提供子体：" + readable(sorted(set(group_by_variant) - expected, key=str)))
    for index, (source, item) in enumerate(ordered, 1):
        identifier = item.get("variant_id", source.get("variant_id"))
        doc.heading(f"方案 B｜子体 {index:02d} · {identifier}", 3, anchor=f"variant-images-{index}")
        variant_identity(doc, profile, source, item)
        group = group_by_variant.get(identifier)
        if group is None:
            gaps.append("子体缺少图片方案：" + as_text(identifier))
            doc.note("图片策划", "缺少该子体方案")
            continue
        main = full_image(group.get("main"), "图1（主图）", 4)
        if main and binding_for(main, identifier):
            render_binding(doc, main, identifier, catalog)
        for number, plan_id in enumerate(secondary_ids(group), 2):
            if plan_id in secondary_ids(shared):
                plan = referenced(plan_id)
                doc.heading(f"图{number}（复用共用附图）", 4)
                if plan:
                    doc.note("共用创意", plan.get("image", f"图{number}") + "；构图与购买理由见方案 A，以下为本子体替换信息。")
                    doc.details("复用关系", {"variant_id": identifier, "plan_id": plan_id})
                    render_binding(doc, plan, identifier, catalog)
            else:
                full_image(plan_id, f"图{number}（附图）", 4)
        doc.note("A+ 使用方式", "引用下方全系列共用 A+，本子体不另建 A+ 方案。")

    doc.heading("A+ 整体策划", anchor="a-plus-plans")
    if mode == "family":
        doc.note("适用范围", "全系列共用；有参数或素材差异的模块按下方对应子体替换。")
    for number, identifier in enumerate(a_plus_ids, 1):
        plan = full_image(identifier, f"模块{number}", 3)
        if plan:
            for index, (source, item) in enumerate(ordered, 1):
                variant_id = item.get("variant_id", source.get("variant_id"))
                if binding_for(plan, variant_id):
                    doc.heading(f"子体替换 {index:02d} · {variant_id}", 4)
                    variant_identity(doc, profile, source, item)
                    render_binding(doc, plan, variant_id, catalog)
    # Unassigned plans must remain visible and prevent a misleading complete report.
    for identifier, plan in catalog_plans.items():
        if identifier not in used:
            gaps.append("图片创意未分配到任何方案：" + identifier)
            doc.heading("未分配创意 · " + identifier, 3)
            render_media_details(doc, plan, catalog, mode)


def render_coverage(doc, listing):
    coverage = listing.get("buyer_question_coverage", [])
    doc.heading("买家问题覆盖清单")
    if not isinstance(coverage, list):
        doc.value(readable(coverage))
        return
    if not coverage:
        doc.value("未提供买家问题覆盖记录。")
        return
    lines, texts = [], []
    for number, item in enumerate(coverage, 1):
        if isinstance(item, dict):
            question = readable(item.get("question", "未提供问题"))
            location = readable(item.get("location", item.get("answer", item.get("status", "未提供覆盖位置"))))
            text = question + " → " + location
        else:
            text = readable(item)
        lines.append(f"{number}. " + md_escape(text))
        texts.append(text)
    doc.md.append("\n".join(lines))
    if doc.report_view:
        doc.html.extend(f'<p>{number}. {html.escape(text)}</p>' for number, text in enumerate(texts, 1))
    else:
        doc.html.append('<ol class="coverage-list">' + "".join("<li>" + html.escape(text) + "</li>" for text in texts) + "</ol>")


def render_listing(profile, listing, report_view=False):
    doc, gaps = Document(report_view=report_view), []
    mode = listing.get("listing_mode", profile.get("listing_mode", "single"))
    if mode not in ("single", "family"):
        raise ReportError(f"不支持的 listing_mode：{mode}")
    ordered = []
    if mode == "single":
        doc.copy(listing, level=2)
    else:
        parent = ensure_object(listing.get("parent", {}), "listing.parent")
        shared = ensure_object(listing.get("shared_content", {}), "listing.shared_content")
        ordered = ordered_variants(profile, listing, gaps)
        doc.navigation([("parent-copy", "父体")] + [(f"variant-copy-{number}", "子体 " + as_text(item.get("variant_id", source.get("variant_id")))) for number, (source, item) in enumerate(ordered, 1)] + [("shared-copy", "共用正文"), ("image-plans", "主附图方案"), ("a-plus-plans", "A+ 方案")], "父子体与文案导航")
        doc.heading("父体", anchor="parent-copy")
        doc.note("SKU", parent.get("sku", profile.get("parent_sku")))
        doc.copy(parent, parent=True)
        doc.details("共同标题结构", listing.get("title_template"))
        for number, (source, item) in enumerate(ordered, 1):
            variant_id = item.get("variant_id", source.get("variant_id"))
            doc.heading(f"子体 {number:02d} · {as_text(variant_id)}", anchor=f"variant-copy-{number}")
            variant_identity(doc, profile, source, item)
            for key in ("title", "item_highlight"):
                doc.field(key, item.get(key))
            if "claims" in item:
                doc.field("claims", item["claims"])
        doc.heading("系列共用正文", anchor="shared-copy")
        for key in FIELDS:
            doc.field(key, shared.get(key))
        for number, (source, item) in enumerate(ordered, 1):
            overrides = ensure_object(item.get("content_overrides", {}), "content_overrides")
            if not overrides:
                continue
            variant_id = item.get("variant_id", source.get("variant_id"))
            doc.heading(f"子体差异正文 {number:02d} · {as_text(variant_id)}")
            variant_identity(doc, profile, source, item)
            for key in FIELDS:
                if key in overrides:
                    doc.field(key, overrides[key])
    render_media(doc, profile, listing, ordered, gaps)
    render_coverage(doc, listing)
    for key in ("excluded_claims", "claim_controls"):
        if key in listing:
            doc.details("未采用宣称与边界", listing[key])
    return doc, gaps


def current_local_issues(profile, listing, qa):
    """Recheck current rules, including when imported outside scripts/ by tests."""
    spec = importlib.util.spec_from_file_location("listing_report_quality", ROOT / "scripts/listing_quality.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.check_local(profile, listing, qa)


def current_keyword_stage(run_dir):
    spec = importlib.util.spec_from_file_location("listing_report_keywords", ROOT / "scripts/keyword_quality.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.check_run(run_dir)


def build_report(run_dir: Path, generated_at=None):
    data, snapshots = {}, {}
    for key, filename in FILES.items():
        data[key], snapshots[filename] = read_json(run_dir / filename, required=key in ("profile", "listing"))
    profile, listing = ensure_object(data["profile"], FILES["profile"]), ensure_object(data["listing"], FILES["listing"])
    for key in ("kw_removed", "kw_filtered", "kw_tagged", "kw_pending"):
        if data[key] is not None:
            ensure_array(data[key], FILES[key])
    for key in ("kw_raw", "title_keywords", "review", "backend"):
        if data[key] is not None:
            ensure_object(data[key], FILES[key])
    doc, gaps = render_listing(profile, listing)
    fingerprints = {f"{key}_sha256": hashlib.sha256(snapshots[FILES[key]]).hexdigest() if snapshots[FILES[key]] is not None else None for key in ("profile", "listing", "qa")}
    evidence_fingerprints = {f"{key}_sha256": canonical_fingerprint(data[key]) for key in ("review", "backend")}
    keywords = current_keyword_stage(run_dir)
    evidence_fingerprints["keywords_sha256"] = canonical_fingerprint(keywords)
    validation = effective_status(data["validation"], fingerprints, gaps, evidence_fingerprints)
    validation["current_keywords"] = keywords
    if keywords["status"] != "passed":
        if validation["status"] != "failed":
            validation["status"] = keywords["status"]
        validation["label"] = {"failed": "验收失败", "incomplete": "尚未完成验收"}[validation["status"]]
        validation["issues"].append("筛词审查尚未通过；历史词表或报告生成不代表审查完成。")
    local_issues = current_local_issues(profile, listing, data["qa"])
    current_status = "failed" if any(issue.get("severity") == "error" for issue in local_issues) else "incomplete" if any(issue.get("severity") == "incomplete" for issue in local_issues) else "passed"
    validation["current_local"] = {"status": current_status, "issues": local_issues}
    if current_status != "passed":
        legacy = any(issue.get("code") == "legacy_schema" for issue in local_issues)
        if validation["status"] != "failed":
            validation["status"] = "incomplete" if legacy else current_status
        validation["label"] = {"passed": "验收通过", "failed": "验收失败", "incomplete": "尚未完成验收"}[validation["status"]]
        validation["issues"].append("按当前规则重新检查尚未通过；详见当前本地校验，历史汇总不能代替本次检查。")
    stamp = generated_at or datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
    listing_md, _ = doc.result()
    report_doc, _ = render_listing(profile, listing, report_view=True)
    _, listing_html = report_doc.result()
    metadata = {"generated_at": stamp, "missing_files": [name for name, raw in snapshots.items() if raw is None], "fingerprints": fingerprints, "evidence_fingerprints": evidence_fingerprints}
    replacements = {"__DATA_" + key.upper() + "__": script_json(data[key]) for key in ("profile", "kw_raw", "kw_removed", "kw_filtered", "kw_tagged", "title_keywords", "qa", "kw_pending")}
    replacements.update({"__DATA_META__": script_json(metadata), "__DATA_LISTING__": script_json(listing),
                         "__DATA_VALIDATION__": script_json(validation),
                         "__DATA_EVIDENCE__": script_json({key: data[key] for key in ("validation", "review", "backend", "keyword_decisions")}),
                         "__DATA_KEYWORD_AUDIT__": script_json(keywords),
                         "__LISTING_HTML__": listing_html, "__VALIDATION_LABEL__": html.escape(validation["label"]),
                         "__VALIDATION_STATUS__": validation["status"]})
    template = (ROOT / "tools/listing_report_template.html").read_text(encoding="utf-8")
    tokens = set(re.findall(r"__[A-Z][A-Z0-9_]*__", template))
    missing = tokens - replacements.keys()
    if missing:
        raise ReportError("报告模板存在未知占位符：" + ", ".join(sorted(missing)))
    rendered = re.sub(r"__[A-Z][A-Z0-9_]*__", lambda match: replacements[match.group()], template)
    # Do not associate outputs with data that changed while the report was built.
    for filename, raw in snapshots.items():
        path = run_dir / filename
        if (path.read_bytes() if path.exists() else None) != raw:
            raise ReportError(f"生成期间文件已变化：{filename}；请重新生成")
    return listing_md, rendered, validation["status"]


def write_outputs(run_dir, markdown, report):
    temporary = []
    try:
        for name, content in (("07_listing.md", markdown), ("report.html", report)):
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=run_dir, prefix=".listing-report-", delete=False) as handle:
                handle.write(content)
                temporary.append((Path(handle.name), run_dir / name))
        for source, destination in temporary:
            os.replace(source, destination)
    finally:
        for source, _ in temporary:
            source.unlink(missing_ok=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        markdown, report, status = build_report(args.run_dir)
        write_outputs(args.run_dir, markdown, report)
    except (ReportError, OSError) as exc:
        print(f"报告生成失败：{exc}", file=sys.stderr)
        return 1
    except (TypeError, AttributeError, KeyError) as exc:
        print(f"报告生成失败：嵌套数据结构不符合要求（{exc}）；请检查对象、数组及编号字段。", file=sys.stderr)
        return 1
    print(json.dumps({"rendered": True, "validation_status": status, "files": ["07_listing.md", "07_listing.json", "report.html"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
