"""r7 (search-guard-v1): the patent search of a new task always runs, with names that find the product itself.

The owner's runs of 2026-10-16 (B0GFNWR8FW eyeliner stamp pen, B0GLNPC6K8 cat teaser, B0H16FDSD8 rolling grill
basket) all published a report, yet the basket's known design USD1035381S1 was never seen. The SerpApi account
(250 searches a month, renewing 2026-10-21) had 9 searches left when the eyeliner run started and none for the other
two: their four US patent and design searches were never sent, EPO was never tried (planning only checks that
credentials exist), and both reports still led with 低. The design query itself was right: the same query returns the
design fourth of 21. In the eyeliner run the broad names "cosmetic applicator" and "makeup applicator" pushed the
design query to 230 results; only the first 100 are read, and nine eyeliner designs ("Dual-ended eyeliner stamp
device", two "Eyeliner stamp") never became candidates.

New tasks carry this marker; under it:

* the account's free Account API (no search is counted) and the local cross-task ledger are read before the run and
  again before planning; when they cannot cover the US discovery searches, those searches go to EPO, the fallback the
  owner chose on 2026-10-14, with the same count; when EPO cannot run either the run stops before it starts;
* a run whose US patent and design discovery searches all failed stops instead of publishing;
* the design query keeps only names that share a word with the product's own specific names (owner decision
  2026-10-16), and the image, web and enforcement searches use those names instead of loose feature phrases;
* candidate detail requests are capped at 8 a task, same-form designs and core utility patents first (owner
  decision 2026-10-16);
* a SerpApi request a client refused before sending (quota) is recorded as such, not as an unknown submission.

Tasks without the marker keep their exact behaviour.

r8 (search-guard-v2; the owner's r7 runs B0GLNPC6K8-US-r7 / B0H16FDSD8-US-r7, both stopped at publication with
EVIDENCE_UNRESOLVED_SCOPE_WITHOUT_LIMITATION):

* the US design route table of a new task lists EPO (coverage_v3.build_requirements): the r7 planner sent the design
  query to EPO, the frozen client refused a route the task never configured, and recording that refusal crashed the
  whole EPO batch, so the patent searches queued behind it were never sent either;
* the product-name term is a program-composed purpose (discovery_budget.dispatch_block), so its image, web and
  enforcement searches are no longer cancelled as a new purpose without a parent (v1 and v2);
* a SerpApi backup key (SERPAPI_API_KEY_BACKUP in .env, owner request 2026-10-16) is used when the main key's account
  cannot cover the task and the backup's can; the choice is recorded (never the key) and kept for the whole task.
"""
from __future__ import annotations

import json
import os
import re
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.parse import urlencode

REVISION = 'search-guard-v2'
REVISIONS = frozenset({'search-guard-v1', REVISION})
TASK_FIELD = 'search_guard_revision'
CAPACITY_FILE = 'serpapi-capacity.json'
CAPACITY_SCHEMA = 'IPR-SERPAPI-CAPACITY/1.0'
# owner decision 2026-10-16: at most 8 SerpApi candidate details a task, the likeliest risks first
DETAIL_CAP = 8
# the searches a recall task sends to Google Patents before any detail: one design query and up to three utility groups
DEFAULT_DISCOVERY_NEED = 4
NAME_RIGHTS = frozenset({'copyright', 'trade_dress', 'unregistered_design', 'enforcement'})
IMAGE_NAME_RIGHTS = frozenset({'copyright', 'trade_dress', 'unregistered_design'})


def enabled(task) -> bool:
    return isinstance(task, dict) and task.get(TASK_FIELD) in REVISIONS


def design_epo_route(task) -> bool:
    """r8: the task's US design route table lists EPO search (fixed at task creation, so only v2 tasks)."""
    return isinstance(task, dict) and task.get(TASK_FIELD) == REVISION


# ----- names -----------------------------------------------------------------------------------------------------------
STOP_WORDS = frozenset({'a', 'an', 'and', 'for', 'of', 'the', 'with', 'set', 'kit', 'pack', 'pcs'})


def _word(value: str) -> str:
    word = value.lower().strip()
    if len(word) > 4 and word.endswith(('ches', 'shes', 'xes', 'zes', 'sses')):
        return word[:-2]
    if len(word) > 3 and word.endswith('s') and not word.endswith('ss'):
        return word[:-1]
    return word


def _same(left: str, right: str) -> bool:
    if left == right:
        return True
    return min(len(left), len(right)) >= 4 and (left.startswith(right) or right.startswith(left))


def _words(name: str) -> list:
    return [_word(part) for part in re.findall(r"[A-Za-z0-9]+(?:'[A-Za-z]+)?", str(name or ''))
            if part.lower() not in STOP_WORDS]


def core_words(specific) -> list:
    """Words found in at least half of the product's specific article names (singular/plural and grill/grilling
    count as the same word): eyeliner stamp, eyeliner stamp pen, eyeliner applicator, eyeliner pen -> eyeliner, stamp,
    pen; rolling grill basket, cylindrical grill basket -> every word; cat teaser, teaser wand, cat wand, interactive
    cat toy, electric cat teaser -> cat, teaser."""
    names = [_words(name) for name in specific if _words(name)]
    if not names:
        return []
    candidates = list(dict.fromkeys(word for words in names for word in words))
    return [word for word in candidates
            if 2 * sum(any(_same(word, other) for other in words) for words in names) >= len(names)]


def shares_core(name, core) -> bool:
    return any(_same(word, other) for word in _words(name) for other in core)


# The image, web and enforcement searches of a marked task use the product's confirmed specific names (run B0GFNWR8FW:
# "stamp pen set", "dual applicator heads" and "rotating applicator"; B0GLNPC6K8: "suction cup base").
NAMES_PROBLEM = 'search-guard-v1:product-names'
NAMES_REASON = '按本品确认的具体叫法检索同款商品的图片、网页与维权信息，取代标题末尾短语和图片特征词'


def names_term(concepts):
    """One discovery term naming the product by its specific article names, or None without such names."""
    import recall
    rows = (concepts or {}).get('article_names') or []
    specific = [row['value'] for row in rows if isinstance(row, dict) and not row.get('broad') and row.get('value')]
    phrases = recall.title_phrases(specific, []) if specific else []
    if not phrases:
        return None
    return {'value': recall._or_group(recall._fit(phrases)), 'kind': 'design', 'language': 'en',
            'derived_from': 'product.title', 'strategy': 'boolean', 'discovery_problem_id': NAMES_PROBLEM,
            'discovery_problem_reason': NAMES_REASON, 'different_from_purpose_id': recall.LISTING_PHRASE}


def is_names_term(term) -> bool:
    return isinstance(term, dict) and term.get('discovery_problem_id') == NAMES_PROBLEM


def scope_terms(task, right, eligible):
    """A marked task's image/web/enforcement scope searches only by the names term; other scopes never use it."""
    if not enabled(task):
        return eligible
    if right in NAME_RIGHTS:
        named = [term for term in eligible if is_names_term(term)]
        return named[:1] if named else eligible
    return [term for term in eligible if not is_names_term(term)]


# ----- SerpApi capacity ------------------------------------------------------------------------------------------------
def _now():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace('+00:00', 'Z')


def _number(value):
    if isinstance(value, bool) or value is None:
        return None
    try:
        number = float(str(value).replace(',', '').strip())
    except ValueError:
        return None
    return int(number) if number == int(number) else None


def discovery_need(task) -> int:
    """US Google Patents discovery searches this task plans: its recall groups, or the default before understanding."""
    groups = [row for row in (task or {}).get('query_terms') or [] if isinstance(row, dict)
              and row.get('recall_group') in ('design', 'patent')]
    return len(groups) if groups else DEFAULT_DISCOVERY_NEED


def _epo_executable(task_dir) -> bool:
    path = Path(task_dir) / 'source-capabilities.json'
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return False
    values = data.get('providers', data.get('sources', [])) if isinstance(data, dict) else []
    rows = values.values() if isinstance(values, dict) else values
    return any(isinstance(row, dict) and row.get('provider') == 'epo_ops' and row.get('executable') is True
               for row in rows)


def account_reading(task, *, fetch=None, slot=None):
    """The SerpApi Account API fields (no search is counted), with the key never leaving this function.

    The frozen client resolves the endpoint and the key (``settings``); its own snapshot raises at a zero balance and
    so loses the renewal date, so the same endpoint is read here directly. ``slot`` ('primary' or 'backup') reads that
    account whatever slot the process selected."""
    from provider_utils import ProviderError, http_json, redact_sensitive_text
    from serpapi_patents_client import settings
    from source_policy import enabled as capacity_policy
    try:
        config, base, key = settings()
        selected = 'backup' if os.environ.get(SLOT_ENV) == 'backup' else 'primary'
        if slot is not None and slot != selected and os.environ.get('LC_IPR_TEST_MODE') != '1':
            from common import serpapi_slot_key
            key = serpapi_slot_key(slot)
            if not key:
                return {'state': 'unknown', 'error_code': 'CREDENTIAL_MISSING'}, None, None
        timeout = int((config.get('http') or {}).get('timeout_seconds', 30))
        payload, _, _ = (fetch or http_json)('%s/account.json?%s' % (base, urlencode({'api_key': key})),
                                             timeout=timeout, retries=0)
    except ProviderError as exc:
        return {'state': 'unknown', 'error_code': exc.code if hasattr(exc, 'code') else 'ACCOUNT_API_FAILED',
                'detail': redact_sensitive_text(str(exc))[:200]}, None, None
    except (OSError, ValueError, TypeError) as exc:
        return {'state': 'unknown', 'error_code': 'ACCOUNT_API_FAILED',
                'detail': redact_sensitive_text(str(exc))[:200]}, None, None
    if not isinstance(payload, dict) or payload.get('error'):
        return {'state': 'unknown', 'error_code': 'ACCOUNT_API_REJECTED'}, None, None
    left = _number(payload.get('plan_searches_left'))
    extra = _number(payload.get('extra_credits')) or 0
    if left is None:
        return {'state': 'unknown', 'error_code': 'ACCOUNT_API_SCHEMA_CHANGED'}, None, None
    available = left + extra if capacity_policy(task) else left
    reading = {'state': 'known', 'remote_available': max(0, available), 'plan_searches_left': left,
               'extra_credits': extra, 'searches_per_month': _number(payload.get('searches_per_month')),
               'this_month_usage': _number(payload.get('this_month_usage')),
               'renewal_date': str(payload.get('plan_renewal_date') or '')[:10],
               'account_status': str(payload.get('account_status') or '')}
    return reading, base, key


SLOT_ENV = 'LC_IPR_SERPAPI_KEY_SLOT'
SLOTS = ('primary', 'backup')


def _slot_reading(task, slot, *, fetch=None, today=None):
    """One account's balance: the Account API reading and the local ledger of that key (never the key)."""
    reading, base, key = account_reading(task, fetch=fetch, slot=slot)
    reading = dict(reading)
    if reading.get('state') == 'known':
        from free_search_budget import peek
        local = peek('serpapi', key, base, renewal_date=reading.get('renewal_date') or '', today=today)
        reading['local_remaining'] = local
        reading['available'] = reading['remote_available'] if local is None else min(reading['remote_available'], local)
    return reading


def _serpapi_used(task_dir) -> bool:
    try:
        evidence = json.loads((Path(task_dir) / 'evidence.json').read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return False
    return any(isinstance(run, dict) and str(run.get('provider') or '').startswith('serpapi')
               and run.get('submission_state') != 'not_submitted' for run in evidence.get('source_runs', []))


def choose_slot(primary, backup, full_need):
    """'primary' when the main account covers the whole task (discovery + details) or no backup reading is usable;
    else 'backup' when it covers the task, else whichever known account has more searches left (ties: primary)."""
    def left(reading):
        return int(reading.get('available') or 0) if isinstance(reading, dict) and reading.get('state') == 'known' else -1
    if backup is None or left(backup) < 0:
        return 'primary'
    if left(primary) >= full_need:
        return 'primary'
    if left(backup) >= full_need:
        return 'backup'
    return 'backup' if left(backup) > left(primary) else 'primary'


def check_capacity(task_dir, *, fetch=None, today=None) -> dict:
    """Read the SerpApi balance once and record it in ``serpapi-capacity.json`` (never the key).

    r8: with a backup key in .env the backup account is read too when the main one cannot cover the task (its US
    discovery searches plus the detail cap); the slot used is recorded and kept for the rest of the task, and once the
    task has sent a SerpApi request the slot never changes."""
    from common import atomic_write_json, load_json, serpapi_free_enabled, serpapi_slot_key
    task_dir = Path(task_dir)
    task = load_json(task_dir / 'task.json')
    record = {'schema': CAPACITY_SCHEMA, 'revision': REVISION, 'checked_at': _now(),
              'needed_discovery': discovery_need(task)}
    if not serpapi_free_enabled(task):
        record.update(state='disabled')
    else:
        previous = capacity(task_dir) or {}
        locked = previous.get('key_slot') in SLOTS and _serpapi_used(task_dir)
        full_need = record['needed_discovery'] + DETAIL_CAP
        backup_configured = os.environ.get('LC_IPR_TEST_MODE') != '1' and bool(serpapi_slot_key('backup'))
        if locked:
            slot = previous['key_slot']
            readings = {slot: _slot_reading(task, slot, fetch=fetch, today=today)}
        else:
            readings = {'primary': _slot_reading(task, 'primary', fetch=fetch, today=today)}
            if backup_configured and not (readings['primary'].get('state') == 'known'
                                          and int(readings['primary'].get('available') or 0) >= full_need):
                readings['backup'] = _slot_reading(task, 'backup', fetch=fetch, today=today)
            slot = choose_slot(readings['primary'], readings.get('backup'), full_need)
        record.update(readings[slot])
        record['key_slot'] = slot
        record['backup_configured'] = backup_configured
        record['accounts'] = {name: {key: value for key, value in reading.items()
                                     if key in ('state', 'available', 'renewal_date', 'error_code')}
                              for name, reading in readings.items()}
        apply_slot(record)
    record['epo_executable'] = _epo_executable(task_dir)
    record['route'] = route_for(record)
    if __import__('portable').enabled(task):
        # r9: the notice names the task's own countries (an EU/JP task is not a "US search")
        record['targets'] = sorted(str(value) for value in task.get('target_jurisdictions') or [])
    atomic_write_json(task_dir / CAPACITY_FILE, record)
    return record


def apply_slot(record) -> str:
    """Select the recorded SerpApi account for this process and the scripts it starts (environment variable)."""
    slot = record.get('key_slot') if isinstance(record, dict) else None
    if slot == 'backup':
        os.environ[SLOT_ENV] = 'backup'
    else:
        os.environ.pop(SLOT_ENV, None)
    return slot or 'primary'


def capacity(task_dir):
    try:
        data = json.loads((Path(task_dir) / CAPACITY_FILE).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) and data.get('schema') == CAPACITY_SCHEMA else None


def route_for(record) -> str:
    """'serpapi' (enough, unknown or disabled), 'epo' (short, EPO can run) or 'none' (short, EPO cannot run)."""
    if not isinstance(record, dict) or record.get('state') != 'known':
        return 'serpapi'
    if int(record.get('available') or 0) >= int(record.get('needed_discovery') or DEFAULT_DISCOVERY_NEED):
        return 'serpapi'
    return 'epo' if record.get('epo_executable') else 'none'


def serpapi_discovery_blocked(task, task_dir) -> bool:
    """A marked task whose recorded SerpApi balance cannot cover its US discovery searches (planning skips SerpApi)."""
    return enabled(task) and task_dir is not None and route_for(capacity(task_dir)) != 'serpapi'


def notice(record) -> str:
    """One line for the owner at checkpoint 1 / the stop message."""
    if not isinstance(record, dict) or record.get('state') == 'disabled':
        return ''
    if record.get('state') != 'known':
        return 'SerpApi 余额这次没有读到（%s），照常用 SerpApi 检索；如果检索被额度挡下，检索阶段结束时会停下说明。' % (
            record.get('error_code') or '未知原因')
    left, renewal = record.get('available'), record.get('renewal_date') or '未载明'
    need = record.get('needed_discovery') or DEFAULT_DISCOVERY_NEED
    route = record.get('route') or route_for(record)
    prefix = _slot_note(record)
    if route == 'serpapi':
        return prefix + 'SerpApi 本期还可用 %s 次（%s 恢复）；本次%s专利与外观检索用 %s 次，深查详情最多 %d 次。' % (
            left, renewal, _area(record), need, DETAIL_CAP)
    return prefix + _short_notice(record, left, renewal, need, route)


def _area(record) -> str:
    """r9: '美国' for a US task (and every record written before r9), otherwise nothing - the counts are task-wide."""
    targets = record.get('targets')
    return '美国' if targets is None or list(targets) == ['US'] else ''


def _slot_note(record) -> str:
    accounts = record.get('accounts') or {}
    if record.get('key_slot') == 'backup':
        main = accounts.get('primary') or {}
        main_left = main.get('available') if main.get('state') == 'known' else '未读到'
        return '主 key 本期剩 %s 次（%s 恢复），本任务改用备用 key。' % (main_left, main.get('renewal_date') or '未载明')
    if 'backup' in accounts:
        spare = accounts['backup']
        spare_left = spare.get('available') if spare.get('state') == 'known' else '未读到'
        return '备用 key 本期剩 %s 次，没有比主 key 多，本任务仍用主 key。' % spare_left
    return ''


def _short_notice(record, left, renewal, need, route) -> str:
    if not _area(record):
        # r9 (portable-v1, a non-US task): the US-only EPO rerouting wording does not apply
        if route == 'epo':
            return ('SerpApi 本期只剩 %s 次（%s 恢复），不够本次检索：能改用 EPO 的专利检索改用 EPO（每条最多 25 条结果），'
                    '其余用不上 SerpApi 的范围列为限制；深查候选没有 SerpApi 详情，现行状态记为未核验。' % (left, renewal))
        return ('SerpApi 本期只剩 %s 次（%s 恢复），EPO 也不能用：本次无法检索专利和外观，开跑前已停止，不出报告。'
                '请在 %s 之后新建任务重跑，或检查 EPO 凭据。' % (left, renewal, renewal))
    if route == 'epo':
        return ('SerpApi 本期只剩 %s 次（%s 恢复），不够本次 %s 条美国专利与外观检索：这几条检索改用 EPO（只查美国文献，条数不变，'
                '每条最多 25 条结果）；深查候选没有 SerpApi 详情，现行状态记为未核验。' % (left, renewal, need))
    return ('SerpApi 本期只剩 %s 次（%s 恢复），EPO 也不能用：本次无法检索美国专利和外观，开跑前已停止，不出报告。'
            '请在 %s 之后新建任务重跑，或检查 EPO 凭据。' % (left, renewal, renewal))


# ----- candidate details (owner decision 2026-10-16: at most 8, likeliest risks first) ---------------------------------
def detail_cap(task_dir) -> int:
    """Details this task may still plan: 8, or what the recorded balance leaves after the discovery searches."""
    record = capacity(task_dir)
    if not isinstance(record, dict) or record.get('state') != 'known':
        return DETAIL_CAP
    if route_for(record) != 'serpapi':
        return 0
    spare = int(record.get('available') or 0) - int(record.get('needed_discovery') or DEFAULT_DISCOVERY_NEED)
    return max(0, min(DETAIL_CAP, spare))


def detail_ranks(task_dir) -> dict:
    """{candidate id: 0 | 1}: 0 for a same-form design or a core utility patent of the list screen, else 1."""
    from recall_screen import load_kept
    ranks = {}
    for mode, first in (('image', 'same'), ('text', 'core')):
        for row in load_kept(task_dir, mode):
            cid = (row.get('scope') or {}).get('candidate_id')
            if cid:
                ranks[cid] = min(ranks.get(cid, 1), 0 if row.get('tier') == first else 1)
    return ranks


def detail_issue(task, evidence, queries, candidate, task_dir) -> str:
    """'' when a SerpApi candidate detail may be planned for ``candidate``, else the reason it may not."""
    if not enabled(task) or task_dir is None or not isinstance(candidate, dict):
        return ''
    import core_focus
    cap = detail_cap(task_dir)
    funded = {row.get('candidate_id') for row in (queries.get('serpapi_google_patents') or [])
              if isinstance(row, dict) and row.get('operation') == 'candidate_detail'}
    funded |= {run.get('candidate_id') or (run.get('request_params') or {}).get('candidate_id')
               for run in (evidence or {}).get('source_runs', []) if isinstance(run, dict)
               and run.get('provider') == 'serpapi_google_patents' and run.get('operation') == 'candidate_detail'}
    funded.discard(None)
    if candidate.get('candidate_id') in funded:
        return ''
    if len(funded) >= cap:
        return 'SEARCH_GUARD_DETAIL_CAP_REACHED'
    ranks = detail_ranks(task_dir)
    own = ranks.get(candidate.get('candidate_id'), 1)
    selected = core_focus.priorities(task_dir)
    ahead = sum(1 for cid in selected if cid not in funded and cid != candidate.get('candidate_id')
                and ranks.get(cid, 1) < own)
    return 'SEARCH_GUARD_DETAIL_CAP_REACHED' if len(funded) + ahead >= cap else ''


# ----- quota refusals before a request is sent -------------------------------------------------------------------------
# Messages the frozen SerpApi clients raise before the metered request (Account API balance, local ledger, task cap).
PRE_NETWORK_QUOTA_MESSAGES = (
    'Shared local free allowance is exhausted',
    'SerpApi available account searches are exhausted',
    'A prior SerpApi quota stop is recorded',
    'This task already reserved its maximum attempts',
    'No confirmed free search allowance remains',
    'Earlier user-authorized requests have unknown credit consumption',
    'Per-task free query cap reached',
)


def pre_network_quota(stderr) -> bool:
    text = str(stderr or '')
    return any(message in text for message in PRE_NETWORK_QUOTA_MESSAGES)


# ----- after the source rounds ---------------------------------------------------------------------------------------
PATENT_RIGHTS = ('design', 'patent')


def patent_discovery_outcome(task, evidence, plan):
    """(planned, succeeded, codes) for the US patent and design discovery rows of this plan."""
    providers = ('serpapi_google_patents', 'epo_ops', 'serper_patents')
    rows = [row for provider in providers for row in ((plan or {}).get('queries') or {}).get(provider, [])
            if isinstance(row, dict) and row.get('jurisdiction') == 'US' and row.get('right_type') in PATENT_RIGHTS
            and row.get('action_purpose', 'discovery') == 'discovery' and row.get('operation') in ('search', 'patents')]
    ids = {row.get('query_id') for row in rows}
    runs = [run for run in (evidence or {}).get('source_runs', []) if isinstance(run, dict) and run.get('query_id') in ids]
    succeeded = sum(1 for run in runs if run.get('status') in ('success', 'no_result'))
    codes = sorted({str(run.get('error_code')) for run in runs if run.get('error_code')})
    return len(rows), succeeded, codes


def main(argv=None):
    import argparse
    parser = argparse.ArgumentParser(description='SerpApi balance check of a search-guard task (no search is counted).')
    parser.add_argument('--task-dir', type=Path, required=True)
    parser.add_argument('--check-capacity', action='store_true')
    args = parser.parse_args(argv)
    from common import load_json
    task = load_json(args.task_dir / 'task.json')
    if not enabled(task):
        print(json.dumps({'status': 'not_applicable'}, ensure_ascii=False))
        return 0
    record = check_capacity(args.task_dir) if args.check_capacity else (capacity(args.task_dir) or {})
    shown = {key: record.get(key) for key in ('state', 'available', 'remote_available', 'local_remaining', 'renewal_date',
                                               'needed_discovery', 'epo_executable', 'route', 'error_code')
             if record.get(key) is not None}
    print(json.dumps({'status': 'ok', **shown, 'notice': notice(record)}, ensure_ascii=False))
    return 0


__all__ = ['REVISION', 'REVISIONS', 'TASK_FIELD', 'enabled', 'design_epo_route', 'apply_slot', 'choose_slot', 'core_words', 'shares_core', 'check_capacity', 'capacity', 'route_for',
           'serpapi_discovery_blocked', 'notice', 'pre_network_quota', 'patent_discovery_outcome', 'DETAIL_CAP',
           'names_term', 'is_names_term', 'scope_terms', 'detail_cap', 'detail_issue']


if __name__ == '__main__':
    raise SystemExit(main())
