#!/usr/bin/env python3
"""Read-only, offline reprocessing of an existing consumer-voice SQLite corpus.

This module deliberately has no network client.  It reads the collector database
with SQLite query-only mode, ignores publication windows, keeps every hard-unique
message, and accepts a message when it is product-related, consumer-authored, and
is reviewed under the six semantic families. Unmatched rule suggestions are
queued for Agent review, never silently discarded.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import html
import json
import os
import re
import sqlite3
import sys
import tempfile
import unicodedata
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple
from urllib.parse import urlsplit


sys.path.insert(0, str(Path(__file__).resolve().parent))
import consumer_voice_evidence as evidence
import voc_prd_pipeline as prd_pipeline


SCHEMA_VERSION = "3.0.0-all-history"
MODE = "all_history_local_reprocess"
CODING_FILENAME = "social_voice_all_history_coding.json"
ANALYSIS_FILENAME = "social_voice_all_history_analysis.json"
RECEIPT_FILENAME = "local_reprocess_receipt.json"
SOURCE_SNAPSHOT_FILENAME = "source_snapshot.json"
TAXONOMY_PROFILE_SCHEMA_VERSION = "1.0.0"

SEMANTIC_CODES = (
    "purchase_selection_recommendation",
    "failure_complaint_return_alternative",
    "satisfaction_recommendation_repurchase",
    "installation_compatibility_scenario",
    "diy_modification_workaround",
    "feature_reverse_innovation",
)
KANO_TYPES = frozenset({"必备型", "期望型", "魅力型", "无差异型", "反向型"})
BUILTIN_TAXONOMY_PROFILE_ID = "car_phone_holder_builtin_v1"

SCOPE_MAP = {
    "category_30d": "category_all_history",
    "segment_1_90d": "segment_1_all_history",
    "segment_2_90d": "segment_2_all_history",
    "segment_3_90d": "segment_3_all_history",
}

SEMANTIC_TAXONOMY: Tuple[Mapping[str, Any], ...] = (
    {
        "code": "purchase_selection_recommendation",
        "label": "购买、选型和推荐",
        "patterns": (
            r"\b(?:buy|bought|purchase|purchased|order|ordered|ordering|shop|shopping|price|cost|worth|recommend(?:ation|ed)?|suggest(?:ion|ed)?|which one|what kind|where (?:can|do|to) (?:i )?(?:buy|get|find)|looking for|link to (?:buy|get)|best (?:one|mount|holder))\b",
            r"(?:购买|买了|想买|下单|选购|选择|选型|价格|多少钱|值不值|值得|推荐|建议|哪一款|哪个好|哪里买|购买链接|求链接)",
            r"\b(?:comprar|compré|precio|recomiend|dónde comprar|acheter|prix|recommand|kaufen|preis|empfehl|comprare|prezzo|consigli|comprar|preço|recomenda)\w*\b",
        ),
    },
    {
        "code": "failure_complaint_return_alternative",
        "label": "故障、抱怨、退货和替代",
        "patterns": (
            r"\b(?:fail(?:ed|ing|s|ure)?|problem|issue|defect(?:ive)?|broke|broken|crack(?:ed)?|fall(?:s|ing)?|fell|drop(?:s|ped|ping)?|shake|shak(?:y|ing)|vibrat\w*|loose|slip(?:s|ped|ping)?|won't|wouldn't|doesn't|didn't|not work(?:ing)?|stopped working|complain\w*|return(?:ed|ing)?|refund|replace(?:ment|d)?|alternative|instead|poor|worst|hate|disappoint\w*|scam|dangerous|overheat\w*)\b",
            r"(?:故障|坏了|损坏|断裂|掉落|摔落|晃动|抖动|震动|松动|滑落|不稳|不工作|不能用|失效|问题|抱怨|投诉|退货|退款|更换|替代|差评|失望|危险|过热)",
            r"\b(?:falla|falló|roto|problema|devolu|reembolso|alternativa|malo|panne|cassé|problème|retour|rembours|schlecht|kaputt|problem|ritorno|rotto|problema)\w*\b",
        ),
    },
    {
        "code": "satisfaction_recommendation_repurchase",
        "label": "满意、推荐和复购",
        "patterns": (
            r"\b(?:love|loved|like it|great|excellent|awesome|amazing|perfect|works? (?:well|great|perfectly|fine)|worked (?:well|great|perfectly)|solid|stable|secure|reliable|satisfied|happy with|recommend(?:ed)?|would buy again|buy again|repurchase|worth every|best mount|good mount|good holder)\b",
            r"(?:满意|喜欢|好用|很好用|太棒|完美|稳定|牢固|可靠|推荐|值得买|会回购|再次购买|复购)",
            r"\b(?:me encanta|excelente|perfecto|funciona bien|satisfech|recomiend|j'adore|excellent|parfait|fonctionne bien|zufrieden|perfekt|funktioniert gut|eccellente|perfetto|funziona bene)\w*\b",
        ),
    },
    {
        "code": "installation_compatibility_scenario",
        "label": "安装、兼容性和使用场景",
        "patterns": (
            r"\b(?:install(?:ed|ing|ation)?|attach(?:ed|ing)?|mount(?:ed|ing)|fit(?:s|ting)?|compatible|compatibility|case friendly|dashboard|dash |windshield|windscreen|air vent|vent clip|cup holder|rearview mirror|steering wheel|truck|semi truck|tractor trailer|cab|tesla|model [3ysx]|cybertruck|navigation|gps|driving|road trip|portrait|landscape|one hand|reach the phone|viewing angle)\b",
            r"(?:安装|固定|粘贴|夹住|适配|兼容|手机壳|仪表盘|中控台|挡风玻璃|出风口|杯架|后视镜|方向盘|卡车|重卡|货车|特斯拉|导航|驾驶|长途|横屏|竖屏|单手|视角)",
            r"\b(?:instalar|instalación|compatible|tablero|parabrisas|camión|installer|compatible|tableau de bord|pare-brise|camion|installieren|kompatibel|armaturenbrett|lkw|installare|compatibile|cruscotto|camion)\w*\b",
        ),
    },
    {
        "code": "diy_modification_workaround",
        "label": "DIY、改装和绕行方案",
        "patterns": (
            r"\b(?:diy|do it yourself|homemade|home made|custom(?:ized|ise|ize)?|modify|modified|modification|modded|hack|workaround|work around|improvised|velcro|double sided tape|duct tape|zip tie|3d print(?:ed|ing)?|printed (?:an?|my)|adapter|made my own|built my own|glue(?:d)?|epoxy|drill(?:ed|ing)?|fabricat\w*)\b",
            r"(?:自己做|自制|DIY|改装|改造|魔改|绕行方案|临时方案|替代办法|魔术贴|双面胶|胶带|扎带|3D打印|转接件|适配器|打孔|粘住)",
            r"\b(?:bricolaje|casero|modifi|adaptador|impreso en 3d|fait maison|bricolage|modifi|adaptateur|selbstgebaut|umbau|adapter|fai da te|modifica|adattatore)\w*\b",
        ),
    },
    {
        "code": "feature_reverse_innovation",
        "label": "新功能、反向需求和创意",
        "patterns": (
            r"\b(?:i wish|wish it|wish there|if only|would like|i want|we want|i need|we need|needs? (?:a|an|to|more|less|better|stronger)|should (?:have|be|add|include|remove)|could (?:have|be|add|include)|would be better|feature request|add (?:a|an|the|more)|without (?:a|the)|don't want|do not want|no app|no magnet|new idea|idea for|design it|invent|location track\w*|tracking|airtag|auto lock|automatic clamp|modular|quick release|anti theft)\b",
            r"(?:希望|要是.*就好|想要|需要|应该有|建议增加|加入功能|新功能|创意|点子|设计成|不想要|不要磁吸|无需应用|更强|更稳|定位|追踪|防盗|自动夹紧|模块化|快拆)",
            r"\b(?:ojalá|quisiera|necesit|debería|sin imán|j'aimerais|souhait|besoin|devrait|ich wünsche|brauche|sollte|vorrei|bisogno|dovrebbe)\w*\b",
        ),
    },
)

PRODUCT_PATTERNS = (
    r"\b(?:car|vehicle|auto|truck|dashboard|dash|windshield|windscreen|vent|cup holder|tesla|model [3ysx]|cybertruck)[ -]+(?:phone|cell phone|mobile phone|iphone|smartphone)[ -]+(?:mount|holder|stand|cradle|clip|grip)\b",
    r"\b(?:phone|cell phone|mobile phone|smartphone|iphone)[ -]?(?:mount|holder|stand|cradle|clip|grip)\b",
    r"\b(?:magsafe|magnetic|suction|adhesive|clamp|vent clip)[ -]+(?:phone[ -]+)?(?:mount|holder|stand|cradle)\b",
    r"\b(?:tesla|model [3ysx]|cybertruck)[ -]+(?:phone[ -]+)?(?:mount|holder|stand|cradle)\b",
    r"(?:车载手机支架|汽车手机支架|手机支架|手机固定架|手机夹|仪表盘支架|出风口支架|磁吸支架)",
    r"\b(?:soporte|support|halterung|supporto) (?:de |pour |für |per )?(?:teléfono|telephone|téléphone|handy|telefono)\b",
)

PROMOTION_PATTERNS = (
    r"\b(?:sponsored|paid partnership|affiliate link|amazon associate|use (?:my )?(?:code|coupon)|promo code|discount code|shop now|tiktok shop|huge discount|offer ends|grab it before|link in (?:my )?bio|subscribe to my channel|wholesale|dropship|order yours|available now|our product|find the product on|product links? below|examples? of products? used)\b",
    r"(?:赞助|推广合作|优惠码|折扣码|点击购买|橱窗下单|批发代理|招商)",
)

BOT_PATTERNS = (
    r"\bpromosm\b",
    r"\b(?:nice video dear|check out my channel|follow for follow|sub4sub|want to promote it)\b",
)

MEDIA_CONTEXT_PATTERNS = (
    r"\b(?:video|channel|filming|filmed|camera|subscriber|creator|title|youtuber|youtube|tiktok|watch(?:ed|ing)?)\b",
    r"(?:视频|频道|拍摄|相机|订阅|博主|作者|标题|观看)",
)

# A thread/video title can establish category context, but a generic word such
# as "great" or "broken" is not enough to turn every reply below it into a
# product opinion.  These anchors keep implicit replies auditable without
# requiring the full phrase "car phone holder" in every comment.
IMPLICIT_PRODUCT_PATTERNS = (
    r"\b(?:phone|cell phone|mobile phone|smartphone|iphone|android|magsafe)\b",
    r"\b(?:mount|mounted|mounting|holder|cradle|clamp|clip|grip|jaw|bracket|arm)\b",
    r"\b(?:suction cup|magnet|magnetic|adhesive|sticky pad|vent mount|air vent|cup holder|dash mount|dashboard mount|windshield mount|wireless charg(?:er|ing)|phone case)\b",
    r"(?:手机|支架|夹臂|夹爪|吸盘|磁吸|背胶|出风口|仪表盘|挡风玻璃|无线充电|手机壳)",
)

IMPLICIT_EXPERIENCE_PATTERNS = (
    r"\b(?:it|this|that|mine|one)\b.{0,100}\b(?:bought|buy|recommend|prefer|return|refund|replace|work|fit|hold|attach|install|mount|fall|fell|drop|broke|broken|loose|wobbl|shake|vibrat|overheat|charge|adjust|remove|love|hate|wish|need|want|bulky|ugly)\w*\b",
    r"\b(?:bought|buy|recommend|prefer|return|refund|replace|work|fit|hold|attach|install|mount|fall|fell|drop|broke|broken|loose|wobbl|shake|vibrat|overheat|charge|adjust|remove|love|hate|wish|need|want|bulky|ugly)\w*\b.{0,100}\b(?:it|this|that|mine|one)\b",
    r"(?:它|这个|这款|我的|那款).{0,60}(?:买|推荐|退货|退款|替换|好用|适配|固定|安装|掉落|松动|晃动|震动|过热|充电|调节|拆卸|喜欢|讨厌|希望|需要|想要|笨重|难看)",
)

INDIFFERENCE_PATTERNS = (
    r"\b(?:i don't care|do not care|doesn't matter|does not matter|no difference|indifferent|irrelevant to me|either way is fine)\b",
    r"(?:无所谓|不在乎|有没有都行|都可以|不影响我)",
)

REJECTION_PATTERNS = (
    r"\b(?:i don't want|do not want|don't need|do not need|no magnet|no app|without (?:an? )?(?:app|magnet|charging|cable|adhesive)|rather not|avoid this feature|remove this feature)\b",
    r"(?:不要|不想要|不需要|拒绝|宁愿不用|取消这个功能|去掉这个功能|不要磁吸|不要应用)",
)

TOPIC_DEFINITIONS: Tuple[Mapping[str, Any], ...] = (
    {"code": "stability_security", "label": "颠簸路面稳定与防掉落", "patterns": (r"\b(?:fall|fell|drop|shake|shaky|vibrat|wobbl|loose|slip|pothole|bump|stable|solid|secure|hold firmly)\w*\b", r"(?:掉落|摔落|晃动|抖动|震动|松动|滑落|颠簸|坑洼|稳定|牢固)")},
    {"code": "adhesive_heat", "label": "胶粘/吸盘与高温耐久", "patterns": (r"\b(?:adhesive|sticky|stick(?:s|ing)?|glue|suction|pad|tape|heat|hot|sun|summer|melt|peel)\w*\b", r"(?:胶粘|背胶|双面胶|吸盘|高温|暴晒|太阳|夏天|融化|脱胶)")},
    {"code": "magnet_strength", "label": "磁力强度与磁吸可靠性", "patterns": (r"\b(?:magnet|magnetic|magsafe|metal ring|magneti[sz]e)\w*\b", r"(?:磁吸|磁铁|磁力|磁环)")},
    {"code": "charging", "label": "无线充电与供电", "patterns": (r"\b(?:wireless charg|charging|charger|qi2?|usb[ -]?c|power|cable)\w*\b", r"(?:无线充电|充电|供电|电源|线缆)")},
    {"code": "phone_case_compatibility", "label": "手机/手机壳兼容", "patterns": (r"\b(?:iphone|android|samsung|pixel|phone size|large phone|case friendly|thick case|otterbox|compatible|fit)\w*\b", r"(?:手机壳|厚壳|机型|尺寸|兼容|适配)")},
    {"code": "installation_removal", "label": "安装、拆卸与无损固定", "patterns": (r"\b(?:install|attach|remove|removal|mounting|drill|damage|residue|scratch|stuck)\w*\b", r"(?:安装|拆卸|移除|打孔|残胶|划伤|无损)")},
    {"code": "mounting_position", "label": "仪表盘/挡风玻璃/出风口位置", "patterns": (r"\b(?:dashboard|dash |windshield|windscreen|air vent|vent clip|cup holder|rearview mirror|steering wheel)\b", r"(?:仪表盘|中控台|挡风玻璃|出风口|杯架|后视镜|方向盘)")},
    {"code": "adjustability_visibility", "label": "角度调节、视野与可达性", "patterns": (r"\b(?:adjust|angle|rotate|rotation|portrait|landscape|view|reach|position|arm length|obstruct|block(?:s|ing)? (?:the )?(?:view|screen))\w*\b", r"(?:调节|角度|旋转|横屏|竖屏|视野|够得到|遮挡|位置)")},
    {"code": "one_hand_quick_release", "label": "单手取放与快拆", "patterns": (r"\b(?:one hand|single hand|quick release|easy release|auto lock|automatic clamp|grab the phone)\b", r"(?:单手|快拆|快速取放|自动夹紧)")},
    {"code": "durability_material", "label": "结构耐久与材料可靠性", "patterns": (r"\b(?:durable|durability|plastic|metal|aluminum|steel|break|broke|broken|crack|wear|rugged)\w*\b", r"(?:耐用|耐久|塑料|金属|铝合金|钢|断裂|磨损|坚固)")},
    {"code": "driving_safety", "label": "驾驶安全与不遮挡", "patterns": (r"\b(?:safe|safety|dangerous|distract|obstruct|block the view|airbag|hands free|eyes off the road)\w*\b", r"(?:安全|危险|分心|遮挡|气囊|免手持)")},
    {"code": "truck_heavy_duty", "label": "卡车/重型车长途与强震场景", "patterns": (r"\b(?:truck|semi truck|semi-truck|tractor trailer|18 wheeler|lorry|cab|fleet|heavy duty|long haul|rough road|off road)\b", r"(?:卡车|重卡|货车|半挂|长途运输|车队|重型|烂路|越野)")},
    {"code": "tesla_integration", "label": "Tesla屏幕/内饰一体化", "patterns": (r"\b(?:tesla|model [3ysx]|cybertruck|tesla screen|center screen)\b", r"(?:特斯拉|中控屏)")},
    {"code": "diy_customization", "label": "DIY、3D打印与自定义改装", "patterns": (r"\b(?:diy|homemade|custom|modify|modded|hack|workaround|velcro|tape|zip tie|3d print|adapter|made my own|built my own)\w*\b", r"(?:自制|DIY|改装|改造|魔术贴|胶带|扎带|3D打印|转接件|适配器)")},
    {"code": "tracking_anti_theft", "label": "支架定位、防盗与遗失找回", "patterns": (r"\b(?:location track|tracking|tracker|airtag|find my|anti theft|stolen|theft)\w*\b", r"(?:定位|追踪|防盗|遗失找回)")},
    {"code": "price_value", "label": "价格与性价比", "patterns": (r"\b(?:price|cost|cheap|expensive|worth|value|shipping)\w*\b", r"(?:价格|多少钱|便宜|贵|性价比|运费)")},
    {"code": "appearance_interior", "label": "外观与内饰融合", "patterns": (r"\b(?:design|beautiful|ugly|bulky|minimal(?:ist)?|interior|color|sleek|low profile|oem look|blend(?:s|ed)? in|looks? (?:good|bad|great|ugly|bulky|clean))\w*\b", r"(?:外观|设计|好看|难看|笨重|简约|内饰|颜色)")},
)

SEGMENT_PATTERNS = {
    "segment_1_all_history": (
        r"\b(?:mechanical clamp|clamp|jaw|jaws|spring loaded|clip arm|grip arm|cradle|ratchet|squeeze arm)\w*\b",
        r"(?:机械夹持|夹臂|夹爪|弹簧夹|卡爪|夹紧)",
    ),
    "segment_2_all_history": (
        r"\b(?:truck|semi truck|semi-truck|tractor trailer|18 wheeler|lorry|cab|fleet|heavy duty|long haul)\b",
        r"(?:卡车|重卡|货车|半挂|长途运输|车队|重型)",
    ),
    "segment_3_all_history": (
        r"\b(?:tesla|model [3ysx]|cybertruck|tesla screen|center screen)\b",
        r"(?:特斯拉|中控屏)",
    ),
}

GENERIC_TOPIC_BY_SEMANTIC = {
    "purchase_selection_recommendation": ("general_purchase_selection", "一般购买与选型"),
    "failure_complaint_return_alternative": ("general_failure_complaint", "一般故障与抱怨"),
    "satisfaction_recommendation_repurchase": ("general_satisfaction", "一般满意与推荐"),
    "installation_compatibility_scenario": ("general_installation_usage", "一般安装与使用"),
    "diy_modification_workaround": ("general_diy_workaround", "一般DIY与绕行"),
    "feature_reverse_innovation": ("general_feature_idea", "一般功能创意"),
}

KANO_BY_TOPIC = {
    "stability_security": "必备型",
    "phone_case_compatibility": "必备型",
    "installation_removal": "必备型",
    "driving_safety": "必备型",
    "durability_material": "必备型",
    "adhesive_heat": "期望型",
    "magnet_strength": "期望型",
    "charging": "期望型",
    "mounting_position": "期望型",
    "adjustability_visibility": "期望型",
    "one_hand_quick_release": "期望型",
    "price_value": "期望型",
    "truck_heavy_duty": "魅力型",
    "tesla_integration": "魅力型",
    "diy_customization": "魅力型",
    "tracking_anti_theft": "魅力型",
    "appearance_interior": "期望型",
}


def _compile_many(patterns: Iterable[str]) -> Tuple[re.Pattern[str], ...]:
    return tuple(re.compile(pattern, flags=re.IGNORECASE) for pattern in patterns)


SEMANTIC_REGEX = {
    str(item["code"]): _compile_many(item["patterns"]) for item in SEMANTIC_TAXONOMY
}
PRODUCT_REGEX = _compile_many(PRODUCT_PATTERNS)
PROMOTION_REGEX = _compile_many(PROMOTION_PATTERNS)
BOT_REGEX = _compile_many(BOT_PATTERNS)
MEDIA_CONTEXT_REGEX = _compile_many(MEDIA_CONTEXT_PATTERNS)
IMPLICIT_PRODUCT_REGEX = _compile_many(IMPLICIT_PRODUCT_PATTERNS)
IMPLICIT_EXPERIENCE_REGEX = _compile_many(IMPLICIT_EXPERIENCE_PATTERNS)
INDIFFERENCE_REGEX = _compile_many(INDIFFERENCE_PATTERNS)
REJECTION_REGEX = _compile_many(REJECTION_PATTERNS)
TOPIC_REGEX = {
    str(item["code"]): _compile_many(item["patterns"]) for item in TOPIC_DEFINITIONS
}
TOPIC_LABELS = {str(item["code"]): str(item["label"]) for item in TOPIC_DEFINITIONS}
SEGMENT_REGEX = {key: _compile_many(value) for key, value in SEGMENT_PATTERNS.items()}
SEMANTIC_LABELS = {str(item["code"]): str(item["label"]) for item in SEMANTIC_TAXONOMY}

BUILTIN_TAXONOMY: Mapping[str, Any] = {
    "profile_id": BUILTIN_TAXONOMY_PROFILE_ID,
    "source": "built_in",
    "product_label": "车载手机支架",
    "semantic_taxonomy": SEMANTIC_TAXONOMY,
    "semantic_regex": SEMANTIC_REGEX,
    "semantic_labels": SEMANTIC_LABELS,
    "product_regex": PRODUCT_REGEX,
    "implicit_product_regex": IMPLICIT_PRODUCT_REGEX,
    "implicit_experience_regex": IMPLICIT_EXPERIENCE_REGEX,
    "topic_regex": TOPIC_REGEX,
    "topic_labels": TOPIC_LABELS,
    "segment_regex": SEGMENT_REGEX,
    "segment_definitions": (),
    "kano_by_topic": KANO_BY_TOPIC,
}

_BUILTIN_CATEGORY_REGEX = _compile_many(
    (
        r"\b(?:car|vehicle|automotive|auto|truck)[ -]+(?:phone|cell phone|mobile phone|smartphone|iphone)[ -]+(?:mount|holder|stand|cradle)\b",
        r"\b(?:phone|cell phone|mobile phone|smartphone|iphone)[ -]+(?:mount|holder|stand|cradle)[ -]+(?:for|in)[ -]+(?:car|vehicle|truck)\b",
        r"(?:车载手机支架|汽车手机支架|车用手机支架|卡车手机支架|重卡手机支架)",
    )
)

_FORBIDDEN_KEY_REGEX = re.compile(
    r"(?:confidence|window|(?:^|_)(?:start_at|end_at|time_range|date_range)(?:$|_)|source[_ -]?status|(?:^|_)evidence(?:_[a-z]+)*_(?:counts?|totals?)(?:$|_)|(?:^|_)(?:counts?|totals?)(?:_[a-z]+)*_evidence(?:$|_))",
    flags=re.IGNORECASE,
)
_OLD_SCOPE_REGEX = re.compile(
    r"(?:(?:category|segment)(?:_[a-z0-9]+)*_(?:30d|90d))",
    flags=re.IGNORECASE,
)


class LocalReprocessError(RuntimeError):
    """A local input or reconciliation failure."""


def iso_utc() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def normalize_text(value: Any) -> str:
    text = html.unescape(str(value or ""))
    text = unicodedata.normalize("NFKC", text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = text.replace("\u200b", " ").replace("\ufeff", " ")
    return re.sub(r"\s+", " ", text).strip()


def _matches(text: str, patterns: Sequence[re.Pattern[str]]) -> bool:
    return any(pattern.search(text) for pattern in patterns)


def _taxonomy(value: Optional[Mapping[str, Any]]) -> Mapping[str, Any]:
    return value or BUILTIN_TAXONOMY


def semantic_codes(
    text: str, taxonomy: Optional[Mapping[str, Any]] = None
) -> List[str]:
    regex = _taxonomy(taxonomy)["semantic_regex"]
    return [code for code in SEMANTIC_CODES if _matches(text, regex[code])]


def topic_codes(
    text: str,
    semantics: Sequence[str],
    taxonomy: Optional[Mapping[str, Any]] = None,
) -> List[str]:
    regex = _taxonomy(taxonomy)["topic_regex"]
    topics = [code for code, patterns in regex.items() if _matches(text, patterns)]
    if not topics:
        topics = [GENERIC_TOPIC_BY_SEMANTIC[code][0] for code in semantics]
    return list(dict.fromkeys(topics))


def segment_codes(
    text: str, taxonomy: Optional[Mapping[str, Any]] = None
) -> List[str]:
    regex = _taxonomy(taxonomy)["segment_regex"]
    return [code for code, patterns in regex.items() if _matches(text, patterns)]


def has_word_content(text: str) -> bool:
    letters = sum(1 for char in text if char.isalpha())
    digits = sum(1 for char in text if char.isdigit())
    return letters >= 2 or (letters >= 1 and digits >= 1)


def is_promotion_or_bot(text: str) -> bool:
    if _matches(text, BOT_REGEX):
        return True
    promotion = _matches(text, PROMOTION_REGEX)
    urls = len(re.findall(r"https?://|www\.", text, flags=re.IGNORECASE))
    commercial_markers = len(
        re.findall(
            r"\b(?:buy|purchase|shop|coupon|code|amazon|aliexpress|temu|shipping|subscribe)\b",
            text,
            flags=re.IGNORECASE,
        )
    )
    seller_link = bool(
        urls
        and re.search(
            r"(?:^|\b)(?:here (?:is|'s) (?:the )?link|link\s*:|find (?:it|the product) (?:here|at)|product link|link below|link in (?:the )?description)",
            text,
            flags=re.IGNORECASE,
        )
    )
    creator_cta = bool(
        re.search(
            r"\b(?:you gotta try|today i(?:'ll| will) show|order now|order yours|shop now|check it out|check out our|visit (?:our|my|the)|get it now|yellow card|left (?:a|the) link|link below|link in (?:the )?description)\b",
            text,
            flags=re.IGNORECASE,
        )
    )
    return bool(
        promotion
        or seller_link
        or creator_cta
        or urls >= 2
        or (urls and commercial_markers >= 3)
    )


def is_bare_generic_praise(text: str) -> bool:
    """Reject context-free applause even inside an otherwise relevant thread."""
    simplified = re.sub(r"[^\w\s]", " ", text.casefold(), flags=re.UNICODE)
    simplified = re.sub(r"\s+", " ", simplified).strip()
    if re.search(r"\b(?:great|nice|awesome|amazing|good|cool|perfect) video\b", simplified):
        return True
    generic = {
        "great",
        "nice",
        "awesome",
        "amazing",
        "perfect",
        "love it",
        "very good",
        "good job",
        "so cool",
        "thank you",
        "thanks",
    }
    return simplified in generic


def is_media_or_creator_comment(
    text: str, taxonomy: Optional[Mapping[str, Any]] = None
) -> bool:
    """Media/creator appraisal is not a product experience by itself."""
    return bool(
        _matches(text, MEDIA_CONTEXT_REGEX)
        and not _matches(text, _taxonomy(taxonomy)["product_regex"])
    )


def is_recognizable_implicit_product_expression(
    text: str, taxonomy: Optional[Mapping[str, Any]] = None
) -> bool:
    """Require a product/component anchor or an explicit product-experience form."""
    current = _taxonomy(taxonomy)
    return bool(
        _matches(text, current["implicit_product_regex"])
        or _matches(text, current["implicit_experience_regex"])
    )


def is_platform_parent_content(row: Mapping[str, Any]) -> bool:
    """Exclude saved media descriptions/transcripts; the unit is a consumer message."""
    source = str(row.get("source") or "").casefold()
    if source not in {"youtube", "tiktok", "instagram"}:
        return False
    raw = _safe_json(row.get("raw_json"))
    if row.get("is_creator_content") is True or raw.get("is_creator_content") is True or raw.get("content_role") == "creator_context":
        return True
    if str(raw.get("raw_origin") or "").casefold() == "last30days_parent":
        return True
    content_id = str(row.get("content_id") or "")
    video_id = str(row.get("video_id") or "")
    if source == "youtube" and content_id and video_id and content_id == video_id:
        return True
    source_position = str(raw.get("source_position") or "").casefold()
    return bool(source_position.endswith(":parent"))


def _product_context_index(
    rows: Sequence[Mapping[str, Any]],
    discoveries: Mapping[str, Sequence[Mapping[str, str]]],
    taxonomy: Optional[Mapping[str, Any]] = None,
) -> Mapping[str, Any]:
    """Build auditable parent/root context without trusting query scope alone."""
    current = _taxonomy(taxonomy)
    infos: Dict[str, Dict[str, Any]] = {}
    content_index: Dict[Tuple[str, str], str] = {}
    groups: Dict[Tuple[str, str], List[Dict[str, Any]]] = defaultdict(list)
    for row in rows:
        record_id = str(row.get("record_id") or "")
        text = normalize_text(row.get("text"))
        source = _source_namespace(row)
        group_id = str(
            row.get("video_id")
            or row.get("thread_id")
            or row.get("parent_content_id")
            or record_id
        )
        info = {
            "row": row,
            "record_id": record_id,
            "source": source,
            "text": text,
            "semantics": semantic_codes(text, current),
            "direct": bool(_matches(text, current["product_regex"])),
            "word_content": has_word_content(text),
            "promotion": is_promotion_or_bot(text) if text else False,
            "author": _author_key(row),
            "group_id": group_id,
            "routes": list(discoveries.get(record_id, [])),
        }
        infos[record_id] = info
        content_id = str(row.get("content_id") or "")
        if content_id:
            content_index[(source, content_id)] = record_id
        groups[(source, group_id)].append(info)

    corroborated_groups: set[Tuple[str, str]] = set()
    rooted_groups: set[Tuple[str, str]] = set()
    group_audit: Dict[Tuple[str, str], Dict[str, Any]] = {}
    for group_key, children in groups.items():
        source, group_id = group_key
        usable = [child for child in children if child["word_content"] and not child["promotion"]]
        anchors = [child for child in usable if child["direct"]]
        anchor_authors = {str(child["author"]) for child in anchors if evidence.known_author(child["author"])}
        anchor_ratio = len(anchors) / len(usable) if usable else 0.0
        # A locally saved root/title explicitly naming the product is a stronger
        # context than a search query.  YouTube parent records use content_id=video_id.
        for child in anchors:
            row = child["row"]
            content_id = str(row.get("content_id") or "")
            if content_id and content_id == group_id:
                rooted_groups.add(group_key)
                break
        # Unknown-title video/thread inheritance needs both independent authors
        # and a relative threshold.  This prevents one huge false-positive video
        # from being admitted merely because it contains a few absolute anchors.
        minimum_authors = 2
        minimum_ratio = 0.05
        if len(anchor_authors) >= minimum_authors and anchor_ratio >= minimum_ratio:
            corroborated_groups.add(group_key)
        group_audit[group_key] = {
            "usable_messages": len(usable),
            "explicit_product_messages": len(anchors),
            "explicit_product_authors": len(anchor_authors),
            "explicit_product_share": round(anchor_ratio, 6),
            "root_explicit": group_key in rooted_groups,
            "corroborated": group_key in corroborated_groups,
        }
    return {
        "infos": infos,
        "content_index": content_index,
        "rooted_groups": rooted_groups,
        "corroborated_groups": corroborated_groups,
        "group_audit": group_audit,
    }


def _resolve_product_context(
    info: Mapping[str, Any],
    context: Mapping[str, Any],
    taxonomy: Optional[Mapping[str, Any]] = None,
) -> Tuple[Optional[str], Optional[str], Optional[Mapping[str, Any]]]:
    current = _taxonomy(taxonomy)
    product_label = str(current["product_label"])
    if bool(info["direct"]):
        return (
            "本条显式产品锚点",
            "本条明确提及%s或配置的等价产品词" % product_label,
            None,
        )
    if is_bare_generic_praise(str(info["text"])) or is_media_or_creator_comment(
        str(info["text"]), current
    ):
        return None, None, None
    if not is_recognizable_implicit_product_expression(str(info["text"]), current):
        return None, None, None
    source = str(info["source"])
    row = info["row"]
    content_index = context["content_index"]
    parent_id = str(row.get("parent_content_id") or "")
    visited: set[str] = set()
    for _ in range(4):
        if not parent_id or parent_id in visited:
            break
        visited.add(parent_id)
        parent_record_id = content_index.get((source, parent_id))
        if not parent_record_id:
            break
        parent = context["infos"][parent_record_id]
        if bool(parent["direct"]):
            return "已确认父级表达", "本条命中六类语义且父级明确提及产品", None
        parent_id = str(parent["row"].get("parent_content_id") or "")
    group_key = (source, str(info["group_id"]))
    audit = context["group_audit"].get(group_key)
    if group_key in context["rooted_groups"]:
        return "已确认根内容", "本条命中六类语义且本地根内容明确提及产品", audit
    if group_key in context["corroborated_groups"]:
        return (
            "多作者产品锚点交叉确认",
            "本条命中六类语义，且同一内容下多个独立作者的显式产品表达达到比例门槛",
            audit,
        )
    return None, None, audit


def _safe_json(value: Any) -> Mapping[str, Any]:
    try:
        loaded = json.loads(str(value or "{}"))
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
    return loaded if isinstance(loaded, Mapping) else {}


def _engagement(raw_json: Any) -> Mapping[str, Any]:
    raw = _safe_json(raw_json)
    engagement = raw.get("engagement")
    if isinstance(engagement, Mapping):
        return {
            key: engagement.get(key)
            for key in ("likes", "replies", "shares", "views", "score")
            if engagement.get(key) is not None
        }
    return {}


def _engagement_score(voice: Mapping[str, Any]) -> float:
    engagement = voice.get("engagement")
    if not isinstance(engagement, Mapping):
        return 0.0
    total = 0.0
    for key, weight in (("likes", 1.0), ("score", 1.0), ("replies", 2.0), ("shares", 2.0)):
        try:
            total += max(0.0, float(engagement.get(key) or 0)) * weight
        except (TypeError, ValueError):
            continue
    return total


def _source_namespace(row: Mapping[str, Any]) -> str:
    source = str(row.get("source") or "unknown").casefold()
    if source in {"web", "blog", "forum"}:
        try:
            host = urlsplit(str(row.get("canonical_url") or row.get("url") or "")).netloc.casefold()
        except ValueError:
            host = ""
        return source + ":" + host if host else source + ":unverified"
    return source


def _author_key(row: Mapping[str, Any]) -> Optional[str]:
    source = _source_namespace(row)
    if source.endswith(":unverified"):
        return None
    # A deleted/anonymous label remains unknown even when an ingestion tool has
    # hashed that placeholder. It must never become one author per record.
    for field in ("author_label", "author_id"):
        label = str(row.get(field) or "").strip()
        if label and not evidence.known_author(label):
            return None
    for key in ("author_id", "author_hash", "author_label"):
        value = str(row.get(key) or "").strip()
        if evidence.known_author(value):
            return source + ":" + value
    return None


def _thread_key(row: Mapping[str, Any]) -> Optional[str]:
    source = _source_namespace(row)
    if source.endswith(":unverified"):
        return None
    for key in ("thread_id", "video_id"):
        value = str(row.get(key) or "").strip()
        if value:
            return source + ":" + value
    # Parent IDs and comment permalinks are not proof of independent root
    # discussions. Unknown roots are retained but do not increase coverage.
    return None


def _source_url(row: Mapping[str, Any]) -> Optional[str]:
    url = str(row.get("canonical_url") or "").strip()
    if url.startswith(("https://", "http://")):
        return url
    if str(row.get("source") or "") == "youtube" and row.get("video_id"):
        base = "https://www.youtube.com/watch?v=" + str(row["video_id"])
        content_id = str(row.get("content_id") or "")
        if content_id and content_id != str(row.get("video_id") or ""):
            return base + "&lc=" + content_id
        return base
    return None


def _sentiment(semantics: Sequence[str]) -> str:
    positive = "satisfaction_recommendation_repurchase" in semantics
    negative = "failure_complaint_return_alternative" in semantics
    if positive and negative:
        return "正负并存"
    if positive:
        return "正向"
    if negative:
        return "负向"
    return "中性/诉求"


def _output_segment(selection: Mapping[str, Any]) -> Dict[str, Any]:
    source_id = str(selection.get("segment_id") or "")
    new_id = _map_all_history_string(source_id)
    result = {
        str(key): _clean_prior_value(value)
        for key, value in selection.items()
        if str(key) != "source_segment_id"
    }
    result["segment_id"] = new_id
    return result


def _load_json(path: Path) -> Mapping[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise LocalReprocessError("无法读取 JSON：%s" % path) from exc
    if not isinstance(value, Mapping):
        raise LocalReprocessError("JSON 顶层必须是对象：%s" % path)
    return value


def _string_list(value: Any, field: str, *, required: bool = False) -> List[str]:
    if value is None:
        values: List[Any] = []
    elif isinstance(value, list):
        values = value
    else:
        raise LocalReprocessError("taxonomy profile 字段 %s 必须是字符串数组" % field)
    if any(not isinstance(item, str) for item in values):
        raise LocalReprocessError("taxonomy profile 字段 %s 只能包含字符串" % field)
    result = [item.strip() for item in values if item.strip()]
    if len(result) != len(values):
        raise LocalReprocessError("taxonomy profile 字段 %s 不允许空字符串" % field)
    if required and not result:
        raise LocalReprocessError("taxonomy profile 字段 %s 至少需要一项" % field)
    return result


def _literal_term_pattern(term: str) -> str:
    escaped = re.escape(term)
    if term[0].isascii() and term[-1].isascii() and term[0].isalnum() and term[-1].isalnum():
        return r"(?<!\w)%s(?!\w)" % escaped
    return escaped


def _profile_regex(
    terms: Any,
    patterns: Any,
    field: str,
    *,
    required: bool = False,
) -> Tuple[re.Pattern[str], ...]:
    raw = [
        *(_literal_term_pattern(term) for term in _string_list(terms, field + ".terms")),
        *_string_list(patterns, field + ".patterns"),
    ]
    if required and not raw:
        raise LocalReprocessError("taxonomy profile 字段 %s 至少需要 term 或 pattern" % field)
    try:
        return _compile_many(raw)
    except re.error as exc:
        raise LocalReprocessError("taxonomy profile 字段 %s 含无效正则：%s" % (field, exc)) from exc


def _profile_entry_regex(entry: Mapping[str, Any], field: str) -> Tuple[re.Pattern[str], ...]:
    return _profile_regex(entry.get("terms"), entry.get("patterns"), field, required=True)


def _load_taxonomy_profile(path: Path) -> Mapping[str, Any]:
    path = path.expanduser().resolve()
    document = _load_json(path)
    allowed_keys = {
        "schema_version",
        "profile_id",
        "product_label",
        "product_terms",
        "product_patterns",
        "implicit_product_terms",
        "implicit_product_patterns",
        "implicit_experience_patterns",
        "semantic_extensions",
        "topics",
        "segments",
        "kano_mapping",
        "required_scenarios",
    }
    unknown = sorted(set(map(str, document)) - allowed_keys)
    if unknown:
        raise LocalReprocessError("taxonomy profile 含未知字段：%s" % ", ".join(unknown))
    if document.get("schema_version") != TAXONOMY_PROFILE_SCHEMA_VERSION:
        raise LocalReprocessError(
            "taxonomy profile schema_version 必须为 %s" % TAXONOMY_PROFILE_SCHEMA_VERSION
        )
    required_keys = {
        "profile_id",
        "product_label",
        "product_terms",
        "implicit_product_terms",
        "semantic_extensions",
        "topics",
        "segments",
        "kano_mapping",
    }
    missing_keys = sorted(required_keys - set(map(str, document)))
    if missing_keys:
        raise LocalReprocessError("taxonomy profile 缺少字段：%s" % ", ".join(missing_keys))
    profile_id = str(document.get("profile_id") or "").strip()
    product_label = str(document.get("product_label") or "").strip()
    if not re.fullmatch(r"[a-z][a-z0-9_.-]{2,63}", profile_id):
        raise LocalReprocessError("taxonomy profile profile_id 格式无效")
    if not product_label:
        raise LocalReprocessError("taxonomy profile 缺少 product_label")

    product_regex = _profile_regex(
        document.get("product_terms"),
        document.get("product_patterns"),
        "product",
        required=True,
    )
    implicit_product_regex = _profile_regex(
        document.get("implicit_product_terms"),
        document.get("implicit_product_patterns"),
        "implicit_product",
        required=True,
    )
    _string_list(document.get("product_terms"), "product_terms", required=True)
    _string_list(
        document.get("implicit_product_terms"), "implicit_product_terms", required=True
    )
    implicit_experience_patterns = _string_list(
        document.get("implicit_experience_patterns"), "implicit_experience_patterns"
    )
    try:
        implicit_experience_regex = _compile_many(
            [*IMPLICIT_EXPERIENCE_PATTERNS, *implicit_experience_patterns]
        )
    except re.error as exc:
        raise LocalReprocessError("taxonomy profile 隐式体验正则无效：%s" % exc) from exc

    extensions = document.get("semantic_extensions")
    if not isinstance(extensions, Mapping):
        raise LocalReprocessError("taxonomy profile semantic_extensions 必须是对象")
    invalid_semantics = sorted(set(map(str, extensions)) - set(SEMANTIC_CODES))
    if invalid_semantics:
        raise LocalReprocessError(
            "taxonomy profile 含未知六语义代码：%s" % ", ".join(invalid_semantics)
        )
    semantic_regex: Dict[str, Tuple[re.Pattern[str], ...]] = {}
    for item in SEMANTIC_TAXONOMY:
        code = str(item["code"])
        extension = extensions.get(code, {})
        if not isinstance(extension, Mapping):
            raise LocalReprocessError("semantic_extensions.%s 必须是对象" % code)
        extra_keys = sorted(set(map(str, extension)) - {"terms", "patterns"})
        if extra_keys:
            raise LocalReprocessError(
                "semantic_extensions.%s 含未知字段：%s" % (code, ", ".join(extra_keys))
            )
        extra = _profile_regex(
            extension.get("terms"),
            extension.get("patterns"),
            "semantic_extensions.%s" % code,
        )
        semantic_regex[code] = (*_compile_many(item["patterns"]), *extra)

    raw_topics = document.get("topics")
    if not isinstance(raw_topics, list):
        raise LocalReprocessError("taxonomy profile topics 必须是数组，可为空以支持开放发现")
    topic_regex: Dict[str, Tuple[re.Pattern[str], ...]] = {}
    topic_labels: Dict[str, str] = {}
    for index, raw in enumerate(raw_topics):
        if not isinstance(raw, Mapping):
            raise LocalReprocessError("taxonomy profile topics[%d] 必须是对象" % index)
        extra_keys = sorted(set(map(str, raw)) - {"code", "label", "terms", "patterns"})
        if extra_keys:
            raise LocalReprocessError(
                "taxonomy profile topics[%d] 含未知字段：%s"
                % (index, ", ".join(extra_keys))
            )
        code = str(raw.get("code") or "").strip()
        label = str(raw.get("label") or "").strip()
        if not re.fullmatch(r"[a-z][a-z0-9_]{2,63}", code) or code.startswith("general_"):
            raise LocalReprocessError("taxonomy profile topics[%d].code 格式无效" % index)
        if code in topic_regex:
            raise LocalReprocessError("taxonomy profile topic code 重复：%s" % code)
        if not label:
            raise LocalReprocessError("taxonomy profile topics[%d] 缺少 label" % index)
        topic_regex[code] = _profile_entry_regex(raw, "topics[%d]" % index)
        topic_labels[code] = label

    raw_segments = document.get("segments")
    if not isinstance(raw_segments, list) or not (0 <= len(raw_segments) <= 3):
        raise LocalReprocessError("taxonomy profile segments 必须包含 0-3 项")
    segment_regex: Dict[str, Tuple[re.Pattern[str], ...]] = {}
    segment_definitions: List[Dict[str, Any]] = []
    ranks: set[int] = set()
    for index, raw in enumerate(raw_segments):
        if not isinstance(raw, Mapping):
            raise LocalReprocessError("taxonomy profile segments[%d] 必须是对象" % index)
        extra_keys = sorted(
            set(map(str, raw))
            - {"segment_id", "rank", "dimension", "feature", "terms", "patterns"}
        )
        if extra_keys:
            raise LocalReprocessError(
                "taxonomy profile segments[%d] 含未知字段：%s"
                % (index, ", ".join(extra_keys))
            )
        segment_id = str(raw.get("segment_id") or "").strip()
        # Legacy Top3 exports use ``segment_*_all_history`` IDs, while the
        # user-selected single-segment workflow preserves the upstream stable
        # segment ID (for example ``compact_desk``).  Both are stable IDs;
        # their exact match to the selected scope is enforced later in
        # ``reprocess``.  Requiring the legacy suffix here made a valid
        # single-segment profile impossible to express.
        if not re.fullmatch(r"[a-z][a-z0-9_]{2,63}", segment_id):
            raise LocalReprocessError(
                "taxonomy profile segments[%d].segment_id 格式无效" % index
            )
        if segment_id in segment_regex:
            raise LocalReprocessError("taxonomy profile segment_id 重复：%s" % segment_id)
        if isinstance(raw.get("rank"), bool):
            raise LocalReprocessError("taxonomy profile segments[%d].rank 无效" % index)
        try:
            rank = int(raw.get("rank"))
        except (TypeError, ValueError):
            raise LocalReprocessError("taxonomy profile segments[%d].rank 无效" % index)
        if rank not in {1, 2, 3} or rank in ranks:
            raise LocalReprocessError("taxonomy profile segment rank 必须在1-3内且不重复")
        ranks.add(rank)
        dimension = str(raw.get("dimension") or "").strip()
        feature = str(raw.get("feature") or "").strip()
        if not dimension or not feature:
            raise LocalReprocessError("taxonomy profile segments[%d] 缺少 dimension/feature" % index)
        segment_regex[segment_id] = _profile_entry_regex(raw, "segments[%d]" % index)
        segment_definitions.append(
            {
                "segment_id": segment_id,
                "rank": rank,
                "dimension": dimension,
                "feature": feature,
            }
        )
    segment_definitions.sort(key=lambda item: int(item["rank"]))

    raw_kano = document.get("kano_mapping")
    if not isinstance(raw_kano, Mapping):
        raise LocalReprocessError("taxonomy profile kano_mapping 必须是对象，可为空")
    kano_by_topic: Dict[str, str] = {}
    for raw_code, raw_value in raw_kano.items():
        code = str(raw_code)
        value = str(raw_value)
        if code not in topic_regex:
            raise LocalReprocessError("kano_mapping 引用了未知 topic：%s" % code)
        if value not in KANO_TYPES:
            raise LocalReprocessError("kano_mapping.%s 必须使用五类中文KANO" % code)
        kano_by_topic[code] = value

    return {
        "profile_id": profile_id,
        "source": "file",
        "profile_path": str(path),
        "profile_sha256": file_sha256(path),
        "product_label": product_label,
        "semantic_taxonomy": SEMANTIC_TAXONOMY,
        "semantic_regex": semantic_regex,
        "semantic_labels": SEMANTIC_LABELS,
        "product_regex": product_regex,
        "implicit_product_regex": implicit_product_regex,
        "implicit_experience_regex": implicit_experience_regex,
        "topic_regex": topic_regex,
        "topic_labels": topic_labels,
        "segment_regex": segment_regex,
        "segment_definitions": tuple(segment_definitions),
        "kano_by_topic": kano_by_topic,
        "required_scenarios": _string_list(document.get("required_scenarios", []), "required_scenarios"),
    }


def _builtin_category_is_explicit(
    task: Mapping[str, Any], selection: Mapping[str, Any]
) -> bool:
    source = selection.get("source") if isinstance(selection.get("source"), Mapping) else {}
    candidates = [
        str(task.get("topic") or ""),
        str(source.get("keyword") or ""),
        str(source.get("category_keyword") or ""),
        str(source.get("category_name") or ""),
    ]
    return any(_matches(normalize_text(value), _BUILTIN_CATEGORY_REGEX) for value in candidates)


def _open_readonly(path: Path) -> sqlite3.Connection:
    if not path.is_file():
        raise LocalReprocessError("source-db 不存在：%s" % path)
    connection = sqlite3.connect("file:%s?mode=ro" % path.resolve(), uri=True, timeout=30.0)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only=ON")
    required = {"tasks", "batches", "comments", "comment_discoveries"}
    tables = {
        str(row[0])
        for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    missing = sorted(required - tables)
    if missing:
        connection.close()
        raise LocalReprocessError("source-db 缺少数据表：%s" % ", ".join(missing))
    return connection


def _select_task(connection: sqlite3.Connection, task_id: Optional[str]) -> Mapping[str, Any]:
    if task_id:
        row = connection.execute("SELECT * FROM tasks WHERE task_id=?", (task_id,)).fetchone()
        if row is None:
            raise LocalReprocessError("source-db 中不存在 task-id：%s" % task_id)
        return dict(row)
    rows = connection.execute("SELECT * FROM tasks ORDER BY created_at,task_id").fetchall()
    if len(rows) != 1:
        raise LocalReprocessError("source-db 含有 %d 个任务，请显式传入 --task-id" % len(rows))
    return dict(rows[0])


def _load_selection(task: Mapping[str, Any], selection_file: Optional[Path]) -> Mapping[str, Any]:
    candidates: List[Path] = []
    if selection_file:
        candidates.append(selection_file)
    run_dir = str(task.get("run_dir") or "").strip()
    if run_dir:
        candidates.append(Path(run_dir) / "selected_segments.json")
    for candidate in candidates:
        if candidate.is_file():
            return _load_json(candidate)
    return {
        "schema_version": "unavailable",
        "source": {},
        "top3_selection": {},
        "selected_segments": [],
    }


def _load_single_segment_gap_fill(path: Optional[Path], segment_id: str) -> Mapping[str, Any]:
    """Accept only a documented two-round source-exhaustion downgrade record."""
    if path is None:
        return {}
    document = _load_json(path.expanduser().resolve())
    if document.get("schema_version") != "single-segment-gap-fill-1.0":
        raise LocalReprocessError("gap-fill 记录 schema_version 必须为 single-segment-gap-fill-1.0")
    if str(document.get("segment_id") or "") != segment_id:
        raise LocalReprocessError("gap-fill 记录的 segment_id 与本次选择不一致")
    rounds = document.get("rounds")
    if not isinstance(rounds, list) or len(rounds) < 1 or any(not isinstance(item, Mapping) for item in rounds):
        raise LocalReprocessError("来源耗尽降级至少需要两轮有记录的 gap-fill rounds")
    for index, item in enumerate(rounds, 1):
        if not str(item.get("query_or_source") or "").strip() or not str(item.get("result") or "").strip():
            raise LocalReprocessError("gap-fill 第 %d 轮必须记录查询/来源和结果" % index)
    status = str(document.get("status") or "")
    if status not in {"completed", "source_exhausted_after_two_gap_fill_rounds", "not_exhausted"}:
        raise LocalReprocessError("gap-fill status 无效")
    return {"status": status, "rounds": [dict(item) for item in rounds]}


def _discoveries(connection: sqlite3.Connection, task_id: str) -> Tuple[int, Dict[str, List[Dict[str, str]]]]:
    rows = connection.execute(
        """SELECT d.record_id,d.batch_id,d.scope,d.query_id,d.source,b.backend,b.query_text
        FROM comment_discoveries d JOIN batches b ON b.batch_id=d.batch_id
        WHERE d.task_id=? ORDER BY d.discovery_id""",
        (task_id,),
    ).fetchall()
    by_record: Dict[str, List[Dict[str, str]]] = defaultdict(list)
    seen: Dict[str, set[Tuple[str, str, str]]] = defaultdict(set)
    for row in rows:
        record_id = str(row["record_id"])
        marker = (str(row["scope"]), str(row["query_id"]), str(row["backend"]), str(row["batch_id"]))
        if marker in seen[record_id]:
            continue
        seen[record_id].add(marker)
        by_record[record_id].append(
            {
                "batch_id": str(row["batch_id"]),
                "scope_id": _map_all_history_string(str(row["scope"])),
                "query_id": _map_all_history_string(str(row["query_id"])),
                "backend": str(row["backend"]),
                "query_text": str(row["query_text"] or ""),
            }
        )
    return len(rows), by_record


def _project_context(task: Mapping[str, Any], selection: Mapping[str, Any]) -> Dict[str, Any]:
    source = selection.get("source") if isinstance(selection.get("source"), Mapping) else {}
    return {
        "project_root": str(task.get("project_dir") or "") or None,
        "marketplace": str(source.get("marketplace") or "") or None,
        "category_keyword": str(source.get("keyword") or task.get("topic") or "") or None,
        "category_node": str(source.get("category_node") or "") or None,
        "source_task_id": str(task.get("task_id") or ""),
    }


def _representative(voice: Mapping[str, Any]) -> Dict[str, Any]:
    return {
        "voice_id": voice["voice_id"],
        "platform": voice["platform"],
        "excerpt": voice["excerpt"],
        "published_at": voice.get("published_at"),
        "source_url": voice.get("source_url"),
        "semantic_codes": list(voice["semantic_codes"]),
        "topic_codes": list(voice["topic_codes"]),
    }


def _pick_representatives(voices: Sequence[Mapping[str, Any]], limit: int = 3) -> List[Dict[str, Any]]:
    def usefulness(item: Mapping[str, Any]) -> float:
        text = str(item.get("excerpt") or "")
        specific_topics = sum(
            1
            for code in item.get("topic_codes", [])
            if not str(code).startswith("general_")
        )
        semantic_depth = len(item.get("semantic_codes", []))
        return (
            specific_topics * 120
            + semantic_depth * 30
            + min(len(text), 700) / 3
            + min(_engagement_score(item), 40)
        )

    ordered = sorted(
        voices,
        key=lambda item: (
            usefulness(item),
            len(str(item.get("excerpt") or "")),
            str(item.get("voice_id") or ""),
        ),
        reverse=True,
    )
    selected: List[Mapping[str, Any]] = []
    platforms: set[str] = set()
    for voice in ordered:
        platform = str(voice.get("platform") or "unknown")
        if platform in platforms and len(selected) + len(platforms) < limit:
            continue
        selected.append(voice)
        platforms.add(platform)
        if len(selected) >= limit:
            break
    if len(selected) < limit:
        selected_ids = {str(item.get("voice_id")) for item in selected}
        selected.extend(
            voice for voice in ordered if str(voice.get("voice_id")) not in selected_ids
        )
    return [_representative(voice) for voice in selected[:limit]]


def _metric(label: str, code: str, voices: Sequence[Mapping[str, Any]], denominator: int) -> Dict[str, Any]:
    # The count intentionally uses hard-unique voices only. Similar opinions
    # and voices in the same discussion are retained; author visibility is
    # reported separately instead of being used for de-duplication.
    unique_voices = {
        str(item.get("voice_id") or item.get("hard_identity") or index): item
        for index, item in enumerate(voices)
    }
    metric_voices = list(unique_voices.values())
    authors = {str(item["author_key"]) for item in metric_voices if evidence.known_author(item.get("author_key"))}
    anonymous_voice_records = sum(
        1 for item in metric_voices if not evidence.known_author(item.get("author_key"))
    )
    threads = {str(item["thread_key"]) for item in metric_voices if evidence.context_key(item.get("thread_key"))}
    platforms = sorted({str(item["platform"]) for item in metric_voices})
    return {
        "code": code,
        "label": label,
        "count": len(metric_voices),
        "share": round(len(metric_voices) / denominator, 6) if denominator else 0.0,
        "authors": len(authors),
        "known_authors": len(authors),
        "anonymous_author_voice_records": anonymous_voice_records,
        "threads": len(threads),
        "platforms": platforms,
        "representative_voices": _pick_representatives(metric_voices),
    }


def _topic_metrics(
    voices: Sequence[Mapping[str, Any]],
    denominator: int,
    taxonomy: Optional[Mapping[str, Any]] = None,
) -> List[Dict[str, Any]]:
    current = _taxonomy(taxonomy)
    labels = current["topic_labels"]
    # Canonical codes are resolved before aggregation using explicit aliases.
    # Identical display labels never establish equivalence between needs.
    grouped: Dict[str, Dict[str, Mapping[str, Any]]] = defaultdict(dict)
    grouped_codes: Dict[str, set[str]] = defaultdict(set)
    for voice in voices:
        raw_labels = {
            str(code): str(label)
            for code, label in zip(voice.get("topic_codes", []), voice.get("topic_labels", []))
            if str(label).strip()
        }
        for code in voice["topic_codes"]:
            code = str(code)
            label = labels.get(code) or raw_labels.get(code)
            if not label:
                label = next(
                    (value[1] for value in GENERIC_TOPIC_BY_SEMANTIC.values() if value[0] == code),
                    code,
                )
            grouped[code][str(voice["voice_id"])] = voice
            grouped_codes[code].add(str(label))
    result = []
    for code, voice_map in grouped.items():
        label = sorted(grouped_codes[code])[0]
        result.append(_metric(label, code, list(voice_map.values()), denominator))
    return sorted(result, key=lambda item: (-int(item["count"]), str(item["label"])))


def _semantic_metrics(
    voices: Sequence[Mapping[str, Any]],
    denominator: int,
    taxonomy: Optional[Mapping[str, Any]] = None,
) -> List[Dict[str, Any]]:
    current = _taxonomy(taxonomy)
    result = []
    for item in current["semantic_taxonomy"]:
        code = str(item["code"])
        children = [voice for voice in voices if code in voice["semantic_codes"]]
        metric = _metric(str(item["label"]), code, children, denominator)
        metric["top_topics"] = [
            topic
            for topic in _topic_metrics(children, denominator, current)
            if not str(topic["code"]).startswith("general_")
        ][:10]
        result.append(metric)
    return result


def _category_summary(
    voices: Sequence[Mapping[str, Any]],
    denominator: int,
    taxonomy: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    mappings = {
        "needs": set(SEMANTIC_LABELS),
        "satisfactions": {"satisfaction_recommendation_repurchase"},
        "dissatisfactions": {"failure_complaint_return_alternative"},
        "scenarios": {"installation_compatibility_scenario"},
        "diy_workarounds": {"diy_modification_workaround"},
        "innovations": {"feature_reverse_innovation"},
    }
    result: Dict[str, Any] = {}
    for key, codes in mappings.items():
        children = [
            voice for voice in voices if set(voice["semantic_codes"]).intersection(codes)
        ]
        topics = _topic_metrics(children, denominator, taxonomy)
        # Generic fallback buckets are useful for audit, but they are not an
        # actionable Amazon operation/product-development point.
        topics = [item for item in topics if not str(item["code"]).startswith("general_")]
        result[key] = topics
    return result


def _segment_analysis(
    voices: Sequence[Mapping[str, Any]],
    segments: Sequence[Mapping[str, Any]],
    denominator: int,
    taxonomy: Optional[Mapping[str, Any]] = None,
) -> List[Dict[str, Any]]:
    result = []
    for segment in segments:
        segment_id = str(segment.get("segment_id") or "")
        children = [voice for voice in voices if segment_id in voice["segment_memberships"]]
        row = {key: value for key, value in segment.items() if key != "synonyms"}
        row.update(_metric(str(segment.get("feature") or segment_id), segment_id, children, denominator))
        row["semantic_categories"] = _semantic_metrics(children, len(children), taxonomy)
        row["top_topics"] = _topic_metrics(children, len(children), taxonomy)[:12]
        row.update(_category_summary(children, len(children), taxonomy))
        result.append(row)
    return result


def _kano(
    voices: Sequence[Mapping[str, Any]],
    denominator: int,
    taxonomy: Optional[Mapping[str, Any]] = None,
) -> List[Dict[str, Any]]:
    return _kano_results(voices, denominator)[0]


def _kano_results(voices, denominator):
    """One need, one plurality winner; unknowns never vote for a type.

    ``count/share`` retain their historical meaning: winning-type support over
    all valid VOC. ``related_*`` and ``dominant_share`` have explicit denominators.
    Legacy tags remain readable but are unreviewed under the current protocol.
    """
    grouped = defaultdict(dict)
    for voice in voices:
        for need in voice.get("needs", []):
            try:
                evidence.validate_kano_review(need, require_current=False)
            except evidence.EvidenceError as exc:
                raise LocalReprocessError(str(exc)) from exc
            identity = str(voice.get("hard_identity") or voice.get("voice_id") or "")
            if not identity:
                raise LocalReprocessError("KANO记录缺少稳定身份")
            code = str(need["code"])
            previous = grouped[code].get(identity)
            if previous and previous[1] != need:
                raise LocalReprocessError("同一底层记录的同一需求存在冲突编码：%s" % code)
            grouped[code][identity] = (voice, need)
    result, audit = [], []
    for code, unique in grouped.items():
        pairs = list(unique.values())
        by_type = {kind: [] for kind in sorted(KANO_TYPES)}
        states = Counter()
        for voice, need in pairs:
            current = (voice.get("coding_method") == "agent_reviewed"
                       and need.get("kano_review_version") == evidence.KANO_REVIEW_VERSION)
            state = need.get("kano_review_status", "unreviewed") if current else "unreviewed"
            if state not in evidence.KANO_REVIEW_STATES:
                raise LocalReprocessError("未知KANO复核状态")
            states[state] += 1
            if state == "classified":
                kind = need.get("kano_type")
                if kind not in KANO_TYPES or not need.get("kano_reason") or not need.get("quote"):
                    raise LocalReprocessError("KANO分类必须包含真实需求引文和解释")
                by_type[kind].append((voice, need))
        counts = {kind: len(rows) for kind, rows in by_type.items()}
        classified = sum(counts.values())
        best = max(counts.values())
        winners = [kind for kind, count in counts.items() if count == best] if best else []
        related = len(pairs)
        common = {"need_code": code, "need": str(pairs[0][1]["label"]),
                  "related_count": related, "related_share": round(related / denominator, 6) if denominator else 0.0,
                  "classified_count": classified, "type_counts": counts,
                  "review_counts": {state: states[state] for state in sorted(evidence.KANO_REVIEW_STATES)},
                  "review_version": evidence.KANO_REVIEW_VERSION,
                  "decision": "selected" if len(winners) == 1 else ("tie" if winners else "unclassified"),
                  "type_support_refs": {kind: [v["voice_id"] for v, _ in rows] for kind, rows in by_type.items()},
                  "formal_survey": False}
        audit.append(common)
        if len(winners) != 1:
            continue
        kano_type = winners[0]
        winning = by_type[kano_type]
        children = [voice for voice, _ in winning]
        metric = _metric(common["need"], code, children, denominator)
        reasons = list(dict.fromkeys(str(need["kano_reason"]) for _, need in winning))
        dominant_share = round(best / classified, 6)
        minority = sum(count for kind, count in counts.items() if kind != kano_type)
        rationale = "；".join(reasons[:3])
        if minority:
            rationale += "；其余%d条可分类声音持其他属性判断，保留场景差异。" % minority
        result.append({**common, "kano_type": kano_type,
                       **{key: value for key, value in metric.items() if key not in {"code", "label"}},
                       "dominant_share": dominant_share,
                       "support_refs": [voice["voice_id"] for voice in children],
                       "rationales": reasons, "rationale": rationale,
                       "method": "逐需求原文方向性归纳；每需求按可分类声音的相对多数保留一个类型，非正式KANO问卷"})
    order = lambda item: (-item["related_count"], item["need_code"])
    return sorted(result, key=order), sorted(audit, key=order)


def _new_needs(
    voices: Sequence[Mapping[str, Any]],
    denominator: int,
    taxonomy: Optional[Mapping[str, Any]] = None,
) -> List[Dict[str, Any]]:
    children = [
        voice
        for voice in voices
        if "feature_reverse_innovation" in voice["semantic_codes"]
        or "diy_modification_workaround" in voice["semantic_codes"]
    ]
    # topic_labels also contains later model-discovered needs; topic_regex stays
    # frozen to the profile's preset topics and is the correct scope boundary.
    preset_topics = set((taxonomy or {}).get("topic_regex", {}))
    candidate_codes = {str(n.get("need_id") or n["code"]) for v in children for n in v.get("needs", [])
                       if n.get("novel") is True and
                       (str(n.get("need_id") or n["code"]) not in preset_topics or n.get("opportunity_specific") is True)
                       # Stable broad needs may be cited inside an innovation
                       # comment, but their aggregate volume must never turn a
                       # narrow mechanism into a "new opportunity".
                       and (str(n.get("need_id") or n["code"]) not in _ESTABLISHED_IMPROVEMENT_FRAMING
                            or n.get("opportunity_specific") is True)}
    # Identify concrete needs from innovation records, then count those same IDs
    # over the entire effective set. Never merge by consumer-facing label.
    result = [n for n in evidence.need_metrics(voices, {})
              if n["need_id"] in candidate_codes and denominator and n["count"] * 200 >= denominator]
    for item in result:
        item["source_type"] = (
            "消费者明确创意或反向需求"
            if any(
                "feature_reverse_innovation" in voice["semantic_codes"]
                for voice in children
                if item["code"] in voice["topic_codes"]
            )
            else "DIY或绕行方案"
        )
        item["supply_validation"] = "待基于现有供给快照验证"
    return result


# These are deliberately a small, explicit mapping of the stable, broad
# demand IDs that can support *improvement* work.  They are not a synonym
# table for new needs and must never lend their aggregate counts to a narrow
# mechanism such as a fold-down desk or monitor-arm reinforcement.
_ESTABLISHED_IMPROVEMENT_FRAMING: Dict[str, Dict[str, str]] = {
    "small_space_fit": {
        "consumer_problem": "有限房间内，桌体占地、通道、桌下净空与可用工作面需要同时成立。",
        "current_workaround": "以更小桌面、临时桌或压缩椅子/通道空间换取可放置性。",
        "supply_gap": "不能由高频占地诉求直接推出某一种折叠、壁挂或收纳结构已被市场验证。",
        "product_response": "用可测量的占地、通道和桌下净空边界约束产品结构；具体机制由打样比较决定。",
        "next_test": "在卧室、宿舍和小单间的真实平面中测量进出、收椅与设备布置任务。",
    },
    "assembly_experience": {
        "consumer_problem": "首次装配、说明理解、部件定位和返工会影响购买后的可用性。",
        "current_workaround": "依赖额外工具、视频说明或拆装返工解决步骤和部件不确定性。",
        "supply_gap": "高频装配讨论不等于某个连接件或免工具方案已被验证为更优。",
        "product_response": "将定位、步骤校验和可复紧路径作为可测试的装配体验改进，而非直接承诺免工具。",
        "next_test": "首次装配用户与基准桌交叉测试错装、求助、返工和遗漏紧固。",
    },
    "stability_structure": {
        "consumer_problem": "桌体晃动、连接松动、承重和长期稳固性会限制紧凑办公桌的信任。",
        "current_workaround": "通过加固、复紧、减少设备负载或更换桌体来降低风险。",
        "supply_gap": "消费者反馈不能单独判定某一竞品的失效根因或证明某种支撑结构必然更稳。",
        "product_response": "把载荷路径、连接可达性和复紧恢复设计为工程假设，进行同包络对比。",
        "next_test": "开展侧推、偏载、循环与复紧恢复台架测试，再进入用户任务。",
    },
    "work_surface_capacity": {
        "consumer_problem": "笔记本、显示器、键鼠和纸面任务同时使用时，紧凑桌面容易失去有效操作区。",
        "current_workaround": "增加支架、夹具、外接托盘或牺牲设备布局来腾出桌面。",
        "supply_gap": "设备容纳需求不能直接证明所有夹具、双屏或深桌方案适配本细分。",
        "product_response": "以限定设备配置和可用操作面为约束，验证桌深、后缘和局部加强方案。",
        "next_test": "在同一墙距和设备组合下，比较操作面、视距、夹具干涉及维护任务。",
    },
    "materials_shipping_damage": {
        "consumer_problem": "板材质感、边角保护、运输损伤和耐久感会影响到货后的价值判断。",
        "current_workaround": "用户通过补漆、换件、退货或降低预期处理到货损伤。",
        "supply_gap": "现有反馈不能证明单一材料或包装方案足以解决所有损伤原因。",
        "product_response": "将易损边、连接区和包装支撑设为材料及运输验证重点。",
        "next_test": "对候选材料、边角和包装进行运输模拟、开箱检查与耐久评估。",
    },
    "value_price": {
        "consumer_problem": "消费者会比较价格、尺寸、材料、稳定和附加配置是否匹配。",
        "current_workaround": "以DIY、二手、临时桌或删减功能降低一次性支出。",
        "supply_gap": "价格讨论不等于市场接受任何新增结构成本或溢价。",
        "product_response": "将功能分层和BOM假设与同配置对标，而不是把功能堆叠写成价值。",
        "next_test": "在明确规格、运费和配置边界后进行价格敏感度与取舍测试。",
    },
    "storage_cable_power": {
        "consumer_problem": "收纳、理线和供电模块若侵占腿部或维护空间，会降低紧凑桌的日常可用性。",
        "current_workaround": "使用外接托盘、粘贴夹、侧袋或临时收纳配件。",
        "supply_gap": "配件讨论不能直接证明内置收纳、线槽或供电模块适用于所有设备和桌板。",
        "product_response": "设计可接近、可维护且不占用关键净空的模块接口，并限定兼容条件。",
        "next_test": "测量夹装、抽取维护、膝部净空、线缆弯折和电源安全边界。",
    },
    "ergonomic_height": {
        "consumer_problem": "桌高、坐姿、腿部位置与屏幕/输入设备布局会影响长时间使用舒适度。",
        "current_workaround": "以坐垫、显示器支架、临时升高或更换椅子来补偿高度不匹配。",
        "supply_gap": "人体工学讨论不能替代不同身高、椅型和任务下的实际测试。",
        "product_response": "明确固定高度或调节范围的适用边界，并把座椅和设备包络纳入设计。",
        "next_test": "按目标用户身高区间测试坐姿、腿部净空、视距和输入面高度。",
    },
}


def _opportunity_tracks(
    voices: Sequence[Mapping[str, Any]],
    denominator: int,
    taxonomy: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Return separate concrete-new and established-improvement tracks.

    The concrete track preserves the strict PRD v2 rule.  The improvement
    track makes high-frequency, already-established needs visible without
    calling them whitespace or a newly discovered mechanism.
    """
    specific = _new_needs(voices, denominator, taxonomy)
    metrics = evidence.need_metrics(voices, {})
    by_id = {str(item.get("need_id") or item.get("code")): item for item in metrics}
    improvements: List[Dict[str, Any]] = []
    for need_id, framing in _ESTABLISHED_IMPROVEMENT_FRAMING.items():
        metric = by_id.get(need_id)
        if not metric or not denominator or metric["count"] * 200 < denominator:
            continue
        # A formal improvement must still have consumer support and current
        # segment applicability.  Unknown is not silently promoted to current.
        if not metric.get("eligible"):
            continue
        improvements.append({
            **metric,
            "opportunity_track": "established_need_improvement",
            "type_label": "既有需求的改进机会",
            "source_type": "已确认的当前细分需求；不代表市场空白",
            **framing,
        })
    return {
        "schema_version": "consumer-opportunity-tracks-2.1",
        "denominator": denominator,
        "specific_new_needs": specific,
        "established_need_improvements": improvements,
        "audit": {
            "review_scope": "全部有效VOC按稳定need_id重算；具体新机制严格沿用创新/绕行且novel=true的候选边界",
            "specific_threshold": 0.005,
            "improvement_threshold": 0.005,
            "specific_candidate_count": len(specific),
            "improvement_candidate_count": len(improvements),
            "all_records_processed": True,
            "semantic_deduplication_applied": False,
        },
    }


def _sample_structure(voices: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    denominator = len(voices)
    platform_counts = Counter(str(voice["platform"]) for voice in voices)
    year_counts: Counter[str] = Counter()
    video_counts: Counter[str] = Counter()
    thread_counts: Counter[str] = Counter()
    for voice in voices:
        published = str(voice.get("published_at") or "")
        year_match = re.match(r"^(\d{4})-", published)
        year_counts[year_match.group(1) if year_match else "未知"] += 1
        if voice.get("video_id"):
            video_counts[str(voice["video_id"])] += 1
        if evidence.context_key(voice.get("thread_key")):
            thread_counts[str(voice["thread_key"])] += 1
    largest_video_id, largest_video_count = (video_counts.most_common(1) or [(None, 0)])[0]
    _, largest_thread_count = (thread_counts.most_common(1) or [(None, 0)])[0]
    return {
        "platform_distribution": [
            {
                "platform": platform,
                "count": count,
                "share": round(count / denominator, 6) if denominator else 0.0,
            }
            for platform, count in sorted(
                platform_counts.items(), key=lambda item: (-item[1], item[0])
            )
        ],
        "year_distribution": [
            {
                "year": year,
                "count": count,
                "share": round(count / denominator, 6) if denominator else 0.0,
            }
            for year, count in sorted(
                year_counts.items(),
                key=lambda item: (item[0] == "未知", item[0]),
            )
        ],
        "largest_single_video_id": largest_video_id,
        "largest_single_video_count": largest_video_count,
        "largest_single_video_share": round(largest_video_count / denominator, 6)
        if denominator
        else 0.0,
        "largest_thread_count": largest_thread_count,
        "largest_thread_share": round(largest_thread_count / denominator, 6)
        if denominator
        else 0.0,
        "unique_authors": len({str(voice["author_key"]) for voice in voices if evidence.known_author(voice.get("author_key"))}),
        "unknown_author_records": sum(not evidence.known_author(voice.get("author_key")) for voice in voices),
        "unique_threads": len({str(voice["thread_key"]) for voice in voices if evidence.context_key(voice.get("thread_key"))}),
    }


def _map_all_history_string(value: str) -> str:
    result = value
    replacements = {
        "segment_1_90d": "segment_1_all_history",
        "segment_2_90d": "segment_2_all_history",
        "segment_3_90d": "segment_3_all_history",
        "category_recent_30d": "category_all_history",
        "category_30d": "category_all_history",
        "segment_90d": "segment_all_history",
        "完整90天": "本地全历史",
        "最近30天": "本地全历史",
        "90天": "全历史",
        "30天": "全历史",
        "evidence_insufficient": "待问卷验证",
        "证据不足": "待补充验证",
    }
    for old, new in replacements.items():
        result = result.replace(old, new)
    result = re.sub(
        r"\bcategory(?:_[a-z0-9]+)*_(?:30d|90d)\b",
        "category_all_history",
        result,
        flags=re.IGNORECASE,
    )
    result = re.sub(
        r"\b(segment(?:_[a-z0-9]+)*?)_(?:recent_)?(?:30d|90d)\b",
        lambda match: match.group(1) + "_all_history",
        result,
        flags=re.IGNORECASE,
    )
    return result


def _clean_prior_value(value: Any) -> Any:
    """Remove internal evidence plumbing while preserving product-development detail."""
    if isinstance(value, Mapping):
        result: Dict[str, Any] = {}
        for key, child in value.items():
            lowered = str(key).casefold()
            if (
                _FORBIDDEN_KEY_REGEX.search(lowered)
                or _OLD_SCOPE_REGEX.search(lowered)
                or lowered in {
                    "voice_ids",
                    "evidence_voice_ids",
                    "evidence_ids",
                    "evidence_counts",
                    "source_status",
                    "source_runs",
                    "backend_status",
                    "agent_reach_health",
                    "raw_artifact",
                    "query_ids",
                }
            ):
                continue
            result[str(key)] = _clean_prior_value(child)
        return result
    if isinstance(value, list):
        return [_clean_prior_value(child) for child in value]
    if isinstance(value, str):
        return _map_all_history_string(value)
    return value


def _prior_kano_mapping(
    rows: Any, current_kano: Sequence[Mapping[str, Any]]
) -> List[Dict[str, Any]]:
    if not isinstance(rows, list):
        return []
    current = {str(item["need_code"]): item for item in current_kano}
    aliases = {
        "secure_hold": "stability_security",
        "vibration_resistance": "stability_security",
        "button_clearance": "phone_case_compatibility",
        "phone_case_compatibility": "phone_case_compatibility",
        "quick_access": "one_hand_quick_release",
        "one_hand_operation": "one_hand_quick_release",
        "non_obstruction": "driving_safety",
        "visibility": "adjustability_visibility",
        "surface_adhesion": "adhesive_heat",
        "heat_resistance": "adhesive_heat",
        "wireless_charging": "charging",
        "charging": "charging",
        "truck_vibration": "truck_heavy_duty",
        "tesla_integration": "tesla_integration",
        "tracking": "tracking_anti_theft",
    }
    result: List[Dict[str, Any]] = []
    seen = set()
    for raw in rows:
        if not isinstance(raw, Mapping):
            continue
        old_need = str(raw.get("need_code") or "")
        mapped_need = aliases.get(old_need, old_need)
        current_row = current.get(mapped_need)
        if not current_row or mapped_need in seen:
            continue
        classification = str(current_row.get("kano_type") or "")
        if classification not in KANO_TYPES:
            continue
        # Current evidence replaces historical labels, counts and explanations.
        # Ties/unknowns have no winner and cannot resurrect an old classification.
        result.append({
            "need_code": mapped_need,
            "need": current_row["need"],
            "classification": classification,
            "design_response": str(current_row.get("rationale") or
                "按当前已复核消费者表达归纳为%s；仍需正式KANO问卷验证。" % classification),
        })
        seen.add(mapped_need)
    return result


def _reuse_prior_analysis(
    prior: Mapping[str, Any],
    top_segments: Sequence[Mapping[str, Any]],
    current_kano: Sequence[Mapping[str, Any]],
) -> Mapping[str, Any]:
    prior_concepts = prior.get("product_concepts")
    if not isinstance(prior_concepts, list) or not prior_concepts:
        return {}
    segments = {str(item.get("segment_id") or ""): item for item in top_segments}
    concepts: List[Dict[str, Any]] = []
    for raw in prior_concepts[:3]:
        if not isinstance(raw, Mapping):
            continue
        cleaned = _clean_prior_value(raw)
        if not isinstance(cleaned, Mapping):
            continue
        concept = dict(cleaned)
        segment_id = str(concept.get("segment_id") or "")
        segment = segments.get(segment_id, {})
        concept.pop("supporting_voice_count", None)
        concept.pop("supporting_topic_codes", None)
        concept["kano_mapping"] = _prior_kano_mapping(
            concept.get("kano_mapping"), current_kano
        )
        concepts.append(concept)
    result: Dict[str, Any] = {"product_concepts": concepts}
    if prior.get("validation") is not None:
        result["prior_product_validation"] = _clean_prior_value(prior["validation"])
    if prior.get("future_validation_checklist") is not None:
        result["future_validation_checklist"] = _clean_prior_value(
            prior["future_validation_checklist"]
        )
    return result


def _atomic_json(path: Path, document: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if os.name != "nt":
        os.chmod(path.parent, 0o700)
    descriptor, temporary_name = tempfile.mkstemp(prefix=".%s." % path.name, dir=str(path.parent))
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(document, handle, ensure_ascii=False, separators=(",", ":"))
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        if os.name != "nt":
            os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _validate_clean_structure(value: Any, path: str = "$") -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            key_text = str(key)
            child_path = "%s.%s" % (path, key_text)
            if _FORBIDDEN_KEY_REGEX.search(key_text) or _OLD_SCOPE_REGEX.search(key_text):
                raise LocalReprocessError("v3 输出包含禁用结构键：%s" % child_path)
            _validate_clean_structure(child, child_path)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _validate_clean_structure(child, "%s[%d]" % (path, index))
    elif isinstance(value, str) and _OLD_SCOPE_REGEX.search(value):
        raise LocalReprocessError("v3 输出仍包含旧 scope：%s" % path)


def _validate_kano_values(value: Any, path: str = "$") -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            child_path = "%s.%s" % (path, key)
            lowered_path = child_path.casefold()
            if str(key) in {"kano_type", "classification"} and "kano" in lowered_path:
                if child is not None and str(child) not in KANO_TYPES | {"M", "O", "A", "I", "R"}:
                    raise LocalReprocessError(
                        "v3 KANO 只能使用五类中文：%s=%s" % (child_path, child)
                    )
            _validate_kano_values(child, child_path)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _validate_kano_values(child, "%s[%d]" % (path, index))


def validate_v3_documents(
    coding: Mapping[str, Any], analysis: Mapping[str, Any]
) -> None:
    """Strict deterministic reconciliation before either v3 document is written."""
    _validate_clean_structure(coding, "$coding")
    _validate_clean_structure(analysis, "$analysis")
    _validate_kano_values(analysis, "$analysis")
    if coding.get("schema_version") != SCHEMA_VERSION or analysis.get("schema_version") != SCHEMA_VERSION:
        raise LocalReprocessError("v3 schema_version 不一致")
    coding_metadata = coding.get("metadata")
    analysis_metadata = analysis.get("metadata")
    if not isinstance(coding_metadata, Mapping) or analysis_metadata != coding_metadata:
        raise LocalReprocessError("coding/analysis metadata 不一致")
    if (
        coding_metadata.get("mode") != MODE
        or coding_metadata.get("no_network") is not True
        or coding_metadata.get("date_filter_applied") is not False
        or not re.fullmatch(r"[0-9a-f]{64}", str(coding_metadata.get("source_db_sha256") or ""))
    ):
        raise LocalReprocessError("v3 metadata 模式、联网或源快照字段无效")

    expected_taxonomy = [
        {"code": code, "label": SEMANTIC_LABELS[code]} for code in SEMANTIC_CODES
    ]
    if coding.get("semantic_taxonomy") != expected_taxonomy:
        raise LocalReprocessError("v3 六语义 taxonomy 必须恰好为固定六类且顺序一致")

    funnel = coding.get("funnel")
    analysis_funnel = analysis.get("funnel")
    if not isinstance(funnel, Mapping) or analysis_funnel != funnel:
        raise LocalReprocessError("coding/analysis 漏斗不一致")
    try:
        hard_unique = int(funnel["hard_unique_records"])
        examined = int(funnel["examined_records"])
        qualified = int(funnel["qualified_consumer_voices"])
        excluded_count = int(funnel["excluded_records"])
        pending_count = int(funnel.get("pending_records", 0))
    except (KeyError, TypeError, ValueError) as exc:
        raise LocalReprocessError("v3 漏斗字段缺失或类型无效") from exc
    if examined != hard_unique or hard_unique != qualified + excluded_count + pending_count:
        raise LocalReprocessError(
            "v3 漏斗必须满足 examined=hard_unique=qualified+excluded+pending"
        )

    voices = coding.get("voices")
    excluded = coding.get("excluded_records")
    pending_rows = coding.get("pending_records", [])
    if not isinstance(pending_rows, list) or len(pending_rows) != pending_count:
        raise LocalReprocessError("pending_records 与漏斗不一致")
    if not isinstance(voices, list) or not isinstance(excluded, list):
        raise LocalReprocessError("v3 voices/excluded_records 必须为数组")
    if len(voices) != qualified or len(excluded) != excluded_count:
        raise LocalReprocessError("v3 漏斗数量与逐条记录数量不一致")

    voice_record_ids: set[str] = set()
    excluded_record_ids: set[str] = set()
    voice_hard_ids: set[str] = set()
    excluded_hard_ids: set[str] = set()
    expected_code_set = set(SEMANTIC_CODES)
    for index, raw in enumerate(voices):
        if not isinstance(raw, Mapping):
            raise LocalReprocessError("voices[%d] 必须是对象" % index)
        voice_id = str(raw.get("voice_id") or "")
        hard_identity = str(raw.get("hard_identity") or "")
        codes = raw.get("semantic_codes")
        if not voice_id or not hard_identity:
            raise LocalReprocessError("voices[%d] 缺少身份" % index)
        if voice_id in voice_record_ids or hard_identity in voice_hard_ids:
            raise LocalReprocessError("voices 内部身份重复：%s" % voice_id)
        if not isinstance(codes, list) or not codes or len(codes) != len(set(map(str, codes))):
            raise LocalReprocessError("voices[%d].semantic_codes 必须非空且唯一" % index)
        if not set(map(str, codes)).issubset(expected_code_set):
            raise LocalReprocessError("voices[%d] 含六类之外的语义代码" % index)
        voice_record_ids.add(voice_id)
        voice_hard_ids.add(hard_identity)
    for index, raw in enumerate(excluded):
        if not isinstance(raw, Mapping):
            raise LocalReprocessError("excluded_records[%d] 必须是对象" % index)
        record_id = str(raw.get("record_id") or "")
        hard_identity = str(raw.get("hard_identity") or "")
        if not record_id or not hard_identity:
            raise LocalReprocessError("excluded_records[%d] 缺少身份" % index)
        if record_id in excluded_record_ids or hard_identity in excluded_hard_ids:
            raise LocalReprocessError("excluded_records 内部身份重复：%s" % record_id)
        excluded_record_ids.add(record_id)
        excluded_hard_ids.add(hard_identity)
    pending_ids: set[str] = set()
    pending_hard_ids: set[str] = set()
    for item in pending_rows:
        if not isinstance(item, Mapping) or not item.get("record_id") or not item.get("hard_identity"):
            raise LocalReprocessError("待复核记录缺少身份")
        rid, hid = str(item["record_id"]), str(item["hard_identity"])
        if rid in pending_ids or hid in pending_hard_ids:
            raise LocalReprocessError("待复核记录身份重复")
        pending_ids.add(rid)
        pending_hard_ids.add(hid)
    groups = [voice_record_ids, excluded_record_ids, pending_ids]
    hard_groups = [voice_hard_ids, excluded_hard_ids, pending_hard_ids]
    if any(groups[i] & groups[j] or hard_groups[i] & hard_groups[j] for i in range(3) for j in range(i + 1, 3)):
        raise LocalReprocessError("纳入、排除、待复核记录必须互斥")
    if len(set.union(*groups)) != hard_unique or len(set.union(*hard_groups)) != hard_unique:
        raise LocalReprocessError("纳入、排除、待复核记录未完整覆盖硬身份记录")

    semantic_categories = analysis.get("semantic_categories")
    if not isinstance(semantic_categories, list) or len(semantic_categories) != 6:
        raise LocalReprocessError("analysis.semantic_categories 必须恰好六项")
    actual_codes = [
        str(item.get("code") or "") if isinstance(item, Mapping) else ""
        for item in semantic_categories
    ]
    if actual_codes != list(SEMANTIC_CODES):
        raise LocalReprocessError("analysis 六语义代码必须恰好固定六类且顺序一致")
    for item in semantic_categories:
        code = str(item["code"])
        if str(item.get("label") or "") != SEMANTIC_LABELS[code]:
            raise LocalReprocessError("analysis 六语义 label 与固定 taxonomy 不一致：%s" % code)
        recomputed_count = sum(1 for voice in voices if code in voice["semantic_codes"])
        recomputed_share = round(recomputed_count / qualified, 6) if qualified else 0.0
        if int(item.get("count", -1)) != recomputed_count:
            raise LocalReprocessError("analysis 六语义 count 无法从 coding 复算：%s" % code)
        try:
            share = float(item.get("share"))
        except (TypeError, ValueError) as exc:
            raise LocalReprocessError("analysis 六语义 share 类型无效：%s" % code) from exc
        if abs(share - recomputed_share) > 0.0000005:
            raise LocalReprocessError("analysis 六语义 share 无法从 coding 复算：%s" % code)

    concepts = analysis.get("product_concepts")
    if not isinstance(concepts, list) or len(concepts) > 3:
        raise LocalReprocessError("正式产品方向必须为 0–3 个")
    readiness = analysis.get("evidence_readiness")
    if readiness is not None:
        if not isinstance(readiness, Mapping) or readiness.get("status") not in {"partial", "sufficient"}:
            raise LocalReprocessError("evidence_readiness 状态无效")
        checks = readiness.get("checks")
        if not isinstance(checks, list) or not checks or any(not isinstance(x, Mapping) or not isinstance(x.get("passed"), bool) for x in checks):
            raise LocalReprocessError("证据充分性检查缺失")
        blocking_checks = [x for x in checks if x.get("blocking", True)] if analysis.get("business_rules_version") in {"voc-prd-v2", "voc-prd-v2.1", "voc-prd-v2.2", "voc-prd-v2.3"} else checks
        if (readiness["status"] == "sufficient") != all(x["passed"] for x in blocking_checks):
            raise LocalReprocessError("证据充分性状态与检查矛盾")
    if coding_metadata.get("evidence_protocol") == "1.0.0":
        reviewed = sum(item.get("coding_method") in evidence.ACCEPTED_CODING_METHODS for item in [*voices, *excluded, *coding.get("pending_records", [])])
        unreviewed = hard_unique - reviewed
        legacy_reviewed = sum(item.get("coding_method") == "agent_reviewed" for item in [*voices, *excluded, *coding.get("pending_records", [])])
        expected_review = {"agent_reviewed": legacy_reviewed, "rule_provisional": sum(v.get("coding_method") == "rule_provisional" for v in voices), "pending": pending_count,
                           "unreviewed_records": unreviewed, "coverage": round(reviewed / hard_unique, 6) if hard_unique else 0.0}
        review = coding.get("coding_review")
        if not isinstance(review, Mapping) or any(review.get(k) != v for k, v in expected_review.items()) or analysis.get("coding_review") != review:
            raise LocalReprocessError("编码复核进度不能从逐条记录复算")
        for voice in voices:
            if voice.get("text_sha256") != evidence.text_digest(str(voice.get("full_text") or voice["excerpt"])):
                raise LocalReprocessError("原文摘要与逐条文本不一致")
            if voice.get("coding_method") not in evidence.ACCEPTED_CODING_METHODS | {"rule_provisional"}:
                raise LocalReprocessError("编码方法无效")
            if voice.get("coding_method") in evidence.ACCEPTED_CODING_METHODS:
                for need in voice["needs"]:
                    if not str(need.get("quote") or "") or str(need["quote"]) not in str(voice.get("full_text") or voice["excerpt"]):
                        raise LocalReprocessError("已复核需求引文不在原文中")
                    try:
                        evidence.validate_kano_review(need, require_current=False)
                    except evidence.EvidenceError as exc:
                        raise LocalReprocessError(str(exc)) from exc
        if not isinstance(readiness, Mapping):
            raise LocalReprocessError("新版分析缺少证据充分性对象")
        if coding_metadata.get("workflow_mode") == "single_segment":
            single_social = readiness.get("single_segment_social")
            if not isinstance(single_social, Mapping):
                raise LocalReprocessError("单细分分析缺少社媒充分性对象")
            segments = coding.get("segments", [])
            if not isinstance(segments, list) or len(segments) != 1 or not isinstance(segments[0], Mapping):
                raise LocalReprocessError("单细分编码必须恰有一个细分")
            policy = single_social.get("policy")
            if not isinstance(policy, Mapping):
                raise LocalReprocessError("单细分社媒政策缺失")
            rebuilt = evidence.evaluate_single_segment(
                voices,
                segments[0],
                coding_metadata.get("collection_batch_order", []),
                review,
                social_policy=policy,
                data_exhaustion=single_social.get("data_exhaustion"),
                thresholds=readiness.get("thresholds"),
                required_scenarios=coding_metadata.get("required_scenarios", []),
                batch_statuses=coding_metadata.get("collection_batch_results", {}),
            )
        else:
            rebuilt = evidence.evaluate(voices, coding.get("segments", []), coding_metadata.get("collection_batch_order", []), review,
                                        thresholds=readiness.get("thresholds"), required_scenarios=coding_metadata.get("required_scenarios", []), batch_statuses=coding_metadata.get("collection_batch_results", {}))
        if readiness != rebuilt:
            raise LocalReprocessError("证据充分性无法从逐条编码与源批次复算")

    kano = analysis.get("kano")
    if not isinstance(kano, list):
        raise LocalReprocessError("analysis.kano 必须为数组")
    if analysis.get("methodology", {}).get("kano_mode") == "need_holistic_inference":
        expected = {n["code"]: n["count"] for n in readiness.get("needs", [])}
        if len(kano) != len(expected) or {n.get("need_id") or n.get("code") for n in kano} != set(expected):
            raise LocalReprocessError("综合KANO需求集合不完整")
        for item in kano:
            status = item.get("status")
            if status not in {"pending", "classified", "insufficient", "conflict", "not_applicable", "below_threshold"}:
                raise LocalReprocessError("综合KANO处理状态无效")
            if item.get("count") != expected[item.get("need_id") or item["code"]]:
                raise LocalReprocessError("综合KANO需求统计被改写")
            if analysis.get("business_rules_version") in {"voc-prd-v2", "voc-prd-v2.1", "voc-prd-v2.2", "voc-prd-v2.3"}:
                below = qualified == 0 or item["count"] * 100 < qualified * 3
                if (status == "below_threshold") != below:
                    raise LocalReprocessError("KANO 3%筛选状态与未舍入统计不一致")
                if item.get("denominator") != qualified or not item.get("source_sha256"):
                    raise LocalReprocessError("KANO缺少当前分母或证据指纹")
            if status == "classified" and item.get("classification") not in {"M", "O", "A", "I", "R"}:
                raise LocalReprocessError("综合KANO分类无效")
            if status != "classified" and item.get("classification") is not None:
                raise LocalReprocessError("未分类KANO不能提供类型")
            if status != "pending" and not item.get("rationale"):
                raise LocalReprocessError("已处理KANO必须说明依据")
        return
    for index, item in enumerate(kano):
        if not isinstance(item, Mapping) or str(item.get("kano_type")) not in KANO_TYPES:
            raise LocalReprocessError("analysis.kano[%d] 不是五类中文KANO" % index)
    if "kano_audit" in analysis:
        rebuilt_kano, rebuilt_audit = _kano_results(voices, qualified)
        if kano != rebuilt_kano or analysis["kano_audit"] != rebuilt_audit:
            raise LocalReprocessError("KANO数量、分类占比或审计结果无法从逐条编码复算")


def _contains_forbidden_grading_key(value: Any) -> bool:
    """Compatibility helper retained for callers; v3 uses strict validation."""
    try:
        _validate_clean_structure(value)
    except LocalReprocessError:
        return True
    return False


def _review_context(row: Mapping[str, Any], context: Mapping[str, Any]) -> List[Dict[str, str]]:
    source = _source_namespace(row)
    ids = [str(row.get("parent_content_id") or ""), str(row.get("thread_id") or row.get("video_id") or "")]
    saved: Dict[str, Dict[str, str]] = {}
    for content_id in ids:
        seen: set[str] = set()
        for _ in range(8):
            record_id = context["content_index"].get((source, content_id))
            if not record_id or record_id in seen or record_id == row["record_id"]:
                break
            seen.add(record_id)
            info = context["infos"][record_id]
            saved[record_id] = {"record_id": record_id, "text": info["text"]}
            content_id = str(info["row"].get("parent_content_id") or "")
    raw = _safe_json(row.get("raw_json"))
    for key in ("product_title", "thread_title", "video_title", "parent_text"):
        value = str(raw.get(key) or "").strip()
        if value:
            rid = str(row["record_id"]) + ":" + key
            saved[rid] = {"record_id": rid, "text": normalize_text(value)}
    return [saved[key] for key in sorted(saved)]


def _atomic_jsonl(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=".%s." % path.name, dir=str(path.parent))
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def reprocess(
    source_db: Path,
    output_dir: Path,
    *,
    task_id: Optional[str] = None,
    selection_file: Optional[Path] = None,
    prior_analysis: Optional[Path] = None,
    taxonomy_profile: Optional[Path] = None,
    dashboard: Optional[Path] = None,
    agent_coding: Sequence[Path] = (),
    coding_cache: Optional[Path] = None,
    export_coding_queue: Optional[Path] = None,
    evidence_thresholds: Optional[Mapping[str, Any]] = None,
    collection_receipt: Optional[Path] = None,
    single_segment_gap_fill: Optional[Path] = None,
    rule_config: Optional[Path] = None,
    quality_review: Optional[Path] = None,
    dry_run: bool = False,
) -> Mapping[str, Any]:
    source_db = source_db.expanduser().resolve()
    rules = _load_json(rule_config) if rule_config else {}
    quality = _load_json(quality_review) if quality_review else {}
    output_dir = output_dir.expanduser().resolve()
    source_stat = source_db.stat()
    source_hash_before = file_sha256(source_db)
    dashboard_path: Optional[Path] = None
    dashboard_stat = None
    dashboard_hash_before: Optional[str] = None
    if dashboard is not None:
        dashboard_path = dashboard.expanduser().resolve()
        dashboard_stat = dashboard_path.stat()
        dashboard_hash_before = file_sha256(dashboard_path)
    protected_paths = {source_db, *[p.expanduser().resolve() for p in (dashboard, selection_file, taxonomy_profile, prior_analysis, collection_receipt, single_segment_gap_fill, rule_config, quality_review) if p], *[p.expanduser().resolve() for p in agent_coding]}
    output_paths = [output_dir / name for name in (CODING_FILENAME, ANALYSIS_FILENAME, RECEIPT_FILENAME, SOURCE_SNAPSHOT_FILENAME)]
    output_paths.append(output_dir / "kano_review_queue.jsonl")
    output_paths.extend(output_dir / name for name in ("review_batches.json", "quality_review_queue.json"))
    output_paths += [export_coding_queue or (output_dir / "agent_coding_queue.jsonl")]
    if coding_cache:
        if coding_cache.expanduser().resolve() in protected_paths:
            raise LocalReprocessError("编码缓存输入不得与其他源输入重叠")
        protected_paths.add(coding_cache.expanduser().resolve())
        output_paths.append(output_dir / "coding_cache.json")
    resolved_outputs = [p.expanduser().resolve() for p in output_paths]
    if protected_paths.intersection(resolved_outputs) or len(resolved_outputs) != len(set(resolved_outputs)):
        raise LocalReprocessError("输出、队列和缓存路径不得重叠或覆盖原始输入")
    connection = _open_readonly(source_db)
    try:
        task = _select_task(connection, task_id)
        selected_task_id = str(task["task_id"])
        selection = _load_selection(task, selection_file)
        single_segment_mode = selection.get("workflow_mode") == "single_segment"
        if taxonomy_profile:
            current_taxonomy = _load_taxonomy_profile(taxonomy_profile)
        else:
            if not _builtin_category_is_explicit(task, selection):
                raise LocalReprocessError(
                    "未提供 --taxonomy-profile；内置默认仅允许明确识别为车载手机支架的项目"
                )
            current_taxonomy = dict(BUILTIN_TAXONOMY)
        current_taxonomy = {**current_taxonomy, "topic_labels": dict(current_taxonomy["topic_labels"])}
        prior_document: Optional[Mapping[str, Any]] = None
        if prior_analysis:
            prior_analysis = prior_analysis.expanduser().resolve()
            prior_document = _load_json(prior_analysis)
        # Taxonomy supplies expressions, never a replacement Top3 selection.
        segments = [_output_segment(item) for item in selection.get("selected_segments", []) if isinstance(item, Mapping)]
        if single_segment_mode and len(segments) != 1:
            raise LocalReprocessError("单细分流程必须且只能接收一个 selected_segments 项")
        if not single_segment_mode and (len(segments) > 3 or len({str(item.get("segment_id")) for item in segments}) != len(segments)):
            raise LocalReprocessError("selected_segments 必须是至多三个唯一细分")
        selected_by_id = {str(item.get("segment_id")): item for item in segments}
        single_segment_id = next(iter(selected_by_id), "")
        gap_fill_record = _load_single_segment_gap_fill(single_segment_gap_fill, single_segment_id) if single_segment_mode else {}
        profile_segments = current_taxonomy.get("segment_definitions") or []
        if single_segment_mode:
            # Built-in taxonomy carries the historical Top3 definitions.  A
            # user-selected segment need not be one of them: its relevance is
            # decided by the imported, record-level review rather than by
            # silently substituting a legacy segment.  A supplied project
            # taxonomy, on the other hand, must explicitly cover the selected
            # segment when it declares segment-level definitions.
            if current_taxonomy["source"] == "file":
                matching_profile_segments = [
                    item for item in profile_segments
                    if str(item.get("segment_id")) == single_segment_id
                ]
                if profile_segments and (
                    len(matching_profile_segments) != 1
                    or any(
                        str(matching_profile_segments[0].get(key))
                        != str(selected_by_id[single_segment_id].get(key))
                        for key in ("rank", "dimension", "feature")
                    )
                ):
                    raise LocalReprocessError("项目词典的细分必须与用户选定细分一致，不能替换研究范围")
                if single_segment_id not in current_taxonomy["segment_regex"]:
                    raise LocalReprocessError("项目词典必须覆盖用户选定的细分")
        else:
            for item in profile_segments:
                selected = selected_by_id.get(str(item.get("segment_id")))
                if not selected or any(str(item.get(key)) != str(selected.get(key)) for key in ("rank", "dimension", "feature")):
                    raise LocalReprocessError("taxonomy 的细分必须与上游 selected_segments 一致，不能覆盖Top3")
            if current_taxonomy["source"] == "file" and set(current_taxonomy["segment_regex"]) != set(selected_by_id):
                raise LocalReprocessError("项目词典必须覆盖上游选定的每个细分")
        current_taxonomy["segment_regex"] = {key: value for key, value in current_taxonomy["segment_regex"].items() if key in selected_by_id}
        discovered_count, discoveries = _discoveries(connection, selected_task_id)
        rows = connection.execute(
            "SELECT * FROM comments WHERE task_id=? ORDER BY first_seen_at,record_id",
            (selected_task_id,),
        ).fetchall()
        seen_hard_keys: set[str] = set()
        voices: List[Dict[str, Any]] = []
        excluded: List[Dict[str, Any]] = []
        hard_duplicate_count = 0
        unique_rows: List[Dict[str, Any]] = []
        for sqlite_row in rows:
            row = dict(sqlite_row)
            content_id = str(row.get("content_id") or "").strip()
            namespace = _source_namespace(row)
            hard_key = (namespace + ":content:" + content_id) if content_id else str(row.get("hard_key") or row.get("record_id") or "")
            if namespace.endswith(":unverified"):
                hard_key = "unverified:" + str(row["record_id"])
            if single_segment_mode and not content_id:
                direct_url = str(row.get("canonical_url") or "").strip()
                hard_key = (str(row.get("source") or "unknown").casefold() + ":url:" + direct_url) if direct_url else "unverified:" + str(row["record_id"])
            row["hard_key"] = hard_key
            if hard_key in seen_hard_keys:
                hard_duplicate_count += 1
                continue
            seen_hard_keys.add(hard_key)
            unique_rows.append(row)
        context = _product_context_index(unique_rows, discoveries, current_taxonomy)
        taxonomy_hash = str(current_taxonomy.get("profile_sha256") or evidence.digest({"profile_id": current_taxonomy["profile_id"], "semantic_patterns": SEMANTIC_TAXONOMY, "topics": TOPIC_DEFINITIONS}))
        if rules:
            taxonomy_hash = evidence.digest({"taxonomy": taxonomy_hash, "rules": rules})
        cache_document = _load_json(coding_cache) if coding_cache and coding_cache.is_file() else {}
        cache_rows = cache_document.get("entries", [])
        if not isinstance(cache_rows, list) or any(not isinstance(item, Mapping) or not item.get("cache_key") for item in cache_rows):
            raise LocalReprocessError("编码缓存 entries 必须是带 cache_key 的对象数组")
        cached_entries = {str(item["cache_key"]): item for item in cache_rows}
        if len(cached_entries) != len(cache_rows):
            raise LocalReprocessError("编码缓存不能含重复键")
        imported = evidence.load_entries(list(agent_coding))
        imported_entries: Dict[str, Mapping[str, Any]] = {}
        for entry in imported:
            key = str(entry.get("cache_key") or "")
            if key in imported_entries and imported_entries[key] != entry:
                raise LocalReprocessError("导入的同一条编码存在冲突")
            imported_entries[key] = entry
        used_imports: set[str] = set()
        reviewed_entries: List[Dict[str, Any]] = []
        review_queue: List[Dict[str, Any]] = []
        kano_review_queue: List[Dict[str, Any]] = []
        pending: List[Dict[str, Any]] = []
        batch_columns = {str(item[1]) for item in connection.execute("PRAGMA table_info(batches)")}
        batch_sort = "COALESCE(started_at,created_at),rowid" if {"started_at", "created_at"}.issubset(batch_columns) else "rowid"
        batch_rows = [dict(item) for item in connection.execute("SELECT * FROM batches WHERE task_id=? ORDER BY " + batch_sort, (selected_task_id,))]
        batch_order = [str(item["batch_id"]) for item in batch_rows]
        batch_statuses = {str(item["batch_id"]): str(item.get("status") or "legacy_unknown") for item in batch_rows}
        for row in unique_rows:
            hard_key = str(row.get("hard_key") or row.get("record_id") or "")
            record_id = str(row["record_id"])
            text = normalize_text(row.get("text"))
            routes = discoveries.get(record_id, [])
            info = context["infos"][record_id]
            text = str(info["text"])
            record_input = evidence.review_input(row, text, _review_context(row, context), taxonomy_hash)
            if single_segment_mode:
                record_input["identity_verified"] = not hard_key.startswith("unverified:")
            raw_decision = imported_entries.get(record_input["cache_key"]) or cached_entries.get(record_input["cache_key"])
            if not raw_decision and single_segment_mode:
                raw_decision = prd_pipeline.classify(record_input, rules, set(selected_by_id))
            raw_decision = prd_pipeline.canonicalize_decision(raw_decision, rules)
            if raw_decision and raw_decision.get("coding_method") == "model_reviewed":
                prd_pipeline.validate_long_review(record_input, raw_decision)
            decision = evidence.validate_entry(raw_decision, record_input, SEMANTIC_CODES, {str(x["segment_id"]) for x in segments}) if raw_decision else None
            if decision:
                reviewed_entries.append(decision)
                if record_input["cache_key"] in imported_entries:
                    used_imports.add(record_input["cache_key"])
            else:
                review_queue.append({**record_input, "rule_suggestions": {"semantic_codes": list(info["semantics"]), "topic_codes": topic_codes(text, info["semantics"], current_taxonomy), "segment_memberships": segment_codes(text, current_taxonomy)}, "audit_sample": int(record_input["cache_key"][:8], 16) % 20 == 0, "decision": None})
            semantics = list(decision["semantic_codes"]) if decision and decision["decision"] == "include" else list(info["semantics"])
            reason: Optional[str] = None
            context_source: Optional[str] = None
            inclusion_reason: Optional[str] = None
            context_audit: Optional[Mapping[str, Any]] = None
            if decision:
                if decision["decision"] == "undetermined":
                    pending.append({"record_id": record_id, "hard_identity": hard_key,
                        "platform": str(row.get("source") or "unknown"), "source_kind": evidence.source_kind(row),
                        "reason": decision["reason"], "excerpt": text, "published_at": row.get("published_at"),
                        "decision": "undetermined", "processing_status": "completed", "coding_method": decision["coding_method"],
                        "text_sha256": record_input["text_sha256"], "cache_key": record_input["cache_key"]})
                    continue
                if decision["decision"] == "exclude":
                    reason = decision["reason"]
                else:
                    context_source = ("Python规则判定：" if decision["coding_method"] == "rule_classified" else "模型逐条复核：") + decision["product_context"]["basis"]
                    inclusion_reason = decision["reason"]
            elif single_segment_mode:
                pending.append({"record_id": record_id, "hard_identity": hard_key,
                    "platform": str(row.get("source") or "unknown"), "source_kind": evidence.source_kind(row),
                    "reason": "规则未覆盖、冲突或缺少可靠产品上下文，等待小批复核", "excerpt": text,
                    "decision": "pending", "processing_status": "planned", "published_at": row.get("published_at"),
                    "text_sha256": record_input["text_sha256"], "cache_key": record_input["cache_key"]})
                continue
            elif not text or not has_word_content(text):
                reason = "空文本或仅表情/符号"
            elif row.get("is_consumer") in (0, "0", False):
                reason = "源记录已识别为非消费者表达"
            elif is_platform_parent_content(row):
                reason = "平台正文或创作者内容，非评论留言"
            elif is_promotion_or_bot(text):
                reason = "广告、推广或机器人表达（规则初筛，待复核）"
            elif is_bare_generic_praise(text):
                reason = "无产品信息的泛泛称赞"
            else:
                context_source, inclusion_reason, context_audit = _resolve_product_context(info, context, current_taxonomy)
                if not semantics or not context_source:
                    pending.append({"record_id": record_id, "hard_identity": hard_key,
                                    "platform": str(row.get("source") or "unknown"), "source_kind": evidence.source_kind(row),
                                    "reason": "需要Agent复核语义与产品上下文；词典未命中不构成排除", "excerpt": text,
                                    "text_sha256": record_input["text_sha256"], "cache_key": record_input["cache_key"], "published_at": row.get("published_at")})
                    continue
            if reason:
                excluded.append({"record_id": record_id, "hard_identity": hard_key,
                                 "platform": str(row.get("source") or "unknown"), "source_kind": evidence.source_kind(row),
                                 "reason": reason, "excerpt": text, "published_at": row.get("published_at"),
                                 "coding_method": decision["coding_method"] if decision else "rule_prescreen",
                                 "text_sha256": record_input["text_sha256"], "cache_key": record_input["cache_key"]})
                continue
            if single_segment_mode and decision is None:
                pending.append({
                    "record_id": record_id,
                    "hard_identity": hard_key,
                    "platform": str(row.get("source") or "unknown"),
                    "source_kind": evidence.source_kind(row),
                    "reason": "单细分流程要求逐条确认细分关联后才计入有效消费者声音",
                    "excerpt": text,
                    "text_sha256": record_input["text_sha256"],
                    "cache_key": record_input["cache_key"],
                    "published_at": row.get("published_at"),
                })
                continue
            if single_segment_mode and decision and decision["decision"] == "include" and single_segment_id not in decision["segment_memberships"]:
                raise LocalReprocessError("单细分纳入编码必须将记录归入当前 selected_segment")
            needs = list(decision["needs"]) if decision else []
            if decision:
                for need in needs:
                    existing_label = current_taxonomy["topic_labels"].get(need["code"])
                    if existing_label and existing_label != need["label"]:
                        raise LocalReprocessError("同一主题代码有冲突标签：%s" % need["code"])
                    current_taxonomy["topic_labels"][need["code"]] = need["label"]
            topics = [need["code"] for need in needs] if decision else topic_codes(text, semantics, current_taxonomy)
            memberships = list(decision["segment_memberships"]) if decision else segment_codes(text, current_taxonomy)
            collection_scopes = sorted(
                ({"selected_segment_all_history"} if single_segment_mode else {"category_all_history"})
                | {str(item["scope_id"]) for item in routes if item.get("scope_id")}
            )
            author = _author_key(row)
            thread = _thread_key(row)
            voice = {
                "voice_id": record_id,
                "hard_identity": hard_key,
                "platform": str(row.get("source") or "unknown"),
                "content_id": row.get("content_id"),
                "thread_id": row.get("thread_id"),
                "parent_content_id": row.get("parent_content_id"),
                "video_id": row.get("video_id"),
                "author_key": author,
                "author_label": row.get("author_label"),
                "published_at": row.get("published_at"),
                "collected_at": row.get("first_seen_at"),
                "source_url": _source_url(row),
                "excerpt": text,
                "full_text": text,
                "text_sha256": record_input["text_sha256"],
                "cache_key": record_input["cache_key"],
                "source_kind": evidence.source_kind(row),
                "coding_method": decision["coding_method"] if decision else "rule_provisional",
                "rule_version": decision.get("rule_version") if decision else None,
                "coding_status": ("classified" if decision["coding_method"] == "rule_classified" else "reviewed") if decision else "requires_agent_review",
                "needs": needs,
                "scenarios": list(decision.get("scenarios", [])) if decision else [],
                "first_batch_id": routes[0]["batch_id"] if routes else None,
                "semantic_codes": semantics,
                "semantic_labels": [current_taxonomy["semantic_labels"][code] for code in semantics],
                "topic_codes": topics,
                "topic_labels": [
                    current_taxonomy["topic_labels"].get(code)
                    or next(
                        (value[1] for value in GENERIC_TOPIC_BY_SEMANTIC.values() if value[0] == code),
                        code,
                    )
                    for code in topics
                ],
                "sentiment": _sentiment(semantics),
                "product_context_source": context_source,
                "inclusion_reason": inclusion_reason,
                "product_context_audit": dict(context_audit) if context_audit else None,
                "collection_scopes": collection_scopes,
                "segment_memberships": memberships,
                "discovery_routes": [
                    {key: value for key, value in item.items() if key != "query_text"}
                    for item in routes
                ],
                "engagement": _engagement(row.get("raw_json")),
                "thread_key": thread,
            }
            voices.append(voice)
            if decision and any(n.get("kano_review_version") != evidence.KANO_REVIEW_VERSION
                                or n.get("kano_review_status") in {None, "unreviewed"} for n in needs):
                kano_review_queue.append({**record_input, "needs": needs,
                                          "kano_review_version": evidence.KANO_REVIEW_VERSION})
        if used_imports != set(imported_entries):
            raise LocalReprocessError("导入包含过期、其他项目或原文/上下文/词典不匹配的编码")
    finally:
        connection.close()

    hard_unique_count = len(seen_hard_keys)
    qualified_count = len(voices)
    excluded_count = len(excluded)
    if hard_unique_count != qualified_count + excluded_count + len(pending):
        raise LocalReprocessError("硬身份总数与纳入/排除数无法对账")
    platform_names = sorted({str(item["platform"]) for item in voices})
    all_platforms = sorted(
        {str(item["platform"]) for item in voices}
        | {str(item["platform"]) for item in excluded}
        | {str(item["platform"]) for item in pending}
    )
    platform_rows = []
    for platform in all_platforms:
        platform_rows.append(
            {
                "platform": platform,
                "hard_unique_records": sum(
                    1 for item in voices if item["platform"] == platform
                )
                + sum(1 for item in excluded if item["platform"] == platform)
                + sum(1 for item in pending if item["platform"] == platform),
                "qualified_consumer_voices": sum(
                    1 for item in voices if item["platform"] == platform
                ),
                "excluded_records": sum(1 for item in excluded if item["platform"] == platform),
                "pending_records": sum(1 for item in pending if item["platform"] == platform),
            }
        )
    reason_counts = Counter(str(item["reason"]) for item in excluded)
    generated_at = iso_utc()
    snapshot_dashboard = (
        selection.get("project_snapshot", {}).get("opportunity_dashboard", {})
        if isinstance(selection.get("project_snapshot"), Mapping)
        else {}
    )
    dashboard_declaration: Optional[Dict[str, str]] = None
    if dashboard_path is not None and dashboard_hash_before is not None:
        dashboard_declaration = {
            "path": str(dashboard_path),
            "sha256": dashboard_hash_before,
        }
    elif isinstance(snapshot_dashboard, Mapping):
        snapshot_path = str(snapshot_dashboard.get("path") or "").strip()
        snapshot_hash = str(snapshot_dashboard.get("sha256") or "").strip().casefold()
        if snapshot_path and re.fullmatch(r"[0-9a-f]{64}", snapshot_hash):
            dashboard_declaration = {
                "path": snapshot_path,
                "sha256": snapshot_hash,
            }
    metadata = {
        "generated_at": generated_at,
        "source_db": str(source_db),
        "source_db_sha256": source_hash_before,
        "source_db_size_bytes": source_stat.st_size,
        "mode": MODE,
        "workflow_mode": "single_segment" if single_segment_mode else "legacy_top3",
        "no_network": True,
        "date_filter_applied": False,
        "evidence_protocol": "1.0.0",
        "collection_batch_order": batch_order,
        "collection_batch_results": batch_statuses,
        "required_scenarios": list(current_taxonomy.get("required_scenarios", [])),
        "semantic_match_rule": "六类语义任一命中（OR）",
        "product_context_rule": "显式产品锚点、已确认父/根内容，或多作者锚点达到相对比例门槛；不使用查询scope单独证明相关性",
        "taxonomy_profile": {
            "profile_id": str(current_taxonomy["profile_id"]),
            "source": str(current_taxonomy["source"]),
            "product_label": str(current_taxonomy["product_label"]),
            **(
                {"sha256": str(current_taxonomy["profile_sha256"])}
                if current_taxonomy.get("profile_sha256")
                else {}
            ),
        },
    }
    if dashboard_declaration is not None:
        metadata["opportunity_dashboard"] = dict(dashboard_declaration)
    if prior_analysis:
        metadata["prior_analysis"] = str(prior_analysis)
        metadata["prior_analysis_sha256"] = file_sha256(prior_analysis)
    funnel = {
        "discovered_records": discovered_count,
        "hard_unique_records": hard_unique_count,
        "examined_records": hard_unique_count,
        "qualified_consumer_voices": qualified_count,
        "excluded_records": excluded_count,
        "pending_records": len(pending),
        "hard_duplicate_rows_skipped": hard_duplicate_count,
        "platforms": platform_rows,
        "exclusion_reasons": [
            {"reason": reason, "count": count}
            for reason, count in sorted(reason_counts.items(), key=lambda item: (-item[1], item[0]))
        ],
    }
    taxonomy = [
        {"code": str(item["code"]), "label": str(item["label"])} for item in SEMANTIC_TAXONOMY
    ]
    project = _project_context(task, selection)
    semantic_analysis = _semantic_metrics(voices, qualified_count, current_taxonomy)
    segment_analysis = _segment_analysis(
        voices, segments, qualified_count, current_taxonomy
    )
    kano_analysis, kano_audit = _kano_results(voices, qualified_count)
    validation = {
        "source_database_opened_read_only": True,
        "network_calls": 0,
        "publication_date_used_as_filter": False,
        "semantic_deduplication_applied": False,
        "hard_identity_only": True,
        "semantic_or_rule_applied": True,
        "reconciliation": {
            "hard_unique_equals_qualified_plus_excluded_plus_pending": hard_unique_count
            == qualified_count + excluded_count + len(pending),
            "qualified_semantic_counts_recompute": sum(
                1 for voice in voices if voice["semantic_codes"]
            )
            == qualified_count,
            "different_id_same_text_kept_separately": True,
        },
    }
    limitations = [
        "本次仅重处理本地已抓取语料，没有补抓、刷新或调用任何外部接口。",
        "发布时间只作描述字段，不作为纳入或排除条件；结果代表本地语料全历史汇总，不代表特定时期趋势。",
        "查询scope不会单独证明产品相关；代词表达仅在已确认父/根内容或多作者产品锚点达到相对比例门槛时纳入。",
        "规则仅作初筛和建议；未复核的表达进入待编码队列，不能宣称已完成语义验证。",
        "地域未知不排除；有效VOC并不等于已确认美国消费者。",
        "KANO为消费者表达方向性归纳，不是正式配对问卷；供给缺口仍需结合现有商品快照验证。",
        "平台分布取决于本地已有采集结果，不能解释为整个市场的平台人口结构。",
    ]
    coding = {
        "schema_version": SCHEMA_VERSION,
        "metadata": metadata,
        "project": project,
        "top3_selection": _clean_prior_value(selection.get("top3_selection", {})),
        "selected_segment": _clean_prior_value(selection.get("selected_segment", {})) if single_segment_mode else None,
        "segments": segments,
        "scope_definitions": (
            [{"scope_id": "selected_segment_all_history", "label": "%s·本地全历史" % str(segments[0].get("feature") or "已选细分")}]
            if single_segment_mode
            else [
                {"scope_id": "category_all_history", "label": "全品类·本地全历史"},
                *[
                    {
                        "scope_id": str(segment.get("segment_id") or ""),
                        "label": "%s·本地全历史" % str(segment.get("feature") or "细分"),
                    }
                    for segment in segments
                ],
            ]
        ),
        "semantic_taxonomy": taxonomy,
        "funnel": funnel,
        "voices": voices,
        "excluded_records": excluded,
        "pending_records": pending,
        "validation": validation,
        "limitations": limitations,
    }
    prior_reuse = (
        _reuse_prior_analysis(prior_document, segment_analysis, kano_analysis)
        if prior_document
        else {}
    )
    product_concepts: List[Dict[str, Any]] = []
    queue_path = export_coding_queue or (output_dir / "agent_coding_queue.jsonl")
    coding_review = {"agent_reviewed": len(reviewed_entries), "rule_provisional": sum(v["coding_method"] == "rule_provisional" for v in voices),
                     "pending": len(pending), "unreviewed_records": len(review_queue),
                     "coverage": round(len(reviewed_entries) / hard_unique_count, 6) if hard_unique_count else 0.0, "queue_path": str(queue_path)}
    sample = prd_pipeline.quality_sample(reviewed_entries, {str(r["record_id"]): evidence.source_kind(r) for r in unique_rows})
    sample_keys = {r["cache_key"] for r in sample}
    reviewed_keys = set(quality.get("reviewed_cache_keys", []))
    results_sha256 = prd_pipeline.results_sha256(reviewed_entries)
    coding_review.update(
        agent_reviewed=sum(r["coding_method"] == "agent_reviewed" for r in reviewed_entries),
        rule_classified=sum(r["coding_method"] == "rule_classified" for r in reviewed_entries),
        model_reviewed=sum(r["coding_method"] == "model_reviewed" for r in reviewed_entries),
        processed_records=len(reviewed_entries),
        coding_method_counts=dict(Counter(r["coding_method"] for r in reviewed_entries)),
        completed_undetermined=sum(r.get("decision") == "undetermined" for r in pending),
        quality_sample_size=len(sample),
        results_sha256=results_sha256,
        quality_review_complete=(bool(quality.get("reviewer")) and quality.get("taxonomy_sha256") == taxonomy_hash
            and quality.get("results_sha256") == results_sha256
            and sample_keys <= reviewed_keys and quality.get("open_issues") == 0),
    )
    coding["processing_reconciliation"] = {"include": len(voices), "exclude": len(excluded),
        "undetermined": coding_review["completed_undetermined"],
        "pending": sum(r.get("decision") != "undetermined" for r in pending)}
    if single_segment_mode:
        task_policy = _safe_json(task.get("collection_policy_json"))
        social_policy = task_policy.get("evidence_target") if isinstance(task_policy, Mapping) else None
        if not isinstance(social_policy, Mapping):
            social_policy = {
                "normal_valid_target": 2000,
                "normal_valid_max": 3000,
                "data_exhaustion_downgrade_floor": 1200,
            }
        readiness = evidence.evaluate_single_segment(
            voices,
            segments[0],
            batch_order,
            coding_review,
            social_policy=social_policy,
            data_exhaustion=gap_fill_record,
            thresholds=evidence_thresholds,
            required_scenarios=current_taxonomy.get("required_scenarios", []),
            batch_statuses=batch_statuses,
        )
    else:
        readiness = evidence.evaluate(voices, segments, batch_order, coding_review, thresholds=evidence_thresholds,
                                      required_scenarios=current_taxonomy.get("required_scenarios", []), batch_statuses=batch_statuses)
    coding["coding_review"] = coding_review
    coding["processing_status"] = ("pending_review" if review_queue else "completed") if single_segment_mode else "complete"
    opportunity_tracks = _opportunity_tracks(voices, qualified_count, current_taxonomy)
    analysis = {
        "schema_version": SCHEMA_VERSION,
        "metadata": metadata,
        "project": project,
        "workflow_mode": "single_segment" if single_segment_mode else "legacy_top3",
        "selected_segment": _clean_prior_value(selection.get("selected_segment", {})) if single_segment_mode else None,
        # The all-history VOC scope must not rewrite the independent sales
        # measurement period, product title, or other frozen competitor facts.
        "competitive_pool": copy.deepcopy(selection.get("full_product_pool", {})) if single_segment_mode else None,
        "funnel": funnel,
        "sample_structure": _sample_structure(voices),
        "semantic_categories": semantic_analysis,
        "category_summary": _category_summary(voices, qualified_count, current_taxonomy),
        "top_segments": segment_analysis,
        "kano": kano_analysis,
        "kano_audit": kano_audit,
        # `new_needs` remains a compatibility alias for the strict concrete
        # track.  New reports render both tracks from opportunity_tracks.
        "new_needs": opportunity_tracks["specific_new_needs"],
        "opportunity_tracks": opportunity_tracks,
        "product_concepts": product_concepts,
        "exploration_concepts": [{**item, "recommendation_status": "requires_revalidation", "revalidation_reason": "历史方案只作探索资料；功能与当前证据需逐项重新核验"} for item in prior_reuse.get("product_concepts", [])],
        "processing_status": coding["processing_status"],
        "evidence_readiness": readiness,
        "coding_review": coding_review,
        "processing_reconciliation": dict(coding["processing_reconciliation"]),
        "source_breakdown": evidence.source_breakdown(voices),
        "repetition_audit": evidence.repetition_audit(voices),
        "validation": validation,
        "limitations": limitations,
        "representative_voices": _pick_representatives(voices, limit=12),
    }
    if single_segment_mode:
        social_valid = [voice for voice in voices if voice.get("source_kind") == "social" and voice.get("coding_method") in evidence.ACCEPTED_CODING_METHODS]
        analysis["business_rules_version"] = "voc-prd-v2.1"
        analysis["methodology"] = {"prd_version": "2.1", "kano_mode": "need_holistic_inference", "rule_version": rules.get("version"),
            "thresholds": {"kano_min_share": 0.03, "opportunity_min_share": 0.005, "quantity_targets_are_advisory": True}}
        analysis["kano"], kano_review_queue = prd_pipeline.holistic_kano(readiness["needs"], voices, taxonomy_hash,
            (prior_document or {}).get("kano", []))
        analysis["kano_audit"] = {"mode": "need_holistic_inference", "pending": len(kano_review_queue),
            "below_threshold": sum(r["status"] == "below_threshold" for r in analysis["kano"]),
            "completed": sum(r["status"] not in {"pending", "below_threshold"} for r in analysis["kano"])}
        analysis["category_summary"]["kano"] = [dict(item) for item in analysis["kano"]]
        analysis["quality_audit"] = {"status": "passed" if coding_review["quality_review_complete"] else "pending",
            "sample_size": len(sample), "rule_version": rules.get("version"), "results_sha256": results_sha256}
        analysis["collection_summary"] = {
            "workflow_mode": "single_segment",
            "scope_id": "selected_segment_all_history",
            "social_valid_voices": len(social_valid),
            "social_known_authors": len({str(voice["author_key"]) for voice in social_valid if evidence.known_author(voice.get("author_key"))}),
            "social_root_discussions": len({str(voice["thread_key"]) for voice in social_valid if evidence.context_key(voice.get("thread_key"))}),
            "social_platforms": sorted({str(voice["platform"]) for voice in social_valid}),
            "gap_fill_record": gap_fill_record or None,
            "counts_are_candidates": False,
        }
    if collection_receipt:
        raw_receipt = _load_json(collection_receipt)
        receipt_task = str(raw_receipt.get("task_id") or raw_receipt.get("task", {}).get("task_id") or "")
        if receipt_task != selected_task_id:
            raise LocalReprocessError("采集回执 task_id 与源数据库不一致")
        acquisition = raw_receipt.get("acquisition_budget", {})
        acquisition = acquisition if isinstance(acquisition, Mapping) else {}
        collection_summary = dict(analysis.get("collection_summary") or {})
        collection_summary.update({
            "collection_mode": raw_receipt.get("collection_mode", "legacy_unspecified"),
            "credits_limit": acquisition.get("credits_cap"),
            "credits_used": acquisition.get("committed_credits"),
            "estimated_cost_usd": acquisition.get("estimated_cost_usd"),
            "uncertain_credits": acquisition.get("uncertain_credits"),
            "acquisition_budget": {key: acquisition.get(key) for key in ("credits_cap", "committed_credits", "remaining_credits", "uncertain_credits", "estimated_cost_usd", "price_basis") if key in acquisition},
            "receipt_sha256": file_sha256(collection_receipt),
            "counts_are_candidates": True,
        })
        analysis["collection_summary"] = collection_summary
    if prior_reuse.get("prior_product_validation") is not None:
        analysis["validation"] = {
            **validation,
            "prior_product_validation": prior_reuse["prior_product_validation"],
        }
    if prior_reuse.get("future_validation_checklist") is not None:
        analysis["future_validation_checklist"] = prior_reuse[
            "future_validation_checklist"
        ]
    validate_v3_documents(coding, analysis)
    source_hash_after = file_sha256(source_db)
    source_stat_after = source_db.stat()
    source_unchanged = bool(
        source_hash_after == source_hash_before
        and source_stat_after.st_size == source_stat.st_size
        and source_stat_after.st_mtime_ns == source_stat.st_mtime_ns
    )
    if not source_unchanged:
        raise LocalReprocessError("只读处理前后 source-db 发生变化")
    dashboard_unchanged: Optional[bool] = None
    if dashboard_path is not None and dashboard_stat is not None:
        dashboard_stat_after = dashboard_path.stat()
        dashboard_unchanged = bool(
            file_sha256(dashboard_path) == dashboard_hash_before
            and dashboard_stat_after.st_size == dashboard_stat.st_size
            and dashboard_stat_after.st_mtime_ns == dashboard_stat.st_mtime_ns
        )
        if not dashboard_unchanged:
            raise LocalReprocessError("处理前后机会看板发生变化")
    receipt = {
        "schema_version": SCHEMA_VERSION,
        "metadata": metadata,
        "dry_run": dry_run,
        "source_db_unchanged": source_unchanged,
        "opportunity_dashboard_unchanged": dashboard_unchanged,
        "outputs_written": not dry_run,
        "output_dir": str(output_dir),
        "funnel": funnel,
        "semantic_category_counts": [
            {"code": item["code"], "label": item["label"], "count": item["count"]}
            for item in semantic_analysis
        ],
        "qualified_platforms": platform_names,
        "processing_status": "completed" if not review_queue else "pending_review",
        "evidence_readiness": readiness,
        "coding_review": coding_review,
    }
    if not dry_run:
        _atomic_json(output_dir / "review_batches.json", {"schema_version": "1.0", "taxonomy_sha256": taxonomy_hash,
            "batches": prd_pipeline.review_batches(review_queue)})
        _atomic_json(output_dir / "quality_review_queue.json", {"taxonomy_sha256": taxonomy_hash,
            "results_sha256": results_sha256, "entries": sample,
            "instruction": "独立核对原文/上下文；回执需taxonomy_sha256, results_sha256, reviewer, reviewed_cache_keys；open_issues为未闭环问题整数数量（完成时0），明细另存open_issue_details数组"})
        published_values = sorted(
            str(row.get("published_at"))
            for row in unique_rows
            if row.get("published_at")
        )
        source_snapshot = {
            "schema_version": SCHEMA_VERSION,
            "generated_at": generated_at,
            "source_db": str(source_db),
            "source_db_sha256": source_hash_before,
            "source_db_size_bytes": source_stat.st_size,
            "source_db_mtime": datetime.fromtimestamp(
                source_stat.st_mtime, tz=timezone.utc
            ).isoformat().replace("+00:00", "Z"),
            "source_task": {
                key: task.get(key)
                for key in (
                    "task_id",
                    "topic",
                    "research_level",
                    "status",
                    "end_at",
                    "project_dir",
                    "run_dir",
                )
                if task.get(key) is not None
            },
            "discovered_records": discovered_count,
            "hard_unique_records": hard_unique_count,
            "platforms": platform_rows,
            "published_at_earliest": published_values[0] if published_values else None,
            "published_at_latest": published_values[-1] if published_values else None,
            "no_network": True,
            "opportunity_dashboard": dict(dashboard_declaration)
            if dashboard_declaration is not None
            else None,
        }
        snapshot_path = output_dir / SOURCE_SNAPSHOT_FILENAME
        receipt["source_snapshot"] = str(snapshot_path)
        _atomic_jsonl(queue_path, review_queue)
        _atomic_jsonl(output_dir / "kano_review_queue.jsonl", kano_review_queue)
        if coding_cache:
            merged_cache = {**cached_entries, **{item["cache_key"]: item for item in reviewed_entries}}
            _atomic_json(output_dir / "coding_cache.json", {"schema_version": "1.0.0", "entries": list(merged_cache.values())})
        _atomic_json(output_dir / CODING_FILENAME, coding)
        _atomic_json(output_dir / ANALYSIS_FILENAME, analysis)
        _atomic_json(snapshot_path, source_snapshot)
        _atomic_json(output_dir / RECEIPT_FILENAME, receipt)
    return receipt


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="仅使用本地 SQLite、无时间窗、无联网的消费者声音全历史重处理"
    )
    parser.add_argument("--source-db", required=True, type=Path, help="已有 collector.sqlite3")
    parser.add_argument("--output-dir", required=True, type=Path, help="新产物目录")
    parser.add_argument("--task-id", help="source-db 含多个任务时指定")
    parser.add_argument("--selection-file", type=Path, help="可选的 selected_segments.json")
    parser.add_argument(
        "--prior-analysis",
        type=Path,
        help="可选的旧 social_voice_analysis.json，用于复用并清洗产品方案与验证清单",
    )
    parser.add_argument(
        "--taxonomy-profile",
        type=Path,
        help="非车载手机支架项目必填的项目级 taxonomy profile JSON",
    )
    parser.add_argument(
        "--dashboard",
        type=Path,
        help="原机会看板；仅计算并记录哈希，处理前后保持只读不变",
    )
    parser.add_argument("--agent-coding", action="append", type=Path, default=[], help="Agent逐条编码JSON/JSONL；可重复指定，绑定原文和上下文")
    parser.add_argument("--rule-config", type=Path, help="PRD声明式规则JSON；未覆盖记录进入疑难复核")
    parser.add_argument("--quality-review", type=Path, help="绑定词典哈希的独立质量复核回执JSON")
    parser.add_argument("--coding-cache", type=Path, help="只读输入缓存；派生缓存写新output-dir/coding_cache.json")
    parser.add_argument("--export-coding-queue", type=Path, help="导出待编码JSONL；默认输出目录下agent_coding_queue.jsonl")
    parser.add_argument("--collection-receipt", type=Path, help="同task采集回执；只导入费用和模式，不信任其有效数或饱和结论")
    parser.add_argument("--single-segment-gap-fill", type=Path, help="关键场景查漏回执；v2数量目标为参考，处理与质量须完成")
    parser.add_argument("--evidence-thresholds", type=Path, help="历史兼容门槛；v2参考目标6000=4000+2000")
    parser.add_argument("--dry-run", action="store_true", help="完成全量扫描和对账，但不写产物")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        receipt = reprocess(
            args.source_db,
            args.output_dir,
            task_id=args.task_id,
            selection_file=args.selection_file,
            prior_analysis=args.prior_analysis,
            taxonomy_profile=args.taxonomy_profile,
            dashboard=args.dashboard,
            agent_coding=args.agent_coding,
            rule_config=args.rule_config,
            quality_review=args.quality_review,
            coding_cache=args.coding_cache,
            export_coding_queue=args.export_coding_queue,
            evidence_thresholds=_load_json(args.evidence_thresholds) if args.evidence_thresholds else None,
            collection_receipt=args.collection_receipt,
            single_segment_gap_fill=args.single_segment_gap_fill,
            dry_run=bool(args.dry_run),
        )
    except (ValueError, OSError, sqlite3.Error) as exc:
        print("全历史本地重处理失败：%s" % exc, file=sys.stderr)
        return 2
    print(json.dumps(receipt, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
