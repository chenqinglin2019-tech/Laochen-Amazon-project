"""专利号的统一写法、保护期的推算。不同来源对同一件专利写法不同（D1035381、USD1035381S、USD1035381S1），要并成一件。"""
from __future__ import annotations

import re
from datetime import date

DESIGN_TERM_CHANGE = date(2015, 5, 13)  # 这一天及以后申请的美国外观保护 15 年，之前的 14 年


def us_key(number: str) -> str:
    """美国专利或外观的比对键：外观 D 加数字，发明只留数字。认不出返回空字符串。"""
    text = re.sub(r"[^A-Za-z0-9]", "", str(number or "")).upper()
    if text.startswith("US"):
        text = text[2:]
    match = re.fullmatch(r"(D)0*(\d{5,7})(S\d?)?", text) or re.fullmatch(r"()0*(\d{6,8})(B\d|A|E\d?)?", text)
    if not match:
        return ""
    return (match.group(1) or "") + match.group(2)


def us_display(number: str, kind: str = "") -> str:
    """统一成 Google Patents 的写法：USD1035381S1、US10633217B2。"""
    key = us_key(number)
    if not key:
        return str(number or "")
    if key.startswith("D"):
        return "US%sS1" % key
    kind = (kind or "").upper()
    if not re.fullmatch(r"[BE]\d", kind):  # 没给类别码：用原号里带的；原号里也没有才默认 B2
        own = re.search(r"([BE]\d)$", re.sub(r"[^A-Za-z0-9]", "", str(number or "")).upper())
        kind = own.group(1) if own else "B2"
    return "US%s%s" % (key, kind)


def parse_date(text: str):
    match = re.match(r"(\d{4})-?(\d{2})-?(\d{2})", str(text or ""))
    if not match:
        return None
    try:
        return date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
    except ValueError:
        return None


def add_years(day: date, years: int) -> date:
    try:
        return day.replace(year=day.year + years)
    except ValueError:  # 2 月 29 日
        return day.replace(year=day.year + years, day=28)


def us_expiry(right_type: str, filing: str, grant: str):
    """按日期推算的保护期届满日（不考虑欠费失效和期限调整）。算不出返回 None。"""
    filed, granted = parse_date(filing), parse_date(grant)
    if right_type == "design":
        if not granted:
            return None
        return add_years(granted, 15 if (filed and filed >= DESIGN_TERM_CHANGE) else 14 if filed else 15)
    if right_type == "patent":  # 名义届满日：实际可能因期限调整更晚，所以只作参考，不凭它丢弃
        return add_years(filed, 20) if filed else None
    return None


def years_ago(years: int, today: date = None) -> str:
    """N 年前的今天，写成 YYYYMMDD。"""
    return add_years(today or date.today(), -years).strftime("%Y%m%d")


# ---------------- 美国以外（Google Patents 的写法：EP3677156B1、DE202019105543U1、JP3232298U、JP1832978S、EM150277340001S）----------------
JP_DESIGN_25 = date(2020, 4, 1)   # 这一天及以后申请的日本意匠保护到申请日起 25 年
JP_DESIGN_20 = date(2007, 4, 1)   # 这一天到 2020-03-31 申请的保护到登记日起 20 年，再早的 15 年


def office_of(number: str) -> str:
    """专利号开头的两位字母：哪个局发的。认不出返回空字符串。"""
    match = re.match(r"([A-Z]{2})[A-Z0-9]", re.sub(r"[^A-Za-z0-9]", "", str(number or "")).upper())
    return match.group(1) if match else ""


def kind_type(number: str, design: bool = False) -> str:
    """按号码结尾的类别码分：S 是外观，U、Y 是实用新型，其余算发明。"""
    text = re.sub(r"[^A-Za-z0-9]", "", str(number or "")).upper()
    if design or re.search(r"\dS\d?$", text):
        return "design"
    if re.search(r"\d[UY]\d?$", text) or re.fullmatch(r"FR\d+[AB]3", text):  # 法国的实用证书类别码是 A3、B3
        return "utility_model"
    return "patent"


def expiry(number: str, right_type: str, filing: str, grant: str):
    """按日期推算的保护期届满日（各国的名义期限，不考虑欠费、放弃和续展）。算不出返回 None。"""
    office = office_of(number)
    if office in ("US", ""):
        return us_expiry(right_type, filing, grant)
    filed, granted = parse_date(filing), parse_date(grant)
    if right_type == "patent":
        return add_years(filed, 20) if filed else None
    if right_type == "utility_model":  # 德国、日本、意大利、西班牙的实用新型都是申请日起 10 年
        return add_years(filed, 10) if filed else None
    if right_type == "design":
        if office == "JP":
            if filed and filed >= JP_DESIGN_25:
                return add_years(filed, 25)
            if granted:
                return add_years(granted, 20 if (not filed or filed >= JP_DESIGN_20) else 15)
            return None
        return add_years(filed, 25) if filed else None  # 欧盟外观：申请日起最长 25 年（每 5 年续展一次，续没续这里不知道）
    return None


def official_link(number: str) -> str:
    """能看到官方附图的页面（Google Patents 上没有图的那几类用）。认不出返回空字符串。"""
    text = re.sub(r"[^A-Za-z0-9]", "", str(number or "")).upper()
    match = re.fullmatch(r"EM(\d{5,9})(\d{4})S?", text)
    if match:  # 欧盟外观 EM150277340001S → 015027734-0001
        return "https://euipo.europa.eu/eSearch/#details/designs/%s-%s" % (match.group(1).zfill(9), match.group(2))
    return ""
