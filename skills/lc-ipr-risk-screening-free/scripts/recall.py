#!/usr/bin/env python3
"""US patent and design recall in patent language (new tasks with ``recall_revision``, r5d20).

Owner's runs B0GLNPC6K8 (electric butterfly cat teaser, report of 2026-10-13) and B0H16FDSD8 (rolling grill
basket): the design patent the owner knows for the cat teaser, USD1152251S "Cat teaser" (granted 2026-10-06), was
never retrieved. The only design query was the listing phrase "butterfly cat toy" (zero results: a design patent's
text is its title and one claim sentence, and this one says neither butterfly nor toy). Invention patents went to
EPO only - title/abstract words ANDed, no word forms, the first 25 results - with listing phrases like
"perforated end lid" that brought back pool skimmers and nuclear casks. The motor, rotation modes and tap wake-up the
listing describes in bullets 2-4 never became a query: the understanding step could only cite the title and the
first bullet, one query was planned per clue source, and a reviewer's "search again with pet toy / teaser" could
only pick the next word of the original list.

Owner decisions (2026-10-14): Google Patents (SerpApi) is the US source for patents and designs, 100 results per
request (the same single credit) and only rights that can still be in force; EPO is a fallback when SerpApi cannot
run, searching US publications only.

* product understanding gives patent-language concept groups: article names (the names patents use for the product
  as a whole, broader names included) and core function concepts (from any bullet), each with its word forms;
* the planner composes them (``compose_terms``): D1 = the article names, D2 = the head nouns with their modifiers
  (US designs, type DESIGN); U1-U3 = the article names AND one function concept (US utility, type PATENT); every
  group is its own discovery purpose;
* a refinement may carry the reviewer's own concept groups (``refine_query``).

Nothing here grades a risk or relaxes a validator; old tasks never see any of it.
"""
from __future__ import annotations

import re
from datetime import date

REVISION = 'recall-v1'
ROUTING_REVISION = 'api-first-v3-recall'
GUARD_ROUTING_REVISION = 'api-first-v3-recall-guard'
GROUPS = ('design', 'patent')
SERPAPI_MAX_RESULTS = 100
OTHER_MAX_RESULTS = 10
DESIGN_YEARS = 16          # a US design is in force 15 years from grant (14 for filings before 2015-05-13)
PATENT_YEARS = 21          # 20 years from the earliest non-provisional filing, a provisional year before
# r9 (portable-v1): a registered design outside the US (EU, GB, JP, ...) can stay in force 25 years from filing
NATIONAL_DESIGN_YEARS = 26
MAX_ARTICLE_NAMES = 8
MAX_FUNCTIONS = 4
MAX_FORMS = 6
MAX_FUNCTION_QUERIES = 3
WORD = re.compile(r"^[A-Za-z][A-Za-z\-']*$")
STOP = frozenset({'the', 'a', 'an', 'for', 'with', 'and', 'of', 'to', 'in', 'by', 'or', 'not', 'on'})
PROMOTION = frozenset({'universal', 'reusable', 'premium', 'perfect', 'ideal', 'best', 'great', 'new', 'upgraded',
                       'improved', 'original', 'genuine', 'patented', 'professional', 'deluxe', 'ultimate', 'amazing',
                       'easy', 'simple', 'innovative', 'quality', 'durable', 'versatile', 'portable', 'convenient'})
PROBLEM_PREFIX = 'recall-v1:'


def enabled(task) -> bool:
    return isinstance(task, dict) and task.get('recall_revision') == REVISION


def routing_revision(task):
    """The provider order the discovery planner follows: Google Patents first for recall tasks."""
    if enabled(task) and __import__('search_guard').enabled(task):
        return GUARD_ROUTING_REVISION   # r7: EPO is the US design fallback too
    return ROUTING_REVISION if enabled(task) else task.get('retrieval_workflow_revision')


def results_per_query(task, provider, policy_value):
    """SerpApi Google Patents takes up to 100 results for one credit in recall tasks; every other route keeps 10."""
    if enabled(task) and provider == 'serpapi_google_patents':
        return min(policy_value, SERPAPI_MAX_RESULTS)
    return min(policy_value, OTHER_MAX_RESULTS)


def _created(task):
    try:
        return date.fromisoformat(str(task.get('created_at') or '')[:10])
    except ValueError:
        return date.today()


NEWEST_FIRST_PROBLEMS = frozenset({PROBLEM_PREFIX + 'design-broad'})


def serpapi_params(task, right, term=None, country=None):
    """Extra wire parameters of a recall task's Google Patents discovery: the document type and the earliest priority
    date a right still in force can have (fixed by the task's creation date, so the query id never drifts). The broad
    design group is read newest first: in a crowded category (pet toys) a design granted last week would otherwise sit
    far below the first 100 by relevance (USD1152251S, granted a week before the B0GLNPC6K8 run)."""
    if not enabled(task) or right not in GROUPS:
        return {}
    extra = {'sort': 'new'} if (term or {}).get('discovery_problem_id') in NEWEST_FIRST_PROBLEMS else {}
    created = _created(task)
    years = DESIGN_YEARS if right == 'design' else PATENT_YEARS
    if right == 'design' and country and str(country).upper() != 'US' and __import__('portable').enabled(task):
        years = NATIONAL_DESIGN_YEARS
    try:
        earliest = created.replace(year=created.year - years)
    except ValueError:                       # 29 February
        earliest = created.replace(year=created.year - years, day=28)
    return {'type': 'DESIGN' if right == 'design' else 'PATENT', 'after': 'priority:' + earliest.strftime('%Y%m%d'),
            **extra}


AFTER_PATTERN = re.compile(r'^priority:\d{8}$')


# ----- concept groups (product_understanding_host) ------------------------------------------------------------------
def _clean(value, *, words=4):
    text = ' '.join(str(value or '').replace('"', ' ').split())
    tokens = [token for token in text.split(' ') if token]
    if not tokens or len(tokens) > words or any(not WORD.match(token) for token in tokens):
        return None
    if all(token.lower() in STOP | PROMOTION for token in tokens):
        return None
    tokens = [token for token in tokens if token.lower() not in PROMOTION]
    return ' '.join(token.lower() for token in tokens) or None


def _source(value, sources):
    """A cited path; one bullet of the list counts as the whole-list fact when only that one exists."""
    if value in sources:
        return value
    if isinstance(value, str) and re.fullmatch(r'product\.bullets\[\d+\]', value) and 'product.bullets' in sources:
        return 'product.bullets'
    return None


def parse_concepts(raw, sources):
    """Validated concept groups, or ValueError. ``sources`` are the fact source paths a concept may cite."""
    if not isinstance(raw, dict):
        raise ValueError('RECALL_CONCEPTS_REQUIRED')
    names, seen = [], set()
    for item in raw.get('article_names') or []:
        value = _clean(item.get('value') if isinstance(item, dict) else item, words=3)
        source = _source(item.get('derived_from') if isinstance(item, dict) else 'product.title', sources)
        if value is None or source is None:
            raise ValueError('RECALL_ARTICLE_NAME_INVALID')
        if value not in seen and len(value.split()) >= 1:
            seen.add(value)
            names.append({'value': value, 'derived_from': source,
                          **({'broad': True} if isinstance(item, dict) and item.get('broad') is True else {})})
    if not 2 <= len(names) <= MAX_ARTICLE_NAMES + 2:
        raise ValueError('RECALL_ARTICLE_NAMES_COUNT_INVALID')
    functions = []
    for item in raw.get('function_concepts') or []:
        if not isinstance(item, dict):
            raise ValueError('RECALL_FUNCTION_CONCEPT_INVALID')
        label = ' '.join(str(item.get('label') or '').split())[:60]
        source = _source(item.get('derived_from'), sources)
        forms = []
        for form in item.get('terms') or []:
            value = _clean(form, words=2)
            if value and value not in forms:
                forms.append(value)
        if not label or source is None or not 1 <= len(forms) <= MAX_FORMS + 2:
            raise ValueError('RECALL_FUNCTION_CONCEPT_INVALID')
        functions.append({'label': label, 'terms': forms[:MAX_FORMS], 'derived_from': source})
    if len(functions) > MAX_FUNCTIONS + 2:
        raise ValueError('RECALL_FUNCTION_CONCEPTS_COUNT_INVALID')
    return {'article_names': names[:MAX_ARTICLE_NAMES], 'function_concepts': functions[:MAX_FUNCTIONS]}


LISTING_PHRASE = PROBLEM_PREFIX + 'listing-phrase'


def program_group(basis):
    """True for the purpose basis of a concept group compose_terms wrote."""
    return (isinstance(basis, dict) and str(basis.get('problem_id') or '').startswith(PROBLEM_PREFIX)
            and basis.get('different_from_purpose_id') == LISTING_PHRASE)


MAX_QUERY_WORDS = 24      # workflow_v24.boolean_tokens: a query is a bounded feature group, operators included


def _words(values):
    return sum(len(value.split()) for value in values) + max(0, len(values) - 1)


def _fit(values, reserved=0):
    """The leading values that still fit one bounded query beside ``reserved`` words of the other group."""
    kept = []
    for value in values:
        if _words(kept + [value]) + reserved > MAX_QUERY_WORDS:
            break
        kept.append(value)
    return kept or values[:1]


def _or_group(values):
    quoted = ['"%s"' % value if ' ' in value else value for value in values]
    return quoted[0] if len(quoted) == 1 else '(' + ' OR '.join(quoted) + ')'


def head_and_modifiers(names):
    """(head nouns, modifiers) of the article names: 'grill basket', 'barbecue basket' -> (['basket'], ['grill',
    'barbecue']). A one-word name is a head noun."""
    heads, modifiers = [], []
    for name in names:
        words = name.split()
        if words[-1] not in heads:
            heads.append(words[-1])
        for word in words[:-1]:
            if word not in modifiers and word not in heads and word not in STOP:
                modifiers.append(word)
    return heads, modifiers


# ----- title phrases (r5d25, new tasks with ``design_query_revision``) -----------------------------------------------
# Owner direction (2026-10-15): reliability through fewer, more precise candidates, not wider searches. The head-noun x
# modifier group read newest first was the noise: "(teaser OR wand OR toy) AND (cat OR interactive OR electric OR
# pet)" returned trailer connectors, building blocks, ride-on cars and vacuum wands (B0GLNPC6K8: 100 results, 2
# selected). Quoted title phrases with the product's own category name and without the upper category ("pet toy")
# return only the same article: a live check gave 56 cat toys holding all four selected designs, and 21 grill baskets
# holding all five graded ones (the old pair of queries: 105 and 32).
TITLE_PHRASES_REVISION = 'title-phrases-v1'
PHRASES_PROBLEM = PROBLEM_PREFIX + 'design-phrases'
# a broad name whose modifiers are all such words names a wider category than the article ("pet toy", "kitchen tool")
UPPER_MODIFIERS = frozenset({'pet', 'pets', 'animal', 'animals', 'kitchen', 'household', 'home', 'house', 'outdoor',
                             'indoor', 'garden', 'kid', 'kids', 'child', 'children', 'baby', 'general', 'multipurpose',
                             'party', 'office', 'travel', 'sport', 'sports', 'camping', 'novelty'})
LEVELS = (('specific', '具体叫法'), ('category', '品类名'), ('upper', '未检索的上位名'),
          ('design_excluded', '外观不检索、只用于发明检索的宽泛名'))


def phrases_enabled(task) -> bool:
    return isinstance(task, dict) and task.get('design_query_revision') == TITLE_PHRASES_REVISION


def name_levels(concepts, *, guard=False):
    """(specific, category, upper) article names. A broad name is the product's own category when it ends in the head
    noun of a specific name and has a modifier of its own ("cat toy" beside "interactive cat toy", "barbecue basket"
    beside "rolling grill basket"); otherwise it is an upper category ("pet toy", "basket", "cooking accessory").

    r7 (``guard``, search-guard-v1 tasks; owner decision 2026-10-16): a category name must also share a word with at
    least half of the specific names. Run B0GFNWR8FW: "cosmetic applicator" and "makeup applicator" end in the head
    noun of "eyeliner applicator" and passed, the design query returned 230 results, only the first 100 were read and
    nine eyeliner designs never became candidates; without them the query returns 15, all eyeliner. Such a name is
    returned as a fourth level by ``design_name_levels``."""
    specific, category, upper, _ = design_name_levels(concepts, guard=guard)
    return specific, category, upper


def design_name_levels(concepts, *, guard=False):
    """(specific, category, upper, design_excluded); ``design_excluded`` is empty unless ``guard``."""
    rows = concepts['article_names']
    specific = [row['value'] for row in rows if not row.get('broad')]
    heads = {value.split()[-1] for value in specific} or {row['value'].split()[-1] for row in rows}
    core = None
    if guard:
        from search_guard import core_words
        core = core_words(specific)
    category, upper, excluded = [], [], []
    for row in rows:
        if not row.get('broad'):
            continue
        words = row['value'].split()
        if len(words) < 2 or words[-1] not in heads or all(word in UPPER_MODIFIERS for word in words[:-1]):
            upper.append(row['value'])
        elif core is not None and specific:
            from search_guard import shares_core
            (category if shares_core(row['value'], core) else excluded).append(row['value'])
        else:
            category.append(row['value'])
    return specific, category, upper, excluded


def title_phrases(specific, category):
    """The quoted phrases of the one design query: names of two or more words, a name dropped when a shorter listed
    phrase is part of it (a title holding "interactive cat toy" already holds "cat toy")."""
    names = list(dict.fromkeys([value for value in specific + category if len(value.split()) >= 2]
                               or specific + category))
    return [value for value in names
            if not any(other != value and (' %s ' % other) in (' %s ' % value) for other in names)]


def _levels_note(specific, category, upper, excluded=()):
    parts = ['%s：%s' % (label, '、'.join('"%s"' % value for value in values))
             for values, (_, label) in zip((specific, category, upper, list(excluded)), LEVELS) if values]
    return ('。' + '；'.join(parts)) if parts else ''


def recorded_levels(task):
    """{specific, category, upper} as the task's design-phrases term recorded them, or None (no such term)."""
    for row in (task or {}).get('query_terms') or []:
        if isinstance(row, dict) and row.get('discovery_problem_id') == PHRASES_PROBLEM:
            reason = str(row.get('discovery_problem_reason') or '')
            levels = {}
            for key, label in LEVELS:
                match = re.search(label + r'：([^；]*)', reason)
                levels[key] = [value.strip().lower() for value in re.findall(r'"([^"]+)"', match.group(1))] if match else []
            return levels
    return None


def compose_terms(concepts, title_source='product.title', *, phrases=False, guard=False):
    """Plan query terms (recorder shape) from validated concept groups.

    The design names group leaves out the broad category names (cat toy, pet toy): in a crowded category they fill
    the first 100 results by relevance (a live check: 428 results, none of the first 100 a cat teaser); they still
    feed the broad head-noun group, which is read newest first.

    r5d25 (``phrases``, title-phrases-v1 tasks): one design query of quoted title phrases - the specific names and the
    product's own category names, never an upper category - read by relevance; the utility groups use the same names.

    r7 (``guard``, search-guard-v1 tasks): the design query leaves out the category names that share no word with the
    product's own names (``design_name_levels``); the utility groups keep them, their function words narrow the field
    (run B0GFNWR8FW: US10004318B1 and US20090293905A1, both rated 中, came only through "cosmetic applicator")."""
    names = [row['value'] for row in concepts['article_names']]
    specific = [row['value'] for row in concepts['article_names'] if not row.get('broad')] or names
    source = concepts['article_names'][0]['derived_from'] if concepts['article_names'] else title_source
    terms = []
    def add(value, group, problem, reason, derived_from):
        terms.append({'value': value, 'kind': 'design' if group == 'design' else 'function', 'language': 'en',
                      'derived_from': derived_from, 'strategy': 'boolean', 'recall_group': group,
                      'discovery_problem_id': PROBLEM_PREFIX + problem, 'discovery_problem_reason': reason,
                      'different_from_purpose_id': PROBLEM_PREFIX + 'listing-phrase'})
    if phrases:
        own, category, upper, excluded = design_name_levels(concepts, guard=guard)
        listed = _fit(title_phrases(own or names, category))
        add(_or_group(listed), 'design', 'design-phrases',
            '美国外观设计的文字只有标题和一句权利要求，按专利标题里这类产品的品名词组（含本品所属品类名，不含更上位的名称）'
            '检索同类外观，按相关度取前 100 条' + _levels_note(own, category, upper, excluded), source)
        # the utility groups keep the unguarded list, in the understanding's own order
        utility = _fit(title_phrases(own or names, design_name_levels(concepts)[1])) if excluded else listed
        for index, concept in enumerate(concepts['function_concepts'][:MAX_FUNCTION_QUERIES], start=1):
            forms = _fit(concept['terms'], 2)
            add(_or_group(_fit(utility, _words(forms) + 1)) + ' AND ' + _or_group(forms), 'patent', 'function-%d' % index,
                '同类物品且涉及核心功能“%s”的美国发明专利' % concept['label'], concept['derived_from'])
        if not concepts['function_concepts']:
            add(_or_group(utility), 'patent', 'article-names', '按专利常用品名检索同类物品的美国发明专利', source)
        return terms
    add(_or_group(_fit(specific)), 'design', 'design-names',
        '美国外观设计的文字只有标题和一句权利要求，按专利对这类产品的具体叫法检索同类外观', source)
    heads, modifiers = head_and_modifiers(names)
    heads = _fit(heads, MAX_QUERY_WORDS // 2)
    modifiers = _fit(modifiers, _words(heads) + 1)
    if heads and modifiers and not concepts.get('program_fallback'):
        add(_or_group(heads) + ' AND ' + _or_group(modifiers), 'design', 'design-broad',
            '品名的中心词与修饰词分别取同义写法，覆盖标题用词不同的同类外观', source)
    # utility full text: the broad names come first (the function words already narrow the field), then specific ones
    broad_first = [row['value'] for row in concepts['article_names'] if row.get('broad')] + specific
    broad_first = list(dict.fromkeys(broad_first))
    for index, concept in enumerate(concepts['function_concepts'][:MAX_FUNCTION_QUERIES], start=1):
        forms = _fit(concept['terms'], 2)
        add(_or_group(_fit(broad_first, _words(forms) + 1)) + ' AND ' + _or_group(forms), 'patent', 'function-%d' % index,
            '同类物品且涉及核心功能“%s”的美国发明专利' % concept['label'], concept['derived_from'])
    if not concepts['function_concepts']:
        add(_or_group(_fit(names)), 'patent', 'article-names', '按专利常用品名检索同类物品的美国发明专利', source)
    return terms


def program_concepts(title_phrase, source='product.title', *, narrow=False):
    """The fallback when the model gives no usable groups: the listing's own product phrase as the only name.

    r5d21 (precision-v1, ``narrow``): only the whole phrase. Its last two words ("cat toy") and the head/modifier group
    built from it ("toy AND (butterfly OR cat)") returned every cat toy (run B0GLNPC6K8: 276 candidates)."""
    value = _clean(title_phrase, words=3)
    if not value:
        return None
    words = value.split()
    names = [value] + ([' '.join(words[-2:])] if len(words) == 3 and not narrow else [])
    concepts = {'article_names': [{'value': name, 'derived_from': source} for name in dict.fromkeys(names)],
                'function_concepts': []}
    if narrow:
        concepts['program_fallback'] = True
    return concepts


CONCEPT_PROMPT = (
    '另给 search_concepts 对象（美国专利与外观设计检索用，英文）：article_names（数组 3-8 项，每项 {value, derived_from}：'
    '专利文献对这类产品整体的常用叫法，1-3 个英文单词，先给具体叫法，再给更上位的品类名，上位品类名加 broad: true，'
    '例如 rolling grill basket 还应给 grill basket、grilling basket、barbecue basket、roasting basket；电动蝴蝶逗猫棒应给 '
    'cat teaser、teaser wand、cat wand、interactive cat toy、electric cat teaser，以及 broad 的 cat toy、pet toy）；function_concepts（数组 2-4 项，每项 {label: 中文概念名, terms: 2-5 个英文单词或两词短语，是同一概念'
    '的不同写法, derived_from}：产品区别于普通同类品的核心功能或机构，取自标题或任意一条卖点，例如 电机驱动：motor、motorized、'
    'electric、driven；旋转：rotate、rotating、rotation、spin；触碰唤醒：touch、sensor、wake）。不要宣传词、品牌名、颜色、'
    '尺寸或材质商品名。')


# r7 (search-guard-v1): the eyeliner run listed "cosmetic applicator" and "makeup applicator" beside the eyeliner names
GUARD_CONCEPT_NOTE = ('article_names 里 cosmetic applicator、makeup applicator、kitchen tool 这类同时指许多不同物品'
                      '（粉扑、刷子、海绵……）的领域总称一律标 broad: true。')


# ----- refinement with the reviewer's own words (auto_refine) -------------------------------------------------------
REFINE_PROMPT = (
    'next_action 为 refine 时另给 refine_query：{"names": [专利常用品名，1-3 个英文单词，至少 1 项], "functions": [可选，同一功能'
    '概念的不同写法，英文单词或两词短语]}，用来覆盖你在 excluded_by_narrowing 里指出的漏检；不要宣传词和品牌名。'
    'names 给这类产品的具体叫法，不要给 pet toy、cat toy、grill basket 这类上位品类名：外观检索按相关度排序，上位名会被'
    '大量泛称结果占满。')


def parse_refine_query(value):
    """(names, functions) of a reviewer's refine_query, or None when absent or unusable."""
    if not isinstance(value, dict):
        return None
    names = [name for name in (_clean(item, words=3) for item in value.get('names') or []) if name]
    functions = [form for form in (_clean(item, words=2) for item in value.get('functions') or []) if form]
    names, functions = list(dict.fromkeys(names))[:MAX_ARTICLE_NAMES], list(dict.fromkeys(functions))[:MAX_FORMS]
    if not names:
        return None
    return names, functions


def refine_value(right, names, functions):
    if right == 'design' or not functions:
        return _or_group(names)
    return _or_group(names) + ' AND ' + _or_group(functions)
