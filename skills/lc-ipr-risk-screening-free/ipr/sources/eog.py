"""美国专利局每周公报（Official Gazette）的网页版：近 52 周授权的每件专利各有一页，外观那一页带一张代表图。
它是静态网页，和"按页取图"的接口是两套东西（那个接口没有公开文档、换过地址，取不到时用这里的图顶上）；图的地址能由专利号和授权日直接算出来（2026-11-26 实测）。
只留最近 52 周：再早的那一周的目录已经被今年同一周的公报盖掉了。"""
from __future__ import annotations

import re
from datetime import date

from .. import numbers

BASE = "https://www.uspto.gov/web/patents/patog"
ANCHOR = (2026, 10, 1551)  # 2026 年 10 月是第 1551 卷，每个月加一卷（实测 2026-10-06 那一期在 1551-1）
KEEP_DAYS = 51 * 7         # 网页版留 52 周，留一周余量


def image_url(number: str, grant_date: str, today: date = None) -> str:
    """这件外观在公报里的代表图地址；不在最近 52 周内、号码或日期不对的返回空字符串。"""
    granted = numbers.parse_date(grant_date)
    found = re.fullmatch(r"US(D\d{6,7})(?:S\d?)?", str(number or "").upper())
    today = today or date.today()
    if not granted or not found or not 0 <= (today - granted).days <= KEEP_DAYS:
        return ""
    year, month, volume = ANCHOR
    volume += (granted.year - year) * 12 + (granted.month - month)
    issue = (granted.day - 1) // 7 + 1                     # 这个月的第几个周二（专利都在周二授权）
    week = (granted.timetuple().tm_yday - 1) // 7 + 1      # 这一年的第几个周二
    return "%s/week%02d/OG/html/%d-%d/US%s-%s-D00000.gif" % (BASE, week, volume, issue, found.group(1), granted.strftime("%Y%m%d"))
