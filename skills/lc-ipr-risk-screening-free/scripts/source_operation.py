"""03C operation-level source acceptance, bound to a retained response."""
from __future__ import annotations

from pathlib import Path
import re

from common import load_json, load_skill_config, sha256_json, sha256_file

REVISION = 'source-operation-v1'
V2_REVISION = 'source-operation-v2'
GOOD = {'verified', 'not_applicable', 'single_page'}
BAD = {'failed', 'unknown'}


def operation_acceptance_context(task, provider):
    """Fingerprint credential/permission state without retaining secret values."""
    from common import credential
    from runtime_v24 import CREDENTIALS
    names = CREDENTIALS.get(provider, ())
    secret_fingerprints = {name: sha256_json({'value': credential({}, name)}) for name in names}
    config = load_skill_config()
    policy = config.get('providers', {}).get(provider, {})
    permission = {key: policy.get(key) for key in (
        'default_enabled', 'network_enabled_when_opted_in', 'allow_paid', 'allow_overage',
        'allow_automatic_recharge', 'credential_file', 'credential_key', 'office_map',
        'excluded_offices', 'max_requests_per_task', 'free_plan',
    ) if key in policy}
    permission['task_opt_in'] = task.get(provider.split('_')[0] + '_free_enhancement', {})
    adapter_names = {'signa': 'signa_client.py', 'serpapi_google_patents': 'serpapi_patents_client.py',
        'serpapi_google_lens': 'serpapi_lens_client.py', 'serper_patents': 'serper_client.py',
        'serper_web': 'serper_client.py', 'serper_images': 'serper_client.py', 'epo_ops': 'epo_ops_client.py',
        'epo_publication_server': 'eps_client.py', 'euipo_trademark': 'euipo_client.py',
        'euipo_design': 'euipo_client.py', 'inpi_api': 'inpi_client.py', 'jpo_api': 'jpo_api_client.py'}
    adapter_hashes = {}
    if provider == 'serpapi_google_patents':
        for name in ('serpapi_patents_client.py', 'serpapi_patent_details_client.py'):
            path = Path(__file__).resolve().parent / name
            adapter_hashes[name] = sha256_file(path) if path.is_file() else 'unavailable'
    else:
        path = Path(__file__).resolve().parent / adapter_names.get(provider, '')
        adapter_hashes[path.name] = sha256_file(path) if path.is_file() else 'unavailable'
    return {'credential_fingerprint_sha256': sha256_json(secret_fingerprints),
            'permission_fingerprint_sha256': sha256_json(permission),
            'adapter_version': sha256_json(adapter_hashes)}


def record_operation_acceptance(task_dir, task, evidence, row, run, entry):
    """Accept only a retained v3 operation response, never its legal facts."""
    if task.get('retrieval_workflow_revision') != 'api-first-v3':
        raise ValueError('SOURCE_OPERATION_V3_OPERATION_REQUIRED')
    if run.get('metadata', {}).get('physical_response_reuse'):
        raise ValueError('SOURCE_OPERATION_PHYSICAL_REUSE_NOT_NEW_REQUEST')
    provider, operation = run.get('provider'), row.get('operation')
    supported = {'search', 'candidate_detail', 'trademark_search', 'trademark_media',
                 'image_search', 'patents', 'images', 'candidate_verification',
                 'document_retrieval', 'number_lookup'}
    if not isinstance(provider, str) or operation not in supported:
        raise ValueError('SOURCE_OPERATION_OPERATION_UNSUPPORTED')
    from common import assert_provider_execution_allowed
    assert_provider_execution_allowed(task, provider, operation,
        jurisdiction=str(row.get('jurisdiction') or ''), right_type=str(row.get('right_type') or ''))
    if (run.get('operation') != operation or run.get('jurisdiction') != row.get('jurisdiction')
            or run.get('right_type') != row.get('right_type') or run.get('query_id') != row.get('query_id')
            or run.get('submission_state') != 'submitted'
            or run.get('plan_entry_sha256') != sha256_json(row)):
        raise ValueError('SOURCE_OPERATION_RUN_BINDING_INVALID')
    from source_result_processing import zero_result_proven
    if task_dir is None:
        raise ValueError('SOURCE_OPERATION_RESPONSE_MISSING')
    zero = zero_result_proven(run, evidence, Path(task_dir))
    if run.get('status') != 'success' and not (run.get('status') == 'no_result' and zero):
        raise ValueError('SOURCE_OPERATION_RESPONSE_INCOMPLETE')
    from runtime_v24 import source_files_complete
    if not source_files_complete(Path(task_dir), evidence, run):
        raise ValueError('SOURCE_OPERATION_RESPONSE_MISSING')
    if not isinstance(entry, dict) or entry.get('source_run_id') != run.get('run_id'):
        raise ValueError('SOURCE_OPERATION_RUN_BINDING_INVALID')
    from trusted_api import _upstream, country as api_country, records, valid_entry
    if not valid_entry(task, entry, run):
        raise ValueError('SOURCE_OPERATION_TRUSTED_RECEIPT_INVALID')
    if (entry.get('provider') != provider or entry.get('operation') != operation
            or entry.get('jurisdiction') != row.get('jurisdiction')
            or entry.get('right_type') != row.get('right_type')):
        raise ValueError('SOURCE_OPERATION_RECORD_IDENTITY_MISMATCH')
    rows = records(entry.get('payload'))
    identity_fields = ('publication_number', 'application_number', 'registration_number',
                       'serial_number', 'provider_record_id', 'record_number', 'patent_id', 'identifier', 'id')
    if operation in {'candidate_detail', 'trademark_media', 'candidate_verification',
                     'document_retrieval', 'number_lookup'}:
        def normalized_ids(value):
            text = str(value or '').strip()
            values = {re.sub(r'[^A-Za-z0-9]', '', text).upper()} if text else set()
            # SerpApi Google Patents identifies a grant as patent/US.../en;
            # its normalized record stores the publication number separately.
            match = re.fullmatch(r'patent/([A-Za-z]{2}[A-Za-z0-9]+)/[a-z]{2}', text, re.I)
            if match:
                values.add(re.sub(r'[^A-Za-z0-9]', '', match.group(1)).upper())
            return {value for value in values if value}
        expected_groups = []
        for key in identity_fields:
            value = row.get(key)
            if value:
                expected_groups.append(normalized_ids(value))
        # Some detail adapters preserve the fetched publication only in q.
        # Admit q only when it is an identifier-shaped token, never free text.
        query_value = str(row.get('q') or '').strip()
        if query_value and re.fullmatch(r'[A-Za-z]{0,4}[0-9][A-Za-z0-9./-]{4,}', query_value):
            expected_groups.append(normalized_ids(query_value))
        matches = []
        for record in rows:
            observed = set().union(*(normalized_ids(record.get(key)) for key in identity_fields if record.get(key)))
            # Every explicit requested identity field must resolve to this
            # response record. A shared application/candidate/language token
            # cannot mask a mismatched publication number.
            same_id = bool(expected_groups) and all(group & observed for group in expected_groups)
            # A candidate link is context only; it cannot replace the actual
            # publication/registration/provider record identity in a fetch.
            if same_id:
                matches.append(record)
        if len(matches) != 1:
            raise ValueError('SOURCE_OPERATION_RECORD_IDENTITY_MISMATCH')
        record = matches[0]
        if row.get('provider_record_id') and str(record.get('provider_record_id') or '').casefold() \
                != str(row['provider_record_id']).casefold():
            raise ValueError('SOURCE_OPERATION_RECORD_IDENTITY_MISMATCH')
        record_country = api_country(record.get('jurisdiction') or record.get('office') or record.get('country_code'))
        if not record_country or record_country != api_country(row.get('jurisdiction')):
            raise ValueError('SOURCE_OPERATION_RECORD_IDENTITY_MISMATCH')
        if operation in {'candidate_detail', 'trademark_media'} and row.get('provider_record_id') \
                and str(record.get('provider_record_id') or '').casefold() != str(row['provider_record_id']).casefold():
            raise ValueError('SOURCE_OPERATION_RECORD_IDENTITY_MISMATCH')
        identity = {key: record.get(key) for key in identity_fields if record.get(key)}
    else:
        metadata = run.get('metadata', {}).get('search_coverage', {})
        if run.get('status') == 'no_result' and not zero:
            raise ValueError('SOURCE_OPERATION_ZERO_UNPROVEN')
        if run.get('status') == 'success' and not rows and metadata.get('returned_count') not in (None, 0):
            raise ValueError('SOURCE_OPERATION_RESPONSE_INCOMPLETE')
        if any(api_country(record.get('jurisdiction') or record.get('office') or record.get('country_code'))
               != api_country(row.get('jurisdiction'))
               for record in rows if record.get('jurisdiction') or record.get('office')):
            raise ValueError('SOURCE_OPERATION_RECORD_IDENTITY_MISMATCH')
        identity = {'record_count': len(rows), 'search_zero_proven': zero}
    identity.update(provider=provider, upstream=_upstream(provider), jurisdiction=row.get('jurisdiction'),
                     right_type=row.get('right_type'), operation=operation)
    config = load_skill_config()
    provider_policy = config.get('providers', {}).get(provider, {})
    if provider == 'signa' and (provider_policy.get('network_enabled_when_opted_in') is not True
            or provider_policy.get('allow_paid') is not False
            or provider_policy.get('allow_overage') is not False
            or provider_policy.get('allow_automatic_recharge') is not False):
        raise ValueError('SOURCE_OPERATION_COST_POLICY_INVALID')
    # Every new response above still validates its exact record/territory and
    # shape. The operation itself was already accepted by the first real
    # request; do not append another full interface acceptance for each case.
    # A later anomaly or current credential/permission/adapter change revokes
    # this reuse through the same receipt-bound consumer.
    if current_operation_acceptance(task, evidence, provider, row, task_dir):
        return None
    # Recompute live fingerprints. A persisted entry context is historical
    # metadata and must never authorize a changed credential or permission.
    context = operation_acceptance_context(task, provider)
    if not isinstance(context, dict):
        raise ValueError('SOURCE_OPERATION_ACCEPTANCE_CONTEXT_INVALID')
    adapter_names = {'signa': 'signa_client.py', 'serpapi_google_patents': 'serpapi_patents_client.py',
        'serpapi_google_lens': 'serpapi_lens_client.py', 'serper_patents': 'serper_client.py',
        'serper_web': 'serper_client.py', 'serper_images': 'serper_client.py',
        'epo_ops': 'epo_ops_client.py', 'epo_publication_server': 'eps_client.py',
        'euipo_trademark': 'euipo_client.py', 'euipo_design': 'euipo_client.py', 'inpi_api': 'inpi_client.py',
        'jpo_api': 'jpo_api_client.py'}
    if provider == 'serpapi_google_patents' and operation == 'candidate_detail':
        adapter_names[provider] = 'serpapi_patent_details_client.py'
    if provider == 'epo_publication_server' and operation == 'document_retrieval':
        adapter_names[provider] = 'eps_client.py'
    adapter = Path(__file__).resolve().parent / adapter_names.get(provider, '')
    if not adapter.is_file():
        raise ValueError('SOURCE_OPERATION_ADAPTER_UNAVAILABLE')
    controls = {key: provider_policy.get(key) for key in ('default_enabled', 'network_enabled_when_opted_in',
        'allow_paid', 'allow_overage', 'allow_automatic_recharge', 'credential_file', 'credential_key',
        'office_map', 'excluded_offices') if key in provider_policy}
    controls['task_opt_in'] = task.get(provider.split('_')[0] + '_free_enhancement', {})
    for key in ('credential_fingerprint_sha256', 'permission_fingerprint_sha256', 'adapter_version'):
        if context.get(key) is not None:
            controls[key] = context[key]
    body = {'provider': provider, 'operation': operation, 'jurisdiction': row.get('jurisdiction'),
        'right_type': row.get('right_type'), 'plan_entry_sha256': sha256_json(row),
        'source_run_id': run.get('run_id'), 'source_run_sha256': sha256_json(run),
        'evidence_entry_sha256': sha256_json(entry), 'record_identity': identity,
        'adapter_sha256': sha256_file(adapter), 'controls_sha256': sha256_json(controls),
        'retrieval_workflow_revision': task.get('retrieval_workflow_revision'),
        'acceptance_context': {key: context.get(key) for key in
            ('credential_fingerprint_sha256', 'permission_fingerprint_sha256', 'adapter_version')
            if context.get(key) is not None}}
    return {'kind': 'source_operation_acceptance_v1', 'state': 'accepted',
            'acceptance_key_sha256': sha256_json(body), 'proof': body}


def _current_acceptance_context(task, provider, operation):
    # Always read the live credential/permission fingerprints; a saved row or
    # prior receipt context must never stand in for current configuration.
    context = operation_acceptance_context(task, provider)
    config = load_skill_config()
    policy = config.get('providers', {}).get(provider, {})
    controls = {key: policy.get(key) for key in ('default_enabled', 'network_enabled_when_opted_in',
        'allow_paid', 'allow_overage', 'allow_automatic_recharge', 'credential_file', 'credential_key',
        'office_map', 'excluded_offices') if key in policy}
    controls['task_opt_in'] = task.get(provider.split('_')[0] + '_free_enhancement', {})
    for key in ('credential_fingerprint_sha256', 'permission_fingerprint_sha256', 'adapter_version'):
        value = context.get(key)
        if value is not None:
            if not isinstance(value, str):
                raise ValueError('SOURCE_OPERATION_ACCEPTANCE_CONTEXT_INVALID')
            controls[key] = value
    names = {'signa': 'signa_client.py', 'serpapi_google_patents': 'serpapi_patents_client.py',
        'serpapi_google_lens': 'serpapi_lens_client.py', 'serper_patents': 'serper_client.py',
        'serper_web': 'serper_client.py', 'serper_images': 'serper_client.py', 'epo_ops': 'epo_ops_client.py',
        'epo_publication_server': 'eps_client.py', 'euipo_trademark': 'euipo_client.py',
        'euipo_design': 'euipo_client.py', 'inpi_api': 'inpi_client.py', 'jpo_api': 'jpo_api_client.py'}
    if provider == 'serpapi_google_patents' and operation == 'candidate_detail':
        names[provider] = 'serpapi_patent_details_client.py'
    if provider == 'epo_publication_server' and operation == 'document_retrieval':
        names[provider] = 'eps_client.py'
    adapter = Path(__file__).resolve().parent / names.get(provider, '')
    if not adapter.is_file():
        raise ValueError('SOURCE_OPERATION_ADAPTER_UNAVAILABLE')
    return sha256_file(adapter), sha256_json(controls)


def current_operation_acceptance(task, evidence, provider, row, task_dir=None):
    """Return True only while the exact saved operation receipt remains current."""
    if task.get('retrieval_workflow_revision') != 'api-first-v3' or not isinstance(row, dict):
        return False
    if task_dir is not None:
        from runtime_v24 import physical_response_source
        logical = [run for run in evidence.get('source_runs', [])
                   if isinstance(run, dict) and run.get('provider') == provider and run.get('query_id') == row.get('query_id')
                   and run.get('plan_entry_sha256') == sha256_json(row)
                   and run.get('metadata', {}).get('physical_response_reuse')]
        if logical:
            for run in logical:
                source = physical_response_source(Path(task_dir), evidence, run)
                if source is None:
                    continue
                plan = load_json(Path(task_dir) / 'search-plan.json')
                originals = [item for item in plan.get('queries', {}).get(provider, [])
                             if item.get('query_id') == source.get('query_id')
                             and sha256_json(item) == source.get('plan_entry_sha256')]
                original_evidence = {**evidence, 'operation_acceptances': [item
                    for item in evidence.get('operation_acceptances', []) if isinstance(item, dict)
                    and isinstance(item.get('proof'), dict)
                    and item['proof'].get('source_run_id') == source.get('run_id')]}
                if len(originals) == 1 and current_operation_acceptance(task, original_evidence, provider, originals[0]):
                    return True
            return False
    try:
        adapter_sha, controls_sha = _current_acceptance_context(task, provider, row.get('operation'))
    except (ValueError, OSError, TypeError):
        return False
    runs = {run.get('run_id'): run for run in evidence.get('source_runs', []) if isinstance(run, dict)}
    entries = [entry for group in evidence.get('collections', {}).values() if isinstance(group, list)
               for entry in group if isinstance(entry, dict)]
    by_id = {entry.get('evidence_id'): entry for entry in entries}
    matches = []
    for acceptance in evidence.get('operation_acceptances', []):
        if not isinstance(acceptance, dict) or acceptance.get('kind') != 'source_operation_acceptance_v1' \
                or acceptance.get('state') != 'accepted' or not isinstance(acceptance.get('proof'), dict):
            continue
        proof = acceptance['proof']
        if acceptance.get('acceptance_key_sha256') != sha256_json(proof):
            continue
        if (proof.get('provider') != provider or proof.get('operation') != row.get('operation')
                or proof.get('jurisdiction') != row.get('jurisdiction')
                or proof.get('right_type') != row.get('right_type')
                or proof.get('adapter_sha256') != adapter_sha
                or proof.get('controls_sha256') != controls_sha):
            continue
        run = runs.get(proof.get('source_run_id'))
        if not isinstance(run, dict) or sha256_json(run) != proof.get('source_run_sha256'):
            continue
        entry = next((value for value in entries if value.get('source_run_id') == run.get('run_id')
                      and sha256_json(value) == proof.get('evidence_entry_sha256')), None)
        if entry is None:
            continue
        from trusted_api import valid_entry
        if not valid_entry(task, entry, run):
            continue
        matches.append((proof, run))
    if not matches:
        return False
    proof, accepted_run = max(matches, key=lambda pair: str(pair[1].get('finished_at') or ''))
    accepted_time = str(accepted_run.get('finished_at') or accepted_run.get('started_at') or '')
    for run in runs.values():
        if (run.get('provider') == provider and run.get('operation') == row.get('operation')
                and run.get('jurisdiction') == row.get('jurisdiction')
                and run.get('right_type') == row.get('right_type')
                and run.get('submission_state') == 'submitted'
                and run.get('status') not in {'success', 'no_result', 'not_applicable'}
                and str(run.get('finished_at') or run.get('started_at') or '') > accepted_time):
            return False
    for failure in evidence.get('operation_acceptance_failures', []):
        failed = runs.get(failure.get('source_run_id')) if isinstance(failure, dict) else None
        if (isinstance(failed, dict) and failed.get('provider') == provider
                and failed.get('operation') == row.get('operation')
                and failed.get('jurisdiction') == row.get('jurisdiction')
                and failed.get('right_type') == row.get('right_type')
                and str(failed.get('finished_at') or failed.get('started_at') or '') > accepted_time):
            return False
    return True


def enabled(task):
    value = task.get('source_operation_revision')
    if value is None:
        return False
    if value not in {REVISION, V2_REVISION}:
        raise ValueError('SOURCE_OPERATION_REVISION_INVALID')
    if value == V2_REVISION and task.get('retrieval_workflow_revision') != 'api-first-v3':
        raise ValueError('SOURCE_OPERATION_REVISION_INVALID')
    return True


def _candidate_runs(evidence, provider, row):
    return [run for run in evidence.get('source_runs', []) if run.get('provider') == provider
        and run.get('query_id') == row.get('query_id')
        and run.get('plan_entry_sha256') == sha256_json(row)
        and run.get('status') in {'success', 'no_result'}
        and run.get('submission_state') == 'submitted']


def _runs(evidence, provider, row):
    return [run for run in _candidate_runs(evidence, provider, row)
            if run.get('operation') == row.get('operation')
            and run.get('jurisdiction') == row.get('jurisdiction')
            and run.get('right_type') == row.get('right_type')]


def validate(task, plan, evidence, review, task_dir=None):
    if not enabled(task) or not isinstance(review, dict):
        raise ValueError('SOURCE_OPERATION_REVIEW_INVALID')
    provider = review.get('provider')
    if provider == 'asset_provenance':
        raise ValueError('SOURCE_OPERATION_AGENT_INVESTIGATION_SEPARATE')
    matches = [row for row in plan.get('queries', {}).get(provider, [])
               if row.get('query_id') == review.get('query_id')]
    if len(matches) != 1:
        raise ValueError('SOURCE_OPERATION_QUERY_CHANGED')
    row = matches[0]
    if row.get('operation') in {'candidate_detail', 'trademark_media'} \
            and task.get('retrieval_workflow_revision') != 'api-first-v3':
        raise ValueError('SOURCE_OPERATION_V3_OPERATION_REQUIRED')
    if review.get('plan_entry_sha256') != sha256_json(row):
        raise ValueError('SOURCE_OPERATION_QUERY_CHANGED')
    runs = [run for run in _runs(evidence, provider, row)
            if run.get('run_id') == review.get('source_run_id')]
    if len(runs) != 1 or review.get('source_run_sha256') != sha256_json(runs[0]):
        raise ValueError('SOURCE_OPERATION_RUN_CHANGED')
    from runtime_v24 import source_files_complete
    if task_dir is None or not source_files_complete(Path(task_dir), evidence, runs[0]):
        raise ValueError('SOURCE_OPERATION_RESPONSE_MISSING')
    if not isinstance(review.get('reviewer'), str) or not review['reviewer'].strip() \
            or not isinstance(review.get('reason'), str) or not review['reason'].strip():
        raise ValueError('SOURCE_OPERATION_REVIEW_REASON_REQUIRED')
    if review.get('decision') not in {'accepted', 'rejected', 'unvalidated'}:
        raise ValueError('SOURCE_OPERATION_DECISION_INVALID')
    if review['decision'] == 'accepted':
        from assessment_v24 import NON_PRODUCTION
        environment = str(runs[0].get('source_environment') or '').casefold()
        if (runs[0].get('fixture') or runs[0].get('test_only')
                or environment in NON_PRODUCTION | {'unit_test_only', 'non_production', 'synthetic', 'offline'}):
            raise ValueError('SOURCE_OPERATION_NON_PRODUCTION_RESPONSE')
    checks = review.get('checks')
    if not isinstance(checks, dict) or type(checks.get('request_response_binding')) is not bool:
        raise ValueError('SOURCE_OPERATION_BINDING_REQUIRED')
    if review['decision'] == 'accepted' and checks['request_response_binding'] is not True:
        raise ValueError('SOURCE_OPERATION_ACCEPTANCE_UNSUPPORTED')
    for name in ('field_effect', 'pagination', 'known_number', 'original_content', 'current_status'):
        if checks.get(name) not in GOOD | BAD:
            raise ValueError('SOURCE_OPERATION_CHECK_INVALID')
    needed = {'field_effect', 'pagination'}
    if row.get('operation') == 'candidate_verification':
        needed.add('current_status')
    elif row.get('operation') == 'document_retrieval':
        needed.add('original_content')
    elif row.get('operation') in {'candidate_detail', 'number_lookup'}:
        needed.add('known_number')
    elif row.get('operation') == 'trademark_media':
        if task.get('source_operation_revision') != V2_REVISION:
            raise ValueError('SOURCE_OPERATION_V3_OPERATION_REQUIRED')
        needed.add('original_content')
    if review['decision'] == 'accepted' and any(checks[name] in BAD for name in needed):
        raise ValueError('SOURCE_OPERATION_ACCEPTANCE_UNSUPPORTED')
    if review['decision'] == 'accepted':
        if checks['field_effect'] != 'verified' and row.get('operation') not in {
                'document_retrieval', 'candidate_verification', 'number_lookup'}:
            raise ValueError('SOURCE_OPERATION_FIELD_UNVERIFIED')
        specific = {'candidate_verification': 'current_status',
                    'document_retrieval': 'original_content',
                    'candidate_detail': 'known_number',
                    'number_lookup': 'known_number'}.get(row.get('operation'))
        if specific and checks[specific] != 'verified':
            raise ValueError('SOURCE_OPERATION_SPECIFIC_CHECK_UNVERIFIED')
        if row.get('operation') == 'trademark_media' and checks['original_content'] != 'verified':
            raise ValueError('SOURCE_OPERATION_SPECIFIC_CHECK_UNVERIFIED')
        if row.get('operation') not in {'document_retrieval', 'candidate_verification'} \
                and checks['pagination'] not in {'verified', 'single_page'}:
            raise ValueError('SOURCE_OPERATION_PAGINATION_UNVERIFIED')
    if review['decision'] == 'accepted' and checks['pagination'] == 'single_page' \
            and row.get('page', 1) not in (None, 1):
        raise ValueError('SOURCE_OPERATION_PAGINATION_UNSUPPORTED')
    return row, runs[0]


def verify(task, plan, evidence, task_dir):
    if not enabled(task):
        return
    reviews = task.get('source_operation_reviews', [])
    if not isinstance(reviews, list):
        raise ValueError('SOURCE_OPERATION_REVIEWS_INVALID')
    for review in reviews:
        try:
            validate(task, plan, evidence, review, task_dir)
        except ValueError as exc:
            # A newly planned expression invalidates old capability scope,
            # while its signed historical review remains retained.
            if str(exc) != 'SOURCE_OPERATION_QUERY_CHANGED':
                raise
        body = {key: value for key, value in review.items() if key not in {'review_id', 'review_sha256'}}
        if review.get('review_sha256') != sha256_json(body):
            raise ValueError('SOURCE_OPERATION_REVIEW_CHANGED')
        path = Path(task_dir) / 'raw' / 'source_operation' / (review['review_id'] + '.json')
        if not path.is_file() or load_json(path) != review:
            raise ValueError('SOURCE_OPERATION_RECEIPT_CHANGED')


def accepted_operations(task, plan, evidence, task_dir):
    if not enabled(task):
        return {}
    verify(task, plan, evidence, task_dir)
    result = {}
    latest = {}
    for review in task.get('source_operation_reviews', []):
        latest[(review['provider'], review['query_id'])] = review
    for review in latest.values():
        if review['decision'] != 'accepted':
            continue
        try:
            row, run = validate(task, plan, evidence, review, task_dir)
        except ValueError as exc:
            if str(exc) == 'SOURCE_OPERATION_QUERY_CHANGED':
                continue
            raise
        result.setdefault(review['provider'], []).append({
            **{key: row.get(key, '') for key in ('jurisdiction', 'right_type', 'operation',
            'query_compiler_revision', 'search_dimension', 'query_id')},
            'plan_entry_sha256': sha256_json(row), 'source_run_id': run['run_id'],
            'source_run_sha256': sha256_json(run), 'review_sha256': review['review_sha256']})
    return result


def rejected_operation_keys(task, plan, evidence, task_dir):
    """A task-local anomaly suspends a packaged acceptance for this task only."""
    if not enabled(task):
        return set()
    verify(task, plan, evidence, task_dir)
    latest = {}
    for review in task.get('source_operation_reviews', []):
        latest[(review['provider'], review['query_id'])] = review
    output = set()
    for review in latest.values():
        if review['decision'] == 'accepted':
            continue
        try:
            row, _ = validate(task, plan, evidence, review, task_dir)
        except ValueError as exc:
            if str(exc) == 'SOURCE_OPERATION_QUERY_CHANGED':
                continue
            raise
        output.add((review['provider'], *(row.get(key, '') for key in
            ('jurisdiction', 'right_type', 'operation', 'query_compiler_revision', 'search_dimension'))))
    return output


def _has_accepted_descendant_fallback(task, plan, evidence, task_dir, provider, row):
    """Whether an immutable rejected route already has an accepted live fallback.

    This only retires the repeated *review work item* for the failed ancestor.
    It does not accept that ancestor, claim source coverage, or close discovery
    triage/semantic work for the fallback.
    """
    rows_by_id = {}
    providers_by_id = {}
    for candidate_provider, rows in plan.get('queries', {}).items():
        for candidate in rows:
            query_id = candidate.get('query_id')
            if query_id in rows_by_id:
                return False
            rows_by_id[query_id] = candidate
            providers_by_id[query_id] = candidate_provider

    intent = row.get('discovery_intent_id')
    if not intent:
        return False
    accepted = accepted_operations(task, plan, evidence, task_dir)
    for query_id, candidate in rows_by_id.items():
        if (candidate.get('discovery_role') != 'browser_fallback'
                or candidate.get('provider_role') != 'fallback'
                or candidate.get('discovery_intent_id') != intent
                or providers_by_id[query_id] == provider):
            continue
        accepted_runs = {(item.get('query_id'), item.get('source_run_id'), item.get('plan_entry_sha256'))
                         for item in accepted.get(providers_by_id[query_id], [])}
        if not any(key[0] == query_id and key[2] == sha256_json(candidate) for key in accepted_runs):
            continue
        seen = set()
        cursor = candidate
        while cursor.get('parent_query_id'):
            parent_id = cursor['parent_query_id']
            if parent_id in seen:
                break
            seen.add(parent_id)
            parent = rows_by_id.get(parent_id)
            if parent is None or cursor.get('parent_plan_entry_sha256') != sha256_json(parent):
                break
            if any(cursor.get(key) != parent.get(key) for key in
                   ('discovery_intent_id', 'jurisdiction', 'right_type', 'search_dimension')):
                break
            if parent_id == row.get('query_id'):
                return True
            cursor = parent
    return False


def work_entries(task, plan, evidence, task_dir, capabilities=None):
    if not enabled(task) or task_dir is None:
        return []
    latest = {(review.get('provider'), review.get('query_id'), review.get('source_run_id')): review
              for review in task.get('source_operation_reviews', [])}
    from runtime_v24 import source_files_complete
    output = []
    for provider, rows in plan.get('queries', {}).items():
        if provider == 'asset_provenance':
            continue  # Agent investigation has its own provenance review.
        for row in rows:
            from runtime_v24 import operation_accepted
            if operation_accepted((capabilities or {}).get(provider), row):
                continue  # Reuse a maintainer-accepted operation; no per-task reacceptance.
            if current_operation_acceptance(task, evidence, provider, row, task_dir):
                continue  # Reuse the exact current v3 first-response acceptance.
            for run in _candidate_runs(evidence, provider, row):
                if not source_files_complete(Path(task_dir), evidence, run):
                    continue
                bound = run in _runs(evidence, provider, row)
                review = latest.get((provider, row.get('query_id'), run.get('run_id')))
                if not bound or review is None or review.get('decision') != 'accepted':
                    if (bound and review is not None and review.get('decision') == 'rejected'
                            and _has_accepted_descendant_fallback(
                                task, plan, evidence, task_dir, provider, row)):
                        continue
                    output.append({'kind': 'agent_investigation', 'state': 'awaiting_review',
                        'provider': provider, 'query_id': row['query_id'],
                        'jurisdiction': row.get('jurisdiction'), 'right_type': row.get('right_type'),
                        'reason': ('SOURCE_OPERATION_RUN_BINDING_INVALID' if not bound else
                                   'SOURCE_OPERATION_REVIEW_REQUIRED' if review is None
                                   else 'SOURCE_OPERATION_REJECTED_REPLAN_REQUIRED')})
    return output
