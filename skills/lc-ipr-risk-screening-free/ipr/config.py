"""固定的约定：国家、权利类型、风险等级、预算、目录。只放常量和读配置，不放流程。"""
from __future__ import annotations

import os
import sys
import re
from pathlib import Path
from urllib.parse import urlsplit

SKILL_DIR = Path(__file__).resolve().parent.parent
VERSION = (SKILL_DIR / "VERSION").read_text(encoding="utf-8").strip()
FIXTURE_DIR = SKILL_DIR / "fixtures"
STATE_FILE = "state.json"
USAGE_FILE = "usage.json"
REPORT_FILE = "report.html"
# 会用到的 key 的名字。值只从 .env 或环境变量读，不打印、不进状态文件和报告。
ENV_KEYS = ["SERPAPI_API_KEY", "SERPAPI_API_KEY_BACKUP", "SERPER_API_KEY", "SIGNA_API_KEY", "EPO_OPS_CONSUMER_KEY",
            "EPO_OPS_CONSUMER_SECRET", "EUIPO_CLIENT_ID", "EUIPO_CLIENT_SECRET", "JPO_API_USERNAME", "JPO_API_PASSWORD"]

# 七个目的国。site 是 Amazon 站点域名的结尾；eu 表示另带欧盟层权利。
COUNTRIES = {
    "US": {"name": "美国", "site": "amazon.com", "eu": False, "lang": "en"},
    "GB": {"name": "英国", "site": "amazon.co.uk", "eu": False, "lang": "en"},
    "DE": {"name": "德国", "site": "amazon.de", "eu": True, "lang": "de"},
    "FR": {"name": "法国", "site": "amazon.fr", "eu": True, "lang": "fr"},
    "IT": {"name": "意大利", "site": "amazon.it", "eu": True, "lang": "it"},
    "ES": {"name": "西班牙", "site": "amazon.es", "eu": True, "lang": "es"},
    "JP": {"name": "日本", "site": "amazon.co.jp", "eu": False, "lang": "ja"},
}

# 报告里每类权利一行，按这个顺序。
RIGHT_TYPES = ["patent", "utility_model", "design", "trademark", "artwork"]
RIGHT_NAMES = {
    "patent": "发明专利",
    "utility_model": "实用新型",
    "design": "外观设计",
    "trademark": "商标",
    "artwork": "版权图案",
}
# 目的国没有这种权利时，程序直接写"不适用"，不为它开 AI 会话。
NOT_APPLICABLE = {
    ("US", "utility_model"): "美国只有发明、外观和植物专利，没有实用新型制度。",
    ("GB", "utility_model"): "英国没有实用新型制度。",
}

# 美国以外各国：发明和实用新型查哪几个局、外观查哪个局（Google Patents 的局代码；None 表示这一类没有可用的来源）。
# 欧洲专利（EP）在英、法、德、意、西都可能生效；欧盟外观（EM）对法、德、意、西有效，英国脱欧后不继承。
# 发明（含申请公开）和实用新型一次查回来（不加"只要已授权"），按号码的类别码分开（2026-11-28 起；之前德、意、西的实用新型要另查一次）。
FOREIGN_PLAN = {
    "GB": {"patent": "GB,EP", "design": None},
    "DE": {"patent": "DE,EP", "design": "EM"},
    "FR": {"patent": "FR,EP", "design": "EM"},
    "IT": {"patent": "IT,EP", "design": "EM"},
    "ES": {"patent": "ES,EP", "design": "EM"},
    "JP": {"patent": "JP", "design": "JP"},
}
OFFICE_NAMES = {"EP": "欧洲专利局", "EM": "欧盟知识产权局", "GB": "英国", "DE": "德国", "FR": "法国", "IT": "意大利", "ES": "西班牙", "JP": "日本"}
# 查不了的本国库：逐项记进检索记录（"未检索"加原因），这一类因此不会被评成低。日本商标在商标检索那里单独写。
COVERAGE_GAPS = {
    ("GB", "design"): "英国注册外观没有可用的数据源（英国知识产权局没有开放接口，Google Patents 也没有收录），未检索",
    ("DE", "design"): "德国本国外观没有可用的数据源，未检索（欧盟外观另查）",
    ("FR", "design"): "法国本国外观没有可用的数据源，未检索（欧盟外观另查）",
    ("IT", "design"): "意大利本国外观没有可用的数据源，未检索（欧盟外观另查）",
    ("ES", "design"): "西班牙本国外观没有可用的数据源，未检索（欧盟外观另查）",
    ("DE", "trademark"): "德国本国商标库没有可用的数据源，未检索（欧盟商标另查）",
}
# 商标没有可以合规地用程序按文字检索的来源、改成"挑词 + 人工核对链接"的国家（2026-11-28 查证，见产品需求文档第 6 节）。
TRADEMARK_MANUAL = {"JP"}
# Google Patents 上这两个局的外观没有任何附图：查得到名单，做不了外观比对。
NO_FIGURE_OFFICES = {"EM": "欧盟外观", "JP": "日本意匠"}

RISK_ORDER = ["极低", "低", "中", "高", "极高"]  # 从低到高
RISK_PENDING = "待定"
RISK_LOW = "低"
CONFIDENCE_ORDER = ["低", "中", "高"]
RECHECK_FROM = "中"  # 评到这一级及以上要复核

# 深查名单上限（需求 R-005）和复核上限（R-007）。
DEEP_CAP = {"design": 8, "patent": 6, "utility_model": 6, "trademark": 5, "artwork": 3}
RECHECK_CAP = 8  # 几件放在同一个会话里复核，多几件花不了多少（原来一件一个会话时定的是 4）

# AI 会话的模型分档。light 给量大、判断简单的活（初筛）；strong 给要紧的判断（产品理解、比对、复核）。
# 不用额度最紧的 gpt-6-astra。具体搭配按真跑的质量和用量再调。
MODEL_TIERS = {
    "light": {"model": "gpt-6-luna", "effort": "low"},
    "strong": {"model": "gpt-6.2-sol", "effort": "medium"},
}
AI_TIMEOUT_SECONDS = 240
AI_IMAGE_MAX_PX = 768   # 给 AI 看的图先缩到这个尺寸
SHEET_MAX_PX = 1280     # 拼图里有十几个格子，缩得太小就看不清了
PRODUCT_IMAGES_MAX = 6  # 采集最多留几张商品图
UNDERSTAND_IMAGES = 4   # 产品理解时给 AI 看几张
COMPETITOR_MAX = 3     # 竞品最多采几个（每个大约半分钟）
COMPETITOR_CAPTURE_SECONDS = 120  # 一个竞品最多采这么久（主商品的采集给得更长）
COMPETITOR_TIME_SECONDS = 150  # 这一次运行用到这么久就不再采竞品（竞品是可选的，不能拖垮 8 分钟的线）
UNDERSTAND_IMAGES_LISTING = 8  # 资料入口：图是卖家拟上架用的，要逐张检查道具、水印、别人的标识，多看几张

# 验收线和收口线（需求 R-010）。
BUDGET = {
    "limit_seconds": 8 * 60,
    "limit_tokens": 500_000,
    "wrapup_seconds": 6 * 60,
    "wrapup_tokens": 400_000,
}

# 这台电脑上同时还有别的单在跑时，每单的线放宽到 12 分钟（收口线跟着按比例放到 9 分钟）；token 的线不变。
BUDGET_SHARED = dict(BUDGET, limit_seconds=12 * 60, wrapup_seconds=9 * 60)
RESUME_ERROR_HOURS = 24  # 出错停下的任务，这么久以内把同一条命令再跑一次算续跑；更久的重新开一单（商品页可能已经变了）

STEPS = ["intake", "understand", "search", "screen", "compare", "recheck", "grade", "report"]
STEP_NAMES = {
    "intake": "入口与采集",
    "understand": "产品理解",
    "search": "检索",
    "screen": "初筛",
    "compare": "深查比对",
    "recheck": "要紧项复核",
    "grade": "定级",
    "report": "出报告",
}
# 这些步骤要开 AI 会话；额度用尽后直接跳过它们。
AI_STEPS = {"understand", "screen", "compare", "recheck"}


CACHE_ENV = "LC_IPR_CACHE_DIR"   # 测试时把缓存指到临时目录
CACHE_DAYS = 45                  # 缓存里的附图留多少天


def cache_dir() -> Path:
    """本机留一份取过的专利附图，别的任务再碰到同一件就不用重新取（同类产品查到的专利大量重复）。"""
    override = os.environ.get(CACHE_ENV)
    return Path(override) if override else Path.home() / ".lc-ipr" / "cache" / "figures"


def inside(base, rel):
    """把 rel 接到 base 下面；接完如果跑到 base 外面去了，返回 None。"""
    base = Path(base).resolve()
    target = (base / str(rel)).resolve()
    return target if base == target or base in target.parents else None


RUNS_DIR = Path.home() / "ipr-runs"  # 不指定任务目录时，任务都放在这里
# Amazon 的站点域名（七个目的国之外的站点配合 --country 也能用）。分享用的短链（a.co、amzn.to）不支持。
AMAZON_SITES = ("amazon.com", "amazon.co.uk", "amazon.de", "amazon.fr", "amazon.it", "amazon.es", "amazon.co.jp", "amazon.ca",
                "amazon.com.mx", "amazon.com.br", "amazon.com.au", "amazon.in", "amazon.nl", "amazon.se", "amazon.pl",
                "amazon.com.be", "amazon.com.tr", "amazon.ae", "amazon.sa", "amazon.sg", "amazon.eg", "amazon.ie", "amazon.co.za")
# 这些环境变量不带进任何子进程（鉴权组件、Codex 子会话、浏览器采集）。
CHILD_ENV_BLOCKED = set(ENV_KEYS) | {"LAOCHEN_BACKEND_TOKEN", "LAOCHEN_BACKEND_URL", "RAPIDAPI_KEY", "INPI_USERNAME", "INPI_PASSWORD"}


def child_env() -> dict:
    """给子进程用的环境变量：去掉各种 key 和 token。"""
    return {k: v for k, v in os.environ.items() if k not in CHILD_ENV_BLOCKED}


def is_amazon_url(url: str) -> bool:
    """是不是一个正常的 Amazon 网址：http(s)、域名是 amazon 的站点、不含空白和控制字符。"""
    if not isinstance(url, str) or re.search(r"[\s\x00-\x1f\x7f\u200b-\u200d\u2028\u2029\ufeff]", url):
        return False
    try:
        parts = urlsplit(url)
        host = (parts.hostname or "").lower().rstrip(".")
    except ValueError:
        return False
    if "@" in parts.netloc or "\\" in url.split("?", 1)[0]:  # 域名段里夹账号、路径里夹反斜杠的都不要
        return False
    return parts.scheme in ("http", "https") and any(host == site or host.endswith("." + site) for site in AMAZON_SITES)


def country_from_url(url: str):
    """按链接所在站点取国家；不在七国内返回 None。"""
    host = (urlsplit(url if "//" in url else "//" + url).hostname or "").lower().rstrip(".")
    # 先比长的域名结尾，免得 amazon.com 抢了 amazon.com.xx。
    for code, info in sorted(COUNTRIES.items(), key=lambda kv: -len(kv[1]["site"])):
        if host == info["site"] or host.endswith("." + info["site"]):
            return code
    return None


def risk_rank(risk: str) -> int:
    return RISK_ORDER.index(risk) if risk in RISK_ORDER else -1


def read_text(path) -> str:
    """读用户自己编辑过的配置文件。Windows 的记事本和 PowerShell 存出来的可能带 BOM、是 UTF-16 或 GBK：都认，不因为编码崩掉。"""
    raw = Path(path).read_bytes()
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        return raw.decode("utf-16", errors="replace")
    for encoding in ("utf-8-sig", "gbk"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def setup_streams() -> None:
    """让屏幕输出不因为编码出错。中文 Windows 上输出被别的程序接走（比如 Codex 在读）时，Python 默认按 GBK 写，
    接的那一头按 UTF-8 读就全是乱码，所以这种情况改成按 UTF-8 写；直接在终端里跑不受影响。"""
    for stream in (sys.stdout, sys.stderr):
        if not hasattr(stream, "reconfigure"):
            continue
        try:
            if os.name == "nt" and not stream.isatty() and not os.environ.get("PYTHONIOENCODING"):
                stream.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)  # 用户自己用 PYTHONIOENCODING 指定了编码的，听用户的
            else:
                stream.reconfigure(errors="replace", line_buffering=True)  # 打不出的字符换成问号，不崩；一行一行往外送，进度不积压
        except (ValueError, OSError):
            pass


def load_env(path: Path = None) -> dict:
    """读 Skill 目录下的 .env（KEY=VALUE，一行一个）和环境变量，环境变量优先。只取 ENV_KEYS 里的名字，不打印任何值。"""
    values = {}
    path = path or (SKILL_DIR / ".env")
    if path.is_file():
        for line in read_text(path).splitlines():
            line = line.strip()
            if line.startswith("export "):
                line = line[len("export "):].strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            if key.strip() in ENV_KEYS:
                values[key.strip()] = value.strip().strip('"').strip("'")
    for key in ENV_KEYS:
        if os.environ.get(key):
            values[key] = os.environ[key]
    return {key: value for key, value in values.items() if value}


_SECRETS = []        # 来自 .env 和环境变量的 key
_EXTRA_SECRETS = []  # 运行中追加的（鉴权 token）


def set_secrets(env: dict) -> None:
    """登记本次运行用到的 key 的值，之后 redact 会自动抹掉它们。不影响已经追加登记的 token。"""
    _SECRETS[:] = [v for v in (env or {}).values() if v and len(v) >= 6]


def clear_secrets() -> None:
    """全部清掉（测试收尾用）。"""
    _SECRETS[:] = []
    _EXTRA_SECRETS[:] = []


def add_secret(value: str) -> None:
    """再登记一个要抹掉的值（比如鉴权用的 token）。"""
    if value and len(value) >= 6 and value not in _EXTRA_SECRETS:
        _EXTRA_SECRETS.append(value)


def mask_secrets(text: str) -> str:
    """只按值抹掉已登记的 key，不动别的内容。所有写盘的地方最后都过这一道。"""
    for value in _SECRETS + _EXTRA_SECRETS:
        text = text.replace(value, "***")
    return text


def redact(text, env: dict = None) -> str:
    """写进状态文件、报告、屏幕之前：去掉链接里的查询串（key 常在里面），再把所有 key 的值抹掉。"""
    text = re.sub(r"(https?://[^\s?\"'<>]+)\?[^\s\"'<>]*", r"\1?…", str(text))
    for value in list((env or {}).values()) + _SECRETS + _EXTRA_SECRETS:
        if value and len(value) >= 6:
            text = text.replace(value, "***")
    return text
