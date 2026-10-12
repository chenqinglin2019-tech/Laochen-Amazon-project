from __future__ import annotations

import re
import unittest
from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parents[1]

DEFAULT_ENTRYPOINTS = (
    SKILL_ROOT / "SKILL.md",
    SKILL_ROOT / "AGENTS.md",
    SKILL_ROOT / "INSTRUCTIONS.md",
)

CANONICAL_REFERENCES = (
    "references/consumer_voice_workflow.md",
    "references/consumer_voice_contract.md",
    "scripts/consumer_voice_local_reprocess.py",
    "scripts/consumer_all_history_report.py",
)

SEMANTIC_CODES = (
    "purchase_selection_recommendation",
    "failure_complaint_return_alternative",
    "satisfaction_recommendation_repurchase",
    "installation_compatibility_scenario",
    "diy_modification_workaround",
    "feature_reverse_innovation",
)

LEGACY_DEFAULT_PATTERNS = {
    "未指定时默认 quick": re.compile(
        r"(?:未指定|默认|直接|自动).{0,50}(?:`?quick`?|快速验证)"
        r"|(?:`?quick`?|快速验证).{0,50}(?:默认|未指定)",
        re.IGNORECASE | re.DOTALL,
    ),
    "30/90 天固定主路径": re.compile(
        r"全品类.{0,60}(?:完整|最近|严格使用|只使用)?\s*30\s*天"
        r".{0,120}(?:Top\s*3|Top1|三个细分|细分)"
        r".{0,60}(?:完整|最近|严格使用|只使用|各自)?\s*90\s*天",
        re.IGNORECASE | re.DOTALL,
    ),
    "旧窗口 scope": re.compile(
        r"\b(?:category_30d|segment_[123]_90d|recent_30d|union_mixed_window"
        r"|N_category_30d|N_segment_[123]_90d)\b",
        re.IGNORECASE,
    ),
    "默认研究档位参数": re.compile(r"--research-level\b", re.IGNORECASE),
}


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _is_explicit_collection_heading(heading: str) -> bool:
    """Return true only for a section explicitly marked as non-default collection."""
    normalized = re.sub(r"\s+", "", heading).casefold()
    collection = any(token in normalized for token in ("联网", "重新抓取", "补采", "采集"))
    opt_in = any(
        token in normalized
        for token in ("显式", "仅当", "非默认", "可选", "旧版", "兼容", "legacy")
    )
    return collection and opt_in


def _default_route_text(markdown: str) -> str:
    """Remove explicitly labelled legacy/recollection sections from route linting.

    The old online collector may remain as an opt-in compatibility path, but a
    heading must say so explicitly.  Descendant headings inherit that status.
    """
    lines = markdown.splitlines()
    heading_stack: list[tuple[int, bool]] = []
    kept: list[str] = []
    in_fenced_code = False

    for line in lines:
        if line.lstrip().startswith("```"):
            in_fenced_code = not in_fenced_code
            if not any(flag for _, flag in heading_stack):
                kept.append(line)
            continue

        match = None if in_fenced_code else re.match(r"^(#{1,6})\s+(.+?)\s*$", line)
        if match:
            level = len(match.group(1))
            while heading_stack and heading_stack[-1][0] >= level:
                heading_stack.pop()
            inherited = any(flag for _, flag in heading_stack)
            explicit = inherited or _is_explicit_collection_heading(match.group(2))
            heading_stack.append((level, explicit))

        if not any(flag for _, flag in heading_stack):
            kept.append(line)

    return "\n".join(kept)


def _assert_canonical_language(test: unittest.TestCase, path: Path, text: str) -> None:
    checks = (
        ("全历史" in text, "未声明全历史消费者声音口径"),
        ("六类语义" in text, "未声明六类语义"),
        (
            re.search(
                r"(?:任一命中|至少命中一类|命中.{0,8}至少一类"
                r"|六类语义.{0,8}至少一类|\bOR\b)",
                text,
                re.IGNORECASE,
            )
            is not None,
            "未声明六类语义使用 OR 规则",
        ),
        (
            re.search(
                r"(?:无|不设|不使用|不按|取消|不做).{0,18}(?:时间窗|时间筛选|日期筛选)"
                r"|日期.{0,12}(?:不参与|不作为).{0,12}(?:筛选|纳入|排除)"
                r"|(?:日期|发布时间|发布日期).{0,18}(?:不作筛选|只作描述|只作追溯)",
                text,
                re.DOTALL,
            )
            is not None,
            "未声明日期不参与筛选",
        ),
        (
            re.search(
                r"(?:无|不输出|不包含|不得包含|取消|不再建立|不再区分|不使用)"
                r".{0,18}置信度",
                text,
                re.DOTALL,
            )
            is not None,
            "未声明不输出置信度",
        ),
    )
    for passed, message in checks:
        if not passed:
            test.fail(f"{path.name} {message}")


class CanonicalConsumerVoiceDocsTests(unittest.TestCase):
    def test_default_entrypoints_route_to_all_history_contract_and_scripts(self) -> None:
        for path in DEFAULT_ENTRYPOINTS:
            with self.subTest(path=path.name):
                text = _default_route_text(_read(path))
                for reference in CANONICAL_REFERENCES:
                    if reference not in text:
                        self.fail(f"{path.name} 默认流程缺少 {reference}")
                _assert_canonical_language(self, path, text)

    def test_default_entrypoints_do_not_expose_quick_or_fixed_windows(self) -> None:
        for path in DEFAULT_ENTRYPOINTS:
            with self.subTest(path=path.name):
                text = _default_route_text(_read(path))
                for label, pattern in LEGACY_DEFAULT_PATTERNS.items():
                    match = pattern.search(text)
                    self.assertIsNone(
                        match,
                        f"{path.name} 默认消费者声音流程仍包含{label}: "
                        f"{match.group(0)[:180] if match else ''}",
                    )

    def test_workflow_and_contract_define_canonical_six_semantic_or_rule(self) -> None:
        for relative in (
            "references/consumer_voice_workflow.md",
            "references/consumer_voice_contract.md",
        ):
            path = SKILL_ROOT / relative
            with self.subTest(path=relative):
                text = _default_route_text(_read(path))
                _assert_canonical_language(self, path, text)
                for semantic_code in SEMANTIC_CODES:
                    if semantic_code not in text:
                        self.fail(f"{relative} 缺少语义类别：{semantic_code}")
                for legacy_label, pattern in LEGACY_DEFAULT_PATTERNS.items():
                    match = pattern.search(text)
                    self.assertIsNone(
                        match,
                        f"{relative} 默认契约仍包含{legacy_label}: "
                        f"{match.group(0)[:180] if match else ''}",
                    )

    def test_canonical_files_exist(self) -> None:
        for relative in CANONICAL_REFERENCES:
            with self.subTest(path=relative):
                self.assertTrue((SKILL_ROOT / relative).is_file(), relative)
        for relative in (
            "references/social_voice_all_history_coding.schema.json",
            "references/social_voice_all_history_analysis.schema.json",
            "assets/consumer_all_history_report.template.html",
        ):
            with self.subTest(path=relative):
                self.assertTrue((SKILL_ROOT / relative).is_file(), relative)

    def test_taxonomy_contract_and_dashboard_gate_match_the_cli(self) -> None:
        contract = _read(SKILL_ROOT / "references/consumer_voice_contract.md")
        for field in (
            "profile_id",
            "product_label",
            "product_terms",
            "implicit_product_terms",
            "semantic_extensions",
            "topics[]",
            "segments[]",
            "kano_mapping",
        ):
            self.assertIn(field, contract)
        self.assertNotIn("product_category.direct_terms", contract)
        for relative in (
            "SKILL.md",
            "INSTRUCTIONS.md",
            "references/consumer_voice_workflow.md",
        ):
            text = _read(SKILL_ROOT / relative)
            with self.subTest(path=relative):
                self.assertIn("--dashboard", text)


if __name__ == "__main__":
    unittest.main()
