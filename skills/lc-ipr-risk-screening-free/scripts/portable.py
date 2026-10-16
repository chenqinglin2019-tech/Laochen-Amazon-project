"""r9 (portable-v1, owner decisions 2026-10-16): small, separately testable corrections for sharing the skill.

The owner's two r8 runs (B0GJD92G1K, B0FHQ475MY) were correct; the owner asked for no large change to the logic or the
flow. New tasks carry ``portable_revision`` and get:

* an honest design search boundary: a query that hit its single-request limit says that later results were not
  read (B0FHQ475MY: 529 hits, the first 100 read - the review had written "designs granted after 2024-12-03 are
  outside this search"), a complete one names the Google indexing lag (``module_review.design_search_coverage``);
* EU / JP step 1: the target country follows the listing's marketplace when the run names none (``run_pipeline``);
  checkpoint 1 names the national scopes (DE/FR/IT/ES/JP) the program cannot search because it generates no
  local-language terms, and the limitation the time box closes them with says exactly that (``time_box.limitation``)
  instead of "the time budget ran out";
* a national design lifetime of 25 years outside the US for the SerpApi priority filter (``recall.serpapi_params``).

Fixes that only change behaviour on Windows, or that only route a download through the user's own proxy when no
fake-IP proxy is present, apply to every task (they change no judgment).
"""
from __future__ import annotations

REVISION = 'portable-v1'
TASK_FIELD = 'portable_revision'
# workflow_v24.LANGUAGES (frozen): scopes whose text queries must be written in the local language
LOCAL_LANGUAGE_SCOPES = {'FR': 'fr', 'DE': 'de', 'IT': 'it', 'ES': 'es', 'JP': 'ja'}
LANGUAGE_NAMES = {'fr': '法语', 'de': '德语', 'it': '意大利语', 'es': '西班牙语', 'ja': '日语'}
COUNTRY_NAMES = {'US': '美国', 'GB': '英国', 'EU': '欧盟', 'FR': '法国', 'DE': '德国', 'IT': '意大利', 'ES': '西班牙',
                 'JP': '日本'}
RIGHT_NAMES = {'patent': '发明专利', 'utility_model': '实用新型', 'design': '外观', 'trademark': '文字商标',
               'trademark_word': '文字商标', 'trademark_figurative': '图形商标', 'figurative_trademark': '图形商标',
               'copyright': '版权', 'trade_dress': '商业外观', 'unregistered_design': '未注册外观', 'enforcement': '公开维权'}
# trademark discovery depends on the sale scenario (an own brand needs none), so a prediction leaves it out
SCENARIO_DEPENDENT_RIGHTS = frozenset({'trademark', 'trademark_word', 'trademark_figurative', 'figurative_trademark'})
LIMITATION_CODE = 'LOCAL_LANGUAGE_TERMS_NOT_GENERATED'


def enabled(task) -> bool:
    return isinstance(task, dict) and task.get(TASK_FIELD) == REVISION


def local_language(jurisdiction) -> str:
    return LOCAL_LANGUAGE_SCOPES.get(str(jurisdiction or '').upper(), '')


def has_local_terms(plan, jurisdiction) -> bool:
    """Whether the search plan holds any text term in the scope's required local language."""
    language = local_language(jurisdiction)
    if not language:
        return True
    for term in (plan or {}).get('terms') or []:
        if isinstance(term, dict) and str(term.get('language') or '').casefold() == language:
            return True
    return False


def unsearched_scopes(task, plan) -> list:
    """(jurisdiction, right_type) of national scopes that cannot be searched for lack of local-language terms: from
    the plan's own gaps once a plan exists, else predicted from the task's recall requirements (checkpoint 1)."""
    rows = []
    gaps = (plan or {}).get('planning_gaps') if isinstance(plan, dict) else None
    if isinstance(gaps, list):
        candidates = [(gap.get('jurisdiction'), gap.get('right_type')) for gap in gaps
                      if isinstance(gap, dict) and gap.get('code') == 'API_DISCOVERY_TERMS_MISSING']
    else:
        candidates = [(requirement.get('jurisdiction'), requirement.get('right_type'))
                      for requirement in (task or {}).get('coverage_requirements') or []
                      if isinstance(requirement, dict) and requirement.get('phase') == 'official_recall'
                      and requirement.get('right_type') not in SCENARIO_DEPENDENT_RIGHTS]
    for jurisdiction, right in candidates:
        if local_language(jurisdiction) and right and not has_local_terms(plan, jurisdiction):
            if (jurisdiction, right) not in rows:
                rows.append((jurisdiction, right))
    return rows


def scope_notice(task, plan) -> str:
    """One Chinese sentence for checkpoint 1 naming what this task will not search, or ''."""
    rows = unsearched_scopes(task, plan)
    if not rows:
        return ''
    by_country = {}
    for jurisdiction, right in rows:
        by_country.setdefault(jurisdiction, []).append(RIGHT_NAMES.get(right, right))
    parts = ['%s本国的%s' % (COUNTRY_NAMES.get(j, j), '、'.join(names)) for j, names in by_country.items()]
    languages = '、'.join(sorted({LANGUAGE_NAMES[local_language(j)] for j in by_country}))
    return ('本技能目前只生成英文检索词，%s需要用%s检索，本次不检索、没有结论（报告会列为限制，不当作低风险）。'
            % ('；'.join(parts), languages))


def market_notice(marketplace, jurisdictions) -> str:
    """A reminder when the countries named for the run do not include the listing's own marketplace."""
    market = str(marketplace or '').upper()
    targets = {str(value).upper() for value in jurisdictions or []}
    if not market or market in targets:
        return ''
    return ('链接是%s站的商品，本次却按%s排查；如果要查%s，请不带 --jurisdictions 新建任务（程序按站点取国家）。'
            % (COUNTRY_NAMES.get(market, market), '、'.join(COUNTRY_NAMES.get(t, t) for t in sorted(targets)),
               COUNTRY_NAMES.get(market, market)))


def language_limitation(task, entry, plan=None) -> str:
    """r9: the disclosed text for scope-level work of an EU/JP national scope the time box closed, when the plan holds
    no term in that country's language (the frozen language gate then plans nothing there: run rehearsal on the
    B0GJD92G1K capture re-targeted to EU+DE gave API_DISCOVERY_TERMS_MISSING / AXIS_MISSING repairs for six DE
    rights), or ''. The closure, its reason code and its proof are unchanged; only the sentence the report shows
    says what really happened. Candidate-level work keeps the time-box text."""
    if not enabled(task) or not isinstance(entry, dict) or entry.get('candidate_id'):
        return ''
    language = str(entry.get('required_language') or local_language(entry.get('jurisdiction')))
    if language not in LANGUAGE_NAMES or has_local_terms(plan, entry.get('jurisdiction')):
        return ''
    return ('本技能目前只生成英文检索词，%s本国的这一范围要用%s检索，本次没有检索、没有结论；这不代表没有相关权利，'
            '也不是低风险。' % (COUNTRY_NAMES.get(str(entry.get('jurisdiction') or ''), entry.get('jurisdiction') or ''),
                                LANGUAGE_NAMES[language]))


MODEL_MARKERS = ('model_not_found', 'model not found', 'does not exist', 'unsupported model', 'model is not supported',
                 'not supported when using codex', 'do not have access to', "don't have access to", 'no access to model',
                 'invalid model', 'unknown model')


def model_unavailable(text) -> bool:
    """r9: the review model pinned in references/review-host.json is not available to this ChatGPT account."""
    value = str(text or '').casefold()
    return 'model' in value and any(marker in value for marker in MODEL_MARKERS)


def model_notice() -> str:
    try:
        from review_isolation import review_settings
        model = review_settings().get('model') or ''
    except Exception:
        model = ''
    return ('模型会话报告模型不可用：本技能的审阅固定使用 %s（references/review-host.json）。这个 ChatGPT 账号看来用不了它，'
            '后面所有模型审阅都会失败、报告会大量待定。请用能使用该模型的账号登录 Codex 后重跑；不要手工改审阅结果。'
            % (model or '配置的模型'))
