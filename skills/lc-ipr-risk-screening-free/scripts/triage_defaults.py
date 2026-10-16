#!/usr/bin/env python3
"""Program default triage for public cards that are not rights candidates (best-estimate-risk-v2 tasks).

Two deterministic rules, recorded through the ordinary triage recorder with reviewer
``program:triage-defaults`` (the Agent may re-triage any of them later through the usual change path):

(a) same product: a public retail or image card whose title/address names the reference brand together with
    the product-name stem, repeats the listing title, or carries the task ASIN is the product's own sales page or
    photograph source, not an independent right -> not_selected;
(b) identity-less web card: an imageless public web result (``host_triage.text_only_lead``) with readable text
    that names no publication / registration / case number and no reference brand or product name -> not_selected;
(c) third-party marketplace listing (tasks with ``discovery_refinement_revision``): a public card whose address is a
    retail marketplace product page (Amazon, eBay, Walmart, Etsy, Temu, AliExpress ...) and whose text names no
    publication / registration / case number and no enforcement event is another seller's sales display of a
    similar product, not a rights record -> not_selected (r5c real run: 16 such images selected by the visual host,
    each then demanding an identity investigation no listing can answer). A card that shows a number or a claim
    still goes to the hosts.

(d) core-focus tasks (``core_focus_revision``, r5d2): a public card with no right identity at all (no publication /
    registration / case number, no enforcement event) is not a rights candidate wherever it was found -> not_selected
    ('no_rights_identity'); a Google Patents page found by a web search is a patent document, not an enforcement or
    copyright record -> not_selected in that scope ('patent_page'); and two objective patent facts
    (``core_focus``): a US filing whose own dates prove the term is over ('expired'), and a WO / foreign
    publication in a US-only task ('family_duplicate' when a US member of the same family is a candidate,
    'foreign_publication' otherwise). r5d real run: these were 15 of the 30 selected candidates.

(e) precision-v1 tasks (r5d21): a US patent or design whose own SerpApi search card reports the US status NOT_ACTIVE
    ('inactive_us_status'; run B0GLNPC6K8: 50 of 100 utility cards, 16 of the 29 it selected).

Apart from (d) and (e), nothing with a right type (patent, design, trademark ...) is touched here; those go to the hosts.
A card without enough readable text is left for the hosts. Every rejection by the recorder is reported, never
retried as a different decision.

usage: triage_defaults.py --task-dir RUN [--dry-run]
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from common import load_json, sha256_json

REVIEWER = 'program:triage-defaults'
OUTPUT_DIR = 'triage-defaults'
PUBLIC_CARD_NATURES = frozenset({'web_result', 'visual_match'})
SAME_PRODUCT_REASON = '同一商品的销售页面或图片来源，不是权利候选'
WEB_CARD_REASON = '公开网页卡片未载明具体权利编号、案号、权利人或与本商品的关联，不是可比较的权利候选'
REOPEN_SAME_PRODUCT = ['出现该来源的具体权利主张、登记记录或维权材料时重新分流',
                       '产品对象、拟用标识或摄影使用范围变化时重新分流']
REOPEN_WEB_CARD = ['出现与本商品、参考品牌或已定位权利编号相关的具体维权或权利材料时重新分流',
                   '候选公开内容、来源回执或产品对象变化时重新分流']
# A publication, registration or case identity anywhere on the card keeps it for the judgment hosts.
IDENTITY_PATTERN = re.compile(
    r'\b(?:US|EP|WO|CN|JP|DE|GB|FR|KR)\s?\d{4,}|\bUSD\s?\d{4,}|\b[DdRr][Ee]?\s?\d{5,}\b|\b\d{1,2}:\d{2}-cv-\d+'
    r'|\bcase\s+no\b|\bno\.\s*\d{3,}|\bv\.\s|\bvs\.?\s|\bpatent\s+(?:no|number)\b|\breg(?:istration)?\.?\s+no\b'
    r'|\bserial\s+no\b|专利号|注册号|案号', re.I)
ENFORCEMENT_WORDS = re.compile(r'lawsuit|litigation|infring|counterfeit|takedown|cease and desist|complaint|侵权|诉讼|投诉', re.I)
# r6 (report-always-v1): Amazon sellers are sued in "Schedule A" cases with a temporary restraining order (TRO); a card
# naming one goes to the triage hosts like any other enforcement card
ENFORCEMENT_WORDS_R6 = re.compile(ENFORCEMENT_WORDS.pattern + r'|schedule\s*a\b|temporary restraining order|\bTRO\b|冻结', re.I)


def _enforcement(text: str, identity: dict | None) -> bool:
    return bool((ENFORCEMENT_WORDS_R6 if (identity or {}).get('r6') else ENFORCEMENT_WORDS).search(text))
MARKETPLACE_REASON = '第三方零售平台的商品销售页或其图片，是同类商品的销售展示，不是权利登记、权利主张或维权材料'
REOPEN_MARKETPLACE = ['该页面出现具体专利号、注册号、版权登记或侵权／维权主张时重新分流',
                      '发现拟用图片或包装与该页图片相同（照片复用）时重新分流']
MARKETPLACE_HOST = re.compile(
    r'(?:^|\.)(?:amazon|ebay|walmart|target|etsy|temu|aliexpress|alibaba|1688|wish|lowes|homedepot|wayfair|bestbuy'
    r'|kohls|macys|shein|mercari|poshmark|rakuten|shopee|lazada|jd|tmall|taobao|made-in-china|dhgate|costco'
    r'|samsclub|overstock|kroger|bedbathandbeyond|qvc|newegg|zulily|ozon|allegro|cdiscount|otto)\.[a-z.]+$', re.I)
TITLE_STOP = frozenset({'the', 'a', 'an', 'for', 'with', 'and', 'of', 'to', 'in', 'by', '-', '|', ',', ':'})
MIN_TEXT = 40
# Patent databases: a page there is a patent document, whatever words its snippet carries.
PATENT_PAGE_HOST = re.compile(
    r'(?:^|\.)(?:patents\.google\.com|patft\.uspto\.gov|ppubs\.uspto\.gov|image-ppubs\.uspto\.gov|patents\.justia\.com'
    r'|freepatentsonline\.com|patentimages\.storage\.googleapis\.com|eureka\.patsnap\.com|patsnap\.com|lens\.org'
    r'|worldwide\.espacenet\.com|patentscope\.wipo\.int|patentguru\.com'
    r'|patents\.glgoo\.top|trea\.com)$', re.I)
NO_IDENTITY_REASON = '公开卡片没有任何权利编号、登记号、案号或维权事件，不是可比较的权利候选'
REOPEN_NO_IDENTITY = ['该来源出现具体权利编号、登记记录或侵权／维权主张时重新分流',
                      '发现拟用图片、文字或包装与该来源相同（素材复用）时重新分流']
PATENT_PAGE_REASON = '网页检索返回的是专利文献页面，不是维权记录或作品来源；专利本身由专利检索路线核验'
REOPEN_PATENT_PAGE = ['该页面所示专利出现在专利检索结果或产品页面标注中时，按专利候选核验',
                      '出现该专利的维权、诉讼或投诉材料时重新分流']
EXPIRED_REASON = '按候选自身日期计算，美国保护期已届满，不能对本商品构成现时专利风险'
REOPEN_EXPIRED = ['取得该文献存在更晚有效申请日、再颁或期限延长的官方记录时重新分流',
                  '候选身份或日期信息被更正时重新分流']
INACTIVE_REASON = '检索记录显示该文献在美国已失效，不能对本商品构成现时专利风险'
REOPEN_INACTIVE = ['取得该文献在美国仍然有效（含恢复、再颁或期限延长）的官方记录时重新分流',
                   '出现以该文献主张权利的投诉或诉讼时重新分流']
FOREIGN_REASON = '国际申请或外国公开文献本身在美国没有专利效力'
REOPEN_FOREIGN = ['发现该文献的美国同族（美国申请、授权或国家阶段）时，以美国文献重新分流',
                  '任务目标国家增加该文献所属国家或地区时重新分流']
FOCUS_RULES = frozenset({'no_rights_identity', 'patent_page', 'expired', 'family_duplicate', 'foreign_publication'})


def _norm(value) -> str:
    return ' '.join(re.findall(r'[a-z0-9一-鿿]+', str(value or '').lower()))


def _stem(title: str) -> str:
    """The product-name stem: the leading words of the listing title before the first connective."""
    words = []
    for word in re.split(r'[\s,|:;()\-]+', str(title or '')):
        if not word:
            continue
        if word.lower() in TITLE_STOP and words:
            break
        words.append(word)
        if len(words) == 4:
            break
    return _norm(' '.join(words))


def product_identity(task: dict) -> dict:
    product = task.get('product') or {}
    brand = '' if product.get('brand_placeholder') else _norm(product.get('brand'))
    title = _norm(product.get('title'))
    words = title.split()
    asins = {str(product.get(key) or '').upper() for key in ('requested_asin', 'actual_asin', 'asin')}
    asins = {value for value in asins if re.fullmatch(r'[A-Z0-9]{10}', value)}
    import report_always
    return {'r6': report_always.enabled(task), 'brand': brand, 'stem': _stem(product.get('title')),
            'title_prefix': ' '.join(words[:8]) if len(words) >= 5 else '', 'asins': sorted(asins)}


def _card_text(candidate: dict, *keys) -> str:
    return ' '.join(str(candidate.get(key) or '') for key in keys)


def same_product(candidate: dict, identity: dict) -> bool:
    if _enforcement(_card_text(candidate, 'title', 'snippet'), identity) or IDENTITY_PATTERN.search(
            _card_text(candidate, 'title', 'snippet')):
        return False                       # an enforcement or rights card about the product goes to the hosts
    title = _norm(candidate.get('title'))
    address = str(candidate.get('url') or candidate.get('link') or candidate.get('source_url') or '')
    text = title + ' ' + _norm(address)
    if any(asin in address.upper() or asin.lower() in title for asin in identity['asins']):
        return True
    if identity['title_prefix'] and identity['title_prefix'] in title:
        return True
    return bool(identity['brand'] and identity['stem'] and identity['brand'] in text and identity['stem'] in text)


def identity_less_web_card(candidate: dict, identity: dict) -> bool:
    from host_triage import text_only_lead
    if not text_only_lead(candidate):
        return False
    readable = _card_text(candidate, 'title', 'snippet')
    if len(readable.strip()) < MIN_TEXT:
        return False                       # a bare title can never support an exclusion
    raw = _card_text(candidate, 'title', 'snippet', 'url')
    if IDENTITY_PATTERN.search(raw):
        return False
    text = _norm(raw)
    return not any(value and value in text for value in (identity['brand'], identity['stem']))


def marketplace_listing(candidate: dict, identity: dict | None = None) -> bool:
    from urllib.parse import urlsplit
    text = _card_text(candidate, 'title', 'snippet')
    if _enforcement(text, identity) or IDENTITY_PATTERN.search(text):
        return False
    for key in ('url', 'link', 'source_url'):
        try:
            host = urlsplit(str(candidate.get(key) or '')).hostname or ''
        except ValueError:
            continue
        if host and MARKETPLACE_HOST.search(host.lower()):
            return True
    return False


def _hosts(candidate: dict):
    from urllib.parse import urlsplit
    for key in ('url', 'link', 'source_url'):
        try:
            host = urlsplit(str(candidate.get(key) or '')).hostname or ''
        except ValueError:
            continue
        if host:
            yield host.lower()


def focus_rule(candidate: dict, task: dict, others, *, today=None):
    """(rule, detail) of the core-focus defaults, or None."""
    import core_focus
    if candidate.get('right_type') in {'patent', 'utility_model', 'design'}:
        reason = core_focus.expired_by_age(candidate, today=today)
        if reason:
            return 'expired', reason
        found = core_focus.foreign_publication(candidate, task, others)
        return found
    if candidate.get('right_type') not in (None, '', 'unknown') or candidate.get('candidate_nature') not in PUBLIC_CARD_NATURES:
        return None
    if candidate.get('publication_number') or candidate.get('registration_number') or candidate.get('serial_number'):
        return None
    if any(PATENT_PAGE_HOST.search(host) for host in _hosts(candidate)):
        return 'patent_page', None
    text = _card_text(candidate, 'title', 'snippet', 'url')
    if len(_card_text(candidate, 'title', 'snippet').strip()) < MIN_TEXT and candidate.get('candidate_nature') == 'web_result':
        return None                        # a bare title can never support an exclusion
    if IDENTITY_PATTERN.search(text) or ENFORCEMENT_WORDS.search(_card_text(candidate, 'title', 'snippet')):
        return None
    return 'no_rights_identity', None


def rule_for(candidate: dict, identity: dict, *, marketplace: bool = False):
    """'same_product', 'web_card', 'marketplace' or None. Typed rights are never decided here."""
    if candidate.get('right_type') not in (None, '', 'unknown'):
        return None
    if candidate.get('publication_number') or candidate.get('registration_number') or candidate.get('serial_number'):
        return None
    if candidate.get('candidate_nature') not in PUBLIC_CARD_NATURES:
        return None
    if same_product(candidate, identity):
        return 'same_product'
    if identity_less_web_card(candidate, identity):
        return 'web_card'
    if marketplace and marketplace_listing(candidate, identity):
        return 'marketplace'
    return None


def pending_entries(root: Path) -> list[dict]:
    from workflow_v24 import work_view_from_dir
    return [entry for entry in work_view_from_dir(root)['entries']
            if entry.get('kind') == 'triage' and entry.get('candidate_id')
            and entry.get('state') in {'ready', 'awaiting_review'}]


def build_decisions(root: Path) -> tuple[list[dict], list[dict]]:
    """(decisions ready for the recorder, skipped entries with the reason)."""
    from annotate_materiality import candidate_index
    from assessment_estimate import best_estimate_v2, validate_supplement
    from decision_workflow import evidence_index
    from input_template import triage_decision
    from workflow_v24 import scenario_supplement
    import product_scope as ps
    root = Path(root)
    task = load_json(root / 'task.json')
    if not best_estimate_v2(task):
        raise ValueError('TRIAGE_DEFAULTS_REQUIRE_BEST_ESTIMATE_V2')
    candidates = load_json(root / 'normalized-candidates.json')
    index, errors = candidate_index(candidates)
    if errors:
        raise ValueError('TRIAGE_DEFAULTS_CANDIDATES_INVALID')
    evidence = load_json(root / 'evidence.json')
    supplement = scenario_supplement(root, task=task, evidence=evidence)
    registry = {**evidence_index(evidence, supplement),
                **validate_supplement(supplement, root, task=task, evidence=evidence)}
    scope_data = ps.scope(task) if ps.enabled(task) else {'objects': []}
    descriptions = {row['object_id']: row.get('description') or row['object_id'] for row in scope_data.get('objects', [])}
    identity = product_identity(task)
    from auto_refine import enabled as marketplace_rule
    import core_focus
    marketplace = marketplace_rule(task)
    focus = core_focus.enabled(task)
    import precision
    statuses = precision.card_statuses(root) if precision.enabled(task) else {}
    patents = [row for name in ('patents', 'designs') for row in (candidates.get(name) or []) if isinstance(row, dict)]
    decisions, skipped, seen = [], [], set()
    for entry in pending_entries(root):
        key = tuple(entry.get(name) for name in ('candidate_id', 'scenario_id', 'jurisdiction', 'right_type'))
        if key in seen:
            continue
        seen.add(key)
        bound = index.get(entry['candidate_id'])
        if bound is None:
            continue
        candidate = bound[1]
        rule, detail = rule_for(candidate, identity, marketplace=marketplace), None
        if rule is None and focus:
            found = focus_rule(candidate, task, patents)
            rule, detail = found if found else (None, None)
        if rule is None and statuses:
            detail = precision.inactive_us_status(candidate, statuses)
            rule = 'inactive_us_status' if detail else None
        if rule is None:
            continue
        template, guide = triage_decision(task, candidates, entry)
        ready = (guide or {}).get('included_product_objects') if isinstance(guide, dict) else None
        if template is None or not ready:
            skipped.append({'candidate_id': entry['candidate_id'], 'reason': 'NO_INCLUDED_PRODUCT_OBJECT'})
            continue
        refs = list(dict.fromkeys([ref for ref in candidate.get('evidence_refs', []) if ref in registry]
            + [ref.get('evidence_id') for ref in candidate.get('sources', [])
               if isinstance(ref, dict) and ref.get('evidence_id') in registry]))
        if not refs:
            skipped.append({'candidate_id': entry['candidate_id'], 'reason': 'NO_REGISTERED_EVIDENCE'})
            continue
        chosen = sorted(ready)
        directions = sorted({direction for object_id in chosen for direction in ready[object_id]})
        product_text = '；'.join(str(descriptions.get(object_id, object_id)) for object_id in chosen)[:900]
        card = ' ｜ '.join(filter(None, (str(candidate.get('publication_number') or '').strip(),
                                         str(candidate.get('title') or '').strip(),
                                         str(candidate.get('snippet') or candidate.get('abstract') or '').strip(),
                                         str(candidate.get('url') or '').strip())))[:900]
        reading = 'result_record'
        if rule in {'expired', 'family_duplicate', 'foreign_publication', 'inactive_us_status'}:
            from host_triage import reading_profile
            reading = reading_profile(candidate)[0]
            relationship = detail + '。'
            if rule == 'expired':
                difference = '候选的保护期已届满，不再能对拟售产品主张专利权；技术内容与产品的关系不再影响本次决策。'
                reason, reopen = EXPIRED_REASON, REOPEN_EXPIRED
            elif rule == 'inactive_us_status':
                difference = '检索记录显示该文献在美国已不再有效，不能对拟售产品主张专利权；技术内容与产品的关系不再影响本次决策。'
                reason, reopen = INACTIVE_REASON, REOPEN_INACTIVE
            else:
                difference = '该文献不是美国专利，不能在美国对拟售产品主张权利；美国效力只能由美国文献承担。'
                reason, reopen = FOREIGN_REASON, REOPEN_FOREIGN
        elif rule == 'patent_page':
            relationship = '卡片地址是专利文献检索网站上的专利页面，卡片未载明维权、诉讼或投诉事件。'
            difference = '专利文献页面不是本情景要找的维权记录或作品来源；专利本身是否相关由专利检索与分流判断。'
            reason, reopen = PATENT_PAGE_REASON, REOPEN_PATENT_PAGE
        elif rule == 'no_rights_identity':
            relationship = '卡片为公开网页或图片结果，标题、摘要与地址均未载明权利编号、登记、案号或维权事件。'
            difference = '同类商品的展示或一般网页信息不是权利记录；本情景不复用他人图片、文字或包装。'
            reason, reopen = NO_IDENTITY_REASON, REOPEN_NO_IDENTITY
        elif rule == 'same_product':
            relationship = ('卡片标题或地址指向同一商品（参考品牌与商品名称、相同标题或相同ASIN），'
                            '是该商品自身的销售页面或图片来源。')
            difference = '该卡片不是独立的权利记录或第三方作品，只复现同一商品的销售展示；本情景不复用其摄影和参考标识。'
            reason, reopen = SAME_PRODUCT_REASON, REOPEN_SAME_PRODUCT
        elif rule == 'marketplace':
            relationship = '卡片地址是第三方零售平台的商品页，标题与摘要只描述在售商品，未载明权利编号、登记或维权事件。'
            difference = '该卡片是其他卖家的同类商品销售展示，不是独立的权利记录；同类商品在售本身不构成权利候选。'
            reason, reopen = MARKETPLACE_REASON, REOPEN_MARKETPLACE
        else:
            relationship = '卡片为公开网页结果，正文未载明权利编号、案号、权利人或与本商品、参考品牌的关联。'
            difference = '卡片内容属于一般性网页信息，未描述针对本商品或其结构的具体权利或维权事件。'
            reason, reopen = WEB_CARD_REASON, REOPEN_WEB_CARD
        gaps = list(guide.get('identity_gaps_prefilled_are_the_minimum', []))
        relation = {'product_object_ids': chosen, 'direction_ids': directions, 'scope_reason': relationship,
                    'evidence_refs': refs, 'identity_gaps': gaps}
        if gaps:
            relation['identity_location'] = {
                'reason': '公开卡片未定位具体权利身份及目标效力（缺口：' + '、'.join(gaps) + '）',
                'affected_work': '准确权利身份、地域及效力',
                'next_action': '保留原件及未知；出现具体权利主张或登记记录时重开，不派生未定位出网核验'}
        decision = {name: template[name] for name in ('candidate_id', 'scenario_id', 'jurisdiction', 'right_type')}
        decision.update(decision='not_selected', reason=reason, reviewer=REVIEWER, reading_level=reading,
            basis_summary=('程序默认分流（' + {'same_product': '同一商品来源', 'marketplace': '第三方零售商品页',
                                          'expired': '保护期已届满', 'inactive_us_status': '检索记录显示美国已失效',
                                          'family_duplicate': '非美国同族文献',
                                          'foreign_publication': '非美国公开文献', 'patent_page': '专利文献页面',
                                          'no_rights_identity': '无权利身份卡片'}.get(rule, '无身份网页卡片')
                           + '）：依据卡片标题、摘要和地址；' + relationship)[:600],
            reopen_conditions=list(reopen), evidence_refs=refs, candidate_relation=relation,
            comparison={'candidate_content': card or relationship, 'product_content': product_text or relationship,
                        'relationship': relationship, 'difference': difference,
                        'applicability_limit': '仅依据卡片已读内容，限于本情景、国家和已比较的产品对象；'
                                               '未入选不等于法律不侵权，后续出现具体权利材料时重新分流。'},
            default_rule=rule)
        decisions.append(decision)
    return decisions, skipped


def record(root: Path, decisions: list[dict]) -> dict:
    from provider_utils import evidence_lock
    from text_triage_host import _record_isolating
    root = Path(root)
    if not decisions:
        return {'recorded': 0, 'rejected': []}
    directory = root / OUTPUT_DIR / sha256_json(decisions)[:16]
    directory.mkdir(parents=True, exist_ok=True)
    # the recorder takes only its own fields; the rule name stays in the retained decisions file
    clean = [{key: value for key, value in row.items() if key != 'default_rule'} for row in decisions]
    with evidence_lock(root):
        recorded, rejected = _record_isolating(root, clean, directory, 'triage-defaults')
    return {'recorded': recorded, 'rejected': rejected}


def run(root: Path, *, dry_run: bool = False) -> dict:
    # New candidates become pending triage only after they are linked to the product scope; the text host links
    # first and then judges, so the defaults must link first too or they never see the cards they exist for.
    if not dry_run:
        try:
            import candidate_scope_link
            candidate_scope_link.auto_link(Path(root))
        except (ValueError, OSError, KeyError, TypeError):
            pass
    decisions, skipped = build_decisions(root)
    rules = {}
    for row in decisions:
        rules[row['default_rule']] = rules.get(row['default_rule'], 0) + 1
    if dry_run:
        return {'dry_run': True, 'would_record': len(decisions), 'by_rule': rules, 'skipped': skipped,
                'candidates': [row['candidate_id'] for row in decisions]}
    outcome = record(root, decisions)
    return {**outcome, 'by_rule': rules, 'skipped': skipped}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--task-dir', type=Path, required=True)
    parser.add_argument('--dry-run', action='store_true', help='List the decisions without recording them')
    args = parser.parse_args()
    print(json.dumps(run(args.task_dir.resolve(), dry_run=args.dry_run), ensure_ascii=False, separators=(',', ':')))


if __name__ == '__main__':
    main()
