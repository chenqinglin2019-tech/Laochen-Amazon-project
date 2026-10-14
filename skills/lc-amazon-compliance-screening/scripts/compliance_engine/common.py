"""Shared constants and helpers. Python 3.9+, standard library only."""
from __future__ import annotations

import hashlib
import json
import re
import unicodedata

SITES = ("US", "JP", "UK", "DE", "FR", "IT", "ES", "AE", "SA", "AU")
SITE_ZH = {"US": "美国站", "JP": "日本站", "UK": "英国站", "DE": "德国站", "FR": "法国站", "IT": "意大利站",
           "ES": "西班牙站", "AE": "阿联酋站", "SA": "沙特站", "AU": "澳大利亚站"}
SEVERITY_RANK = {"info": 1, "compliance_required": 2, "approval_required": 3, "prohibited": 4}
VERDICTS = ("prohibited", "approval_required", "compliance_required", "no_specific_restriction", "needs_info")
VERDICT_RANK = {"no_specific_restriction": 1, "compliance_required": 2, "approval_required": 3, "prohibited": 4,
                "needs_info": 0}
VERDICT_ZH = {"prohibited": "禁售", "approval_required": "需审核/许可", "compliance_required": "需合规资料",
              "no_specific_restriction": "未发现特殊限制", "needs_info": "信息不足"}
QUICK_VERDICT_ZH = {"prohibited": "疑似禁售", "approval_required": "疑似需审核", "compliance_required": "需合规资料",
                    "no_specific_restriction": "初筛未见限制", "needs_info": "信息不足"}
DECISION_ZH = {"prohibited": "禁售：不能在该站上架",
               "approval_required": "需先申请审核或许可",
               "compliance_required": "可售，上架前需备齐认证、注册或文件",
               "no_specific_restriction": "本规则库范围内未发现特殊限制",
               "needs_info": "结论不完整：需补信息"}
FBA_ZH = {"fba_prohibited": "FBA 禁运", "fba_dg_review": "需危险品审核", "fba_ok": "未发现 FBA 限制",
          "unknown": "FBA 情况未知"}
CONFIDENCES = ("low", "medium", "high")
CONFIDENCE_ZH = {"low": "低", "medium": "中", "high": "高"}
LAYER_ZH = {"L1": "平台禁售", "L2": "平台限售/审核", "L3": "平台合规资料", "L4": "FBA/危险品",
            "L5": "当地法规", "L6": "进口/清关"}
KIND_ZH = {"certification": "认证", "test_report": "测试报告", "registration": "注册/备案", "labeling": "标签",
           "documentation": "文件", "amazon_approval": "亚马逊审核", "local_representative": "本地责任人",
           "license": "许可证", "prohibition": "禁止"}
# Attributes that drive dangerous-goods classification; unknown values make the FBA dimension unknown.
DG_ATTRS = ("battery.included", "substance.liquid", "substance.aerosol", "substance.flammable",
            "substance.corrosive", "magnets.type")
# Every formal profile must state these (any status), so attribute-only rules don't fire on unrelated products.
CORE_ATTRS = ("power.source", "battery.included", "radio.technologies", "connectivity.internet", "laser.present",
              "user.primarily_children", "user.infants_under_3", "material.food_contact",
              "material.skin_contact_prolonged", "substance.liquid", "substance.aerosol", "substance.flammable",
              "substance.chemical_mixture", "blade.present", "heating.element", "magnets.type",
              "product.is_medical_use", "product.condition", "origin.country", "substance.primary_form")


def canonical(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def digest(obj) -> str:
    return hashlib.sha256(canonical(obj).encode("utf-8")).hexdigest()


def norm_text(text) -> str:
    return unicodedata.normalize("NFKC", str(text or "")).casefold()


_NON_LATIN = re.compile(r"[؀-ۿ぀-ヿ㐀-鿿가-힯]")


class KeywordMatcher:
    """Whole-word match for Latin keywords, substring match for CJK/Arabic. Exclusion phrases (e.g. "wine glass"
    for alcohol) are removed from the text before matching."""

    def __init__(self, keywords, excludes=()):
        self.excludes = sorted({norm_text(x).strip() for x in excludes if str(x).strip()}, key=len, reverse=True)
        self.items = []
        for kw in keywords:
            k = norm_text(kw).strip()
            if not k:
                continue
            self.items.append((kw, k, not _NON_LATIN.search(k)))

    def find(self, text_norm: str):
        for phrase in self.excludes:
            text_norm = text_norm.replace(phrase, " ")
        hits = []
        for original, k, whole_word in self.items:
            if (_find_word(text_norm, k) if whole_word else k in text_norm):
                hits.append(original)
        return hits


def _latin(ch: str) -> bool:
    return ("0" <= ch <= "9") or ("a" <= ch <= "z") or ("\u00c0" <= ch <= "\u024f")


def _find_word(text: str, k: str) -> bool:
    """k occurs with no Latin letter/digit directly before or after it (Japanese/Chinese neighbours are fine)."""
    i = text.find(k)
    while i != -1:
        j = i + len(k)
        if (i == 0 or not _latin(text[i - 1])) and (j == len(text) or not _latin(text[j])):
            return True
        i = text.find(k, i + 1)
    return False


def flatten_keywords(spec) -> list:
    """{lang: [words]} -> [words]."""
    out = []
    if isinstance(spec, dict):
        for lang, words in spec.items():
            if lang == "not":
                continue
            out.extend(w for w in (words or []) if isinstance(w, str))
    elif isinstance(spec, list):
        out.extend(w for w in spec if isinstance(w, str))
    return out


def excludes_of(spec) -> list:
    return [w for w in ((spec or {}).get("not") or []) if isinstance(w, str)] if isinstance(spec, dict) else []


def bad_text(value: str) -> bool:
    return "????" in value or "�" in value
