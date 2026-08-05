#!/usr/bin/env python3
"""Read-only, offline reprocessing of an existing consumer-voice SQLite corpus.

This module deliberately has no network client.  It reads the collector database
with SQLite query-only mode, ignores publication windows, keeps every hard-unique
message, and accepts a message when it is product-related, consumer-authored, and
matches at least one of the six configured semantic families.
"""

from __future__ import annotations

import argparse
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
    r"(?:confidence|window|(?:^|_)(?:start_at|end_at|time_range|date_range)(?:$|_)|source[_ -]?status|evidence.*(?:count|total)|(?:count|total).*evidence)",
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
        source = str(row.get("source") or "unknown")
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
        anchor_authors = {str(child["author"]) for child in anchors}
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


def _author_key(row: Mapping[str, Any]) -> str:
    for key in ("author_hash", "author_id", "author_label"):
        value = str(row.get(key) or "").strip()
        if value:
            return value
    return "unknown:" + str(row.get("record_id") or "")


def _thread_key(row: Mapping[str, Any]) -> str:
    for key in ("thread_id", "video_id", "parent_content_id", "canonical_url"):
        value = str(row.get(key) or "").strip()
        if value:
            return value
    return "record:" + str(row.get("record_id") or "")


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
    if not isinstance(raw_topics, list) or not raw_topics:
        raise LocalReprocessError("taxonomy profile topics 至少需要一项")
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
    if not isinstance(raw_segments, list) or not (1 <= len(raw_segments) <= 3):
        raise LocalReprocessError("taxonomy profile segments 必须包含 1-3 项")
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
        if not re.fullmatch(r"segment_[a-z0-9_]+_all_history", segment_id):
            raise LocalReprocessError(
                "taxonomy profile segments[%d].segment_id 必须是全历史 scope" % index
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
    if not isinstance(raw_kano, Mapping) or not raw_kano:
        raise LocalReprocessError("taxonomy profile kano_mapping 至少需要一项")
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


def _discoveries(connection: sqlite3.Connection, task_id: str) -> Tuple[int, Dict[str, List[Dict[str, str]]]]:
    rows = connection.execute(
        """SELECT d.record_id,d.scope,d.query_id,d.source,b.backend,b.query_text
        FROM comment_discoveries d JOIN batches b ON b.batch_id=d.batch_id
        WHERE d.task_id=? ORDER BY d.discovery_id""",
        (task_id,),
    ).fetchall()
    by_record: Dict[str, List[Dict[str, str]]] = defaultdict(list)
    seen: Dict[str, set[Tuple[str, str, str]]] = defaultdict(set)
    for row in rows:
        record_id = str(row["record_id"])
        marker = (str(row["scope"]), str(row["query_id"]), str(row["backend"]))
        if marker in seen[record_id]:
            continue
        seen[record_id].add(marker)
        by_record[record_id].append(
            {
                "scope_id": _map_all_history_string(str(row["scope"])),
                "query_id": str(row["query_id"]),
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
    authors = {str(item["author_key"]) for item in voices}
    threads = {str(item["thread_key"]) for item in voices}
    platforms = sorted({str(item["platform"]) for item in voices})
    return {
        "code": code,
        "label": label,
        "count": len(voices),
        "share": round(len(voices) / denominator, 6) if denominator else 0.0,
        "authors": len(authors),
        "threads": len(threads),
        "platforms": platforms,
        "representative_voices": _pick_representatives(voices),
    }


def _topic_metrics(
    voices: Sequence[Mapping[str, Any]],
    denominator: int,
    taxonomy: Optional[Mapping[str, Any]] = None,
) -> List[Dict[str, Any]]:
    current = _taxonomy(taxonomy)
    labels = current["topic_labels"]
    grouped: Dict[str, List[Mapping[str, Any]]] = defaultdict(list)
    for voice in voices:
        for code in voice["topic_codes"]:
            grouped[str(code)].append(voice)
    result = []
    for code, children in grouped.items():
        label = labels.get(code)
        if not label:
            label = next(
                (value[1] for value in GENERIC_TOPIC_BY_SEMANTIC.values() if value[0] == code),
                code,
            )
        result.append(_metric(label, code, children, denominator))
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
        result[key] = topics[:20]
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
        row["semantic_categories"] = _semantic_metrics(children, denominator, taxonomy)
        row["top_topics"] = _topic_metrics(children, denominator, taxonomy)[:12]
        row.update(_category_summary(children, denominator, taxonomy))
        result.append(row)
    return result


def _kano(
    voices: Sequence[Mapping[str, Any]],
    denominator: int,
    taxonomy: Optional[Mapping[str, Any]] = None,
) -> List[Dict[str, Any]]:
    current = _taxonomy(taxonomy)
    kano_by_topic = current["kano_by_topic"]
    topics = _topic_metrics(voices, denominator, current)
    result = []
    for item in topics:
        code = str(item["code"])
        if code.startswith("general_") or code not in kano_by_topic:
            continue
        children = [voice for voice in voices if code in voice["topic_codes"]]
        kano_type = kano_by_topic[code]
        indifferent = [voice for voice in children if _matches(str(voice["excerpt"]), INDIFFERENCE_REGEX)]
        rejected = [voice for voice in children if _matches(str(voice["excerpt"]), REJECTION_REGEX)]

        # Keep the topic's product attribute classification stable.  A comment
        # saying "no magnet" may also mention a vent or charger; it must not
        # flip every co-mentioned topic into a reverse attribute.  Explicit
        # rejections remain counted as directional evidence/new needs.
        result.append(
            {
                "need_code": code,
                "need": item["label"],
                "kano_type": kano_type,
                "count": item["count"],
                "share": item["share"],
                "authors": item["authors"],
                "threads": item["threads"],
                "platforms": item["platforms"],
                "representative_voices": item["representative_voices"],
                "explicit_indifference_count": len(indifferent),
                "explicit_rejection_count": len(rejected),
                "method": "消费者表达方向性归纳，非正式KANO问卷",
            }
        )
    return result


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
    result = _topic_metrics(children, denominator, taxonomy)
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
    return result[:20]


def _product_concepts(
    top_segments: Sequence[Mapping[str, Any]],
    taxonomy: Optional[Mapping[str, Any]] = None,
) -> List[Dict[str, Any]]:
    current = _taxonomy(taxonomy)
    by_rank = {int(item.get("rank") or 0): item for item in top_segments}
    if current.get("source") != "built_in":
        product_label = str(current["product_label"])
        generic: List[Dict[str, Any]] = []
        ordered = sorted(top_segments, key=lambda item: int(item.get("rank") or 99))
        for rank in range(1, 4):
            segment = ordered[rank - 1] if rank <= len(ordered) else {}
            topics = [row for row in segment.get("top_topics", []) if isinstance(row, Mapping)]
            topic_labels = [str(row.get("label") or "") for row in topics[:6] if row.get("label")]
            feature = str(segment.get("feature") or "全品类方向%d" % rank)
            generic.append(
                {
                    "rank": rank,
                    "name": "%s·%s需求方案" % (product_label, feature),
                    "target_users": "在%s相关场景中有明确需求的消费者" % feature,
                    "scenario": "%s的核心使用与问题解决场景" % feature,
                    "must": topic_labels[:4] or ["满足该细分已识别的核心消费者需求"],
                    "should": topic_labels[4:6] or ["强化耐用性与可维护性"],
                    "could": ["基于后续验证增加模块化扩展"],
                    "segment_id": segment.get("segment_id"),
                    "segment": segment.get("feature"),
                    "supporting_voice_count": int(segment.get("count") or 0),
                    "supporting_topic_codes": [
                        str(row.get("code")) for row in topics[:6] if row.get("code")
                    ],
                    "wont_this_release": ["未经消费者和工程验证的高风险功能"],
                    "status": "基于本地消费者表达形成的产品方向，待工程与供给验证",
                }
            )
        return generic
    defaults = (
        {
            "rank": 1,
            "name": "全尺寸机械夹持稳固支架",
            "target_users": "重视稳定、单手取放和手机壳兼容的日常驾驶者",
            "scenario": "通勤、颠簸道路与频繁导航",
            "must": ["机械双重锁止", "厚壳兼容", "不遮挡驾驶视野", "单手快拆"],
            "should": ["耐高温底座", "角度记忆", "可更换防滑垫"],
            "could": ["模块化充电组件", "线缆管理"],
        },
        {
            "rank": 2,
            "name": "卡车长途抗振支架",
            "target_users": "卡车、重型车、车队与长途运输司机",
            "scenario": "长途驾驶、强震动驾驶室与多班次换机",
            "must": ["多点机械锁止", "高幅振动抑制", "戴手套可操作", "不依赖一次性胶粘"],
            "should": ["快拆导轨", "超长可达调节", "阻燃耐候材料"],
            "could": ["支架定位防盗", "车队资产标签位"],
        },
        {
            "rank": 3,
            "name": "Tesla低遮挡内饰融合支架",
            "target_users": "Tesla车主和重视内饰一体感的消费者",
            "scenario": "中控屏周边导航、充电和横竖屏切换",
            "must": ["不遮挡中控屏", "无损安装", "稳定磁吸/机械保险", "手机壳兼容"],
            "should": ["Qi2充电", "线缆隐蔽", "内饰同色表面处理"],
            "could": ["左右舵模块化", "快拆扩展臂"],
        },
    )
    result = []
    for item in defaults:
        segment = by_rank.get(int(item["rank"]), {})
        supporting_topics = [row["code"] for row in segment.get("top_topics", [])[:6]]
        result.append(
            {
                **item,
                "segment_id": segment.get("segment_id"),
                "segment": segment.get("feature"),
                "supporting_voice_count": int(segment.get("count") or 0),
                "supporting_topic_codes": supporting_topics,
                "wont_this_release": ["未经验证的自动驾驶联动", "依赖云端账号的核心夹持功能"],
                "status": "基于本地消费者表达形成的产品方向，待工程与供给验证",
            }
        )
    return result


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
        "unique_authors": len({str(voice["author_key"]) for voice in voices}),
        "unique_threads": len({str(voice["thread_key"]) for voice in voices}),
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
    class_map = {
        "M": "必备型",
        "must_be": "必备型",
        "O": "期望型",
        "one_dimensional": "期望型",
        "performance": "期望型",
        "A": "魅力型",
        "attractive": "魅力型",
        "I": "无差异型",
        "indifferent": "无差异型",
        "R": "反向型",
        "reverse": "反向型",
    }
    result: List[Dict[str, Any]] = []
    for raw in rows:
        if not isinstance(raw, Mapping):
            continue
        cleaned = _clean_prior_value(raw)
        if not isinstance(cleaned, Mapping):
            continue
        row = dict(cleaned)
        old_need = str(row.get("need_code") or "")
        mapped_need = aliases.get(old_need, old_need)
        current_row = current.get(mapped_need)
        classification = str(row.get("classification") or row.get("kano_type") or "")
        if classification in {"evidence_insufficient", "待问卷验证"}:
            if not current_row:
                continue
            classification = str(current_row["kano_type"])
            row["design_response"] = (
                "按本地全历史消费者表达重映射为%s；后续仍需正式KANO问卷验证。"
                % classification
            )
        else:
            classification = class_map.get(classification, classification)
            if classification not in KANO_TYPES and current_row:
                classification = str(current_row["kano_type"])
        if classification not in KANO_TYPES:
            continue
        row["need_code"] = mapped_need
        row["classification"] = classification
        row.pop("kano_type", None)
        if current_row:
            row["need"] = current_row["need"]
        result.append(row)
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
        concept["supporting_voice_count"] = int(segment.get("count") or 0)
        concept["supporting_topic_codes"] = [
            str(item["code"]) for item in segment.get("top_topics", [])[:8]
        ]
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
                if str(child) not in KANO_TYPES:
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
    except (KeyError, TypeError, ValueError) as exc:
        raise LocalReprocessError("v3 漏斗字段缺失或类型无效") from exc
    if examined != hard_unique or hard_unique != qualified + excluded_count:
        raise LocalReprocessError(
            "v3 漏斗必须满足 examined=hard_unique=qualified+excluded"
        )

    voices = coding.get("voices")
    excluded = coding.get("excluded_records")
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
    if voice_record_ids.intersection(excluded_record_ids) or voice_hard_ids.intersection(
        excluded_hard_ids
    ):
        raise LocalReprocessError("voices 与 excluded_records 身份必须互斥")
    if (
        len(voice_record_ids | excluded_record_ids) != hard_unique
        or len(voice_hard_ids | excluded_hard_ids) != hard_unique
    ):
        raise LocalReprocessError("voices/excluded_records 未完整覆盖 hard_unique")

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

    kano = analysis.get("kano")
    if not isinstance(kano, list):
        raise LocalReprocessError("analysis.kano 必须为数组")
    for index, item in enumerate(kano):
        if not isinstance(item, Mapping) or str(item.get("kano_type")) not in KANO_TYPES:
            raise LocalReprocessError("analysis.kano[%d] 不是五类中文KANO" % index)


def _contains_forbidden_grading_key(value: Any) -> bool:
    """Compatibility helper retained for callers; v3 uses strict validation."""
    try:
        _validate_clean_structure(value)
    except LocalReprocessError:
        return True
    return False


def reprocess(
    source_db: Path,
    output_dir: Path,
    *,
    task_id: Optional[str] = None,
    selection_file: Optional[Path] = None,
    prior_analysis: Optional[Path] = None,
    taxonomy_profile: Optional[Path] = None,
    dashboard: Optional[Path] = None,
    dry_run: bool = False,
) -> Mapping[str, Any]:
    source_db = source_db.expanduser().resolve()
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
    connection = _open_readonly(source_db)
    try:
        task = _select_task(connection, task_id)
        selected_task_id = str(task["task_id"])
        selection = _load_selection(task, selection_file)
        if taxonomy_profile:
            current_taxonomy = _load_taxonomy_profile(taxonomy_profile)
        else:
            if not _builtin_category_is_explicit(task, selection):
                raise LocalReprocessError(
                    "未提供 --taxonomy-profile；内置默认仅允许明确识别为车载手机支架的项目"
                )
            current_taxonomy = BUILTIN_TAXONOMY
        prior_document: Optional[Mapping[str, Any]] = None
        if prior_analysis:
            prior_analysis = prior_analysis.expanduser().resolve()
            prior_document = _load_json(prior_analysis)
        profile_segments = current_taxonomy.get("segment_definitions")
        if isinstance(profile_segments, Sequence) and profile_segments:
            segments = [dict(item) for item in profile_segments if isinstance(item, Mapping)]
        else:
            segments = [
                _output_segment(item)
                for item in selection.get("selected_segments", [])
                if isinstance(item, Mapping)
            ]
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
            hard_key = str(row.get("hard_key") or row.get("record_id") or "")
            if hard_key in seen_hard_keys:
                hard_duplicate_count += 1
                continue
            seen_hard_keys.add(hard_key)
            unique_rows.append(row)
        context = _product_context_index(unique_rows, discoveries, current_taxonomy)
        for row in unique_rows:
            hard_key = str(row.get("hard_key") or row.get("record_id") or "")
            record_id = str(row["record_id"])
            text = normalize_text(row.get("text"))
            routes = discoveries.get(record_id, [])
            info = context["infos"][record_id]
            semantics = list(info["semantics"])
            reason: Optional[str] = None
            context_source: Optional[str] = None
            inclusion_reason: Optional[str] = None
            context_audit: Optional[Mapping[str, Any]] = None
            if not text or not has_word_content(text):
                reason = "空文本或仅表情/符号"
            elif row.get("is_consumer") in (0, "0", False):
                reason = "源记录已识别为非消费者表达"
            elif is_platform_parent_content(row):
                reason = "平台正文或创作者内容，非评论留言"
            elif is_promotion_or_bot(text):
                reason = "广告、推广或机器人表达"
            elif not semantics:
                reason = "未覆盖六类语义"
            else:
                context_source, inclusion_reason, context_audit = _resolve_product_context(
                    info, context, current_taxonomy
                )
                if not context_source:
                    reason = "缺少可审计的产品上下文"
            if reason:
                excluded.append(
                    {
                        "record_id": record_id,
                        "hard_identity": hard_key,
                        "platform": str(row.get("source") or "unknown"),
                        "reason": reason,
                        "excerpt": text[:240],
                        "published_at": row.get("published_at"),
                    }
                )
                continue
            topics = topic_codes(text, semantics, current_taxonomy)
            memberships = segment_codes(text, current_taxonomy)
            collection_scopes = sorted(
                {"category_all_history"}
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
                "excerpt": text[:1000],
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
    finally:
        connection.close()

    hard_unique_count = len(seen_hard_keys)
    qualified_count = len(voices)
    excluded_count = len(excluded)
    if hard_unique_count != qualified_count + excluded_count:
        raise LocalReprocessError("硬身份总数与纳入/排除数无法对账")
    platform_names = sorted({str(item["platform"]) for item in voices})
    all_platforms = sorted(
        {str(item["platform"]) for item in voices}
        | {str(item["platform"]) for item in excluded}
    )
    platform_rows = []
    for platform in all_platforms:
        platform_rows.append(
            {
                "platform": platform,
                "hard_unique_records": sum(
                    1 for item in voices if item["platform"] == platform
                )
                + sum(1 for item in excluded if item["platform"] == platform),
                "qualified_consumer_voices": sum(
                    1 for item in voices if item["platform"] == platform
                ),
                "excluded_records": sum(
                    1 for item in excluded if item["platform"] == platform
                ),
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
        "no_network": True,
        "date_filter_applied": False,
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
    kano_analysis = _kano(voices, qualified_count, current_taxonomy)
    validation = {
        "source_database_opened_read_only": True,
        "network_calls": 0,
        "publication_date_used_as_filter": False,
        "semantic_deduplication_applied": False,
        "hard_identity_only": True,
        "semantic_or_rule_applied": True,
        "reconciliation": {
            "hard_unique_equals_qualified_plus_excluded": hard_unique_count
            == qualified_count + excluded_count,
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
        "六类语义和主题由可复算词典规则编码；讽刺、隐喻及小语种表达可能漏判。",
        "KANO为消费者表达方向性归纳，不是正式配对问卷；供给缺口仍需结合现有商品快照验证。",
        "平台分布取决于本地已有采集结果，不能解释为整个市场的平台人口结构。",
    ]
    coding = {
        "schema_version": SCHEMA_VERSION,
        "metadata": metadata,
        "project": project,
        "top3_selection": _clean_prior_value(selection.get("top3_selection", {})),
        "segments": segments,
        "scope_definitions": [
            {"scope_id": "category_all_history", "label": "全品类·本地全历史"},
            *[
                {
                    "scope_id": str(segment.get("segment_id") or ""),
                    "label": "%s·本地全历史" % str(segment.get("feature") or "细分"),
                }
                for segment in segments
            ],
        ],
        "semantic_taxonomy": taxonomy,
        "funnel": funnel,
        "voices": voices,
        "excluded_records": excluded,
        "validation": validation,
        "limitations": limitations,
    }
    prior_reuse = (
        _reuse_prior_analysis(prior_document, segment_analysis, kano_analysis)
        if prior_document
        else {}
    )
    product_concepts = prior_reuse.get("product_concepts") or _product_concepts(
        segment_analysis, current_taxonomy
    )
    analysis = {
        "schema_version": SCHEMA_VERSION,
        "metadata": metadata,
        "project": project,
        "funnel": funnel,
        "sample_structure": _sample_structure(voices),
        "semantic_categories": semantic_analysis,
        "category_summary": _category_summary(voices, qualified_count, current_taxonomy),
        "top_segments": segment_analysis,
        "kano": kano_analysis,
        "new_needs": _new_needs(voices, qualified_count, current_taxonomy),
        "product_concepts": product_concepts,
        "validation": validation,
        "limitations": limitations,
        "representative_voices": _pick_representatives(voices, limit=12),
    }
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
    }
    if not dry_run:
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
            dry_run=bool(args.dry_run),
        )
    except (LocalReprocessError, OSError, sqlite3.Error) as exc:
        print("全历史本地重处理失败：%s" % exc, file=sys.stderr)
        return 2
    print(json.dumps(receipt, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
