from __future__ import annotations

import re
import sys
import unittest
from html.parser import HTMLParser
from pathlib import Path
from typing import Optional


SKILL_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = SKILL_ROOT / "scripts"
FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "page_health"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from amazon_page_recovery import (  # noqa: E402
    PageHealthStatus,
    PageSnapshot,
    classify_page_snapshot,
)


class _FixtureParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.in_title = False
        self.title_parts: list[str] = []
        self.body_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs):
        if tag.lower() == "title":
            self.in_title = True

    def handle_endtag(self, tag: str):
        if tag.lower() == "title":
            self.in_title = False

    def handle_data(self, data: str):
        target = self.title_parts if self.in_title else self.body_parts
        target.append(data)


def snapshot_from_fixture(
    name: str,
    *,
    page_kind: str = "product",
    url: str = "https://www.amazon.com/dp/B000000001",
    http_status: Optional[int] = None,
) -> PageSnapshot:
    html = (FIXTURE_DIR / name).read_text(encoding="utf-8")
    parser = _FixtureParser()
    parser.feed(html)
    expected = bool(
        re.search(
            r'id=["\']productTitle["\']|data-component-type=["\']s-search-result["\']',
            html,
            flags=re.I,
        )
    )
    explicit_empty = bool(
        re.search(r'id=["\']noResultsTitle["\']', html, flags=re.I)
    )
    return PageSnapshot(
        page_kind=page_kind,
        url=url,
        title=" ".join(parser.title_parts).strip(),
        body_text=" ".join(parser.body_parts).strip(),
        http_status=http_status,
        expected_content_present=expected,
        explicit_empty=explicit_empty,
    )


class HtmlPageHealthFixtureTests(unittest.TestCase):
    def test_transient_fixtures(self) -> None:
        cases = [
            ("amazon_dog.html", None, "amazon_dog_error"),
            ("http_503.html", 503, "http_503"),
            ("rate_limited.html", 429, "http_429"),
            ("blank.html", None, "blank_page"),
        ]
        for name, status, reason in cases:
            with self.subTest(name=name):
                assessment = classify_page_snapshot(
                    snapshot_from_fixture(name, http_status=status)
                )
                self.assertEqual(
                    assessment.status,
                    PageHealthStatus.TRANSIENT_UNAVAILABLE,
                )
                self.assertEqual(assessment.reason, reason)

    def test_healthy_product_can_contain_sorry(self) -> None:
        assessment = classify_page_snapshot(
            snapshot_from_fixture("healthy_product_with_sorry.html")
        )
        self.assertEqual(assessment.status, PageHealthStatus.HEALTHY)

    def test_only_explicit_empty_is_a_legal_empty_result(self) -> None:
        assessment = classify_page_snapshot(
            snapshot_from_fixture(
                "explicit_no_results.html",
                page_kind="search_category",
                url="https://www.amazon.com/s?k=fixture",
            )
        )
        self.assertEqual(assessment.status, PageHealthStatus.VERIFIED_EMPTY)

    def test_captcha_and_login_do_not_enter_automatic_retry(self) -> None:
        captcha = classify_page_snapshot(
            snapshot_from_fixture(
                "captcha.html",
                url="https://www.amazon.com/errors/validateCaptcha",
            )
        )
        login = classify_page_snapshot(
            snapshot_from_fixture(
                "amazon_login.html",
                url="https://www.amazon.com/ap/signin",
            )
        )
        self.assertEqual(
            captcha.status,
            PageHealthStatus.INTERACTIVE_VERIFICATION,
        )
        self.assertEqual(login.status, PageHealthStatus.AMAZON_SIGN_IN)


if __name__ == "__main__":
    unittest.main()
