"""Optional, local-only Scrapling parsing for already-rendered Amazon cards.

This module never opens a browser or sends a network request.  Browser/CDP
ownership, Amazon navigation, plugin readiness and every provider call stay in
the existing crawler code.  It is intentionally limited to custom field
selectors so its output can be compared with the browser implementation.
"""

from __future__ import annotations

import re
from typing import Dict, List


class ScraplingUnavailable(RuntimeError):
    pass


def scrapling_available() -> bool:
    try:
        import scrapling  # noqa: F401
    except ImportError:
        return False
    return True


def extract_card_fields(card_html: str, selectors: Dict[str, List[str]]) -> Dict[str, str]:
    """Apply existing CSS selectors to one captured card without DOM mutation."""
    if not selectors or not card_html:
        return {}
    try:
        from scrapling import Selector
    except ImportError as exc:  # pragma: no cover - verified by config validation
        raise ScraplingUnavailable("Scrapling 未安装；请先运行 runner install。") from exc

    page = Selector(card_html)
    output: Dict[str, str] = {}
    for field_name, candidates in selectors.items():
        for css in candidates:
            try:
                nodes = page.css(css)
            except Exception:
                # Browser querySelector is still the compatibility fallback for
                # selectors unsupported by Scrapling/lxml.
                continue
            if not nodes:
                continue
            node = nodes[0]
            value = str(
                node.attrib.get("title")
                or node.attrib.get("aria-label")
                or node.get_all_text(separator=" ", strip=True)
                or ""
            )
            value = re.sub(r"\s+", " ", value).strip()
            if value:
                output[field_name] = value
                break
    return output
