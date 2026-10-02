"""Bounded identity review of public Lens sales leads, never a rights clearance."""
from __future__ import annotations

from pathlib import Path
from contextlib import contextmanager
from contextvars import ContextVar
import json
from common import atomic_write_json, load_json, now_iso, resolve_retained_path, sha256_file, sha256_json, stable_id

EVENTS = 'public_identity_investigations'
REVISION = 'public-identity-bounded-v1'
GAPS = {'right_type', 'rights_holder', 'first_publication', 'supply_chain_authorization'}


# Verification reuse is bounded by one work view.  File-backed proofs never use
# the longer-lived pure decision memo or a timestamp/size freshness shortcut.
_VALIDATION = ContextVar('ipr_public_identity_validation', default=None)


@contextmanager
def validation_snapshot(task_dir, task, evidence, candidates, plan, ledger, supplement=None):
    """Reject the entire view if a memoized proof's actual files change."""
    if not enabled(task):
        yield None
        return
    inputs = (task, evidence, candidates, plan, ledger, supplement)
    root = Path(task_dir).resolve()
    parent = _VALIDATION.get()
    if parent is not None and parent['root'] == root and all(a is b for a,b in zip(parent['inputs'],inputs)):
        yield parent
        return
    before = sha256_json(inputs)
    state = {'root':root, 'inputs':inputs, 'memo':{}, 'files':{}, 'error':None}
    token = _VALIDATION.set(state)
    try:
        yield state
    finally:
        try:
            # Rehash bytes even after exceptions.  Cached positive results cannot
            # leave this boundary when any dependency disappeared or changed.
            for path, recorded in state['files'].items():
                try:
                    intact = (path.resolve() == recorded['resolved_path']
                        and sha256_file(path) == recorded['sha256'])
                except (OSError, ValueError):
                    intact = False
                if not intact:
                    state['error'] = 'PUBLIC_IDENTITY_VIEW_FILE_CHANGED'
            if sha256_json(inputs) != before:
                state['error'] = 'PUBLIC_IDENTITY_VIEW_INPUT_CHANGED'
            if state['error']:
                raise ValueError(state['error'])
        finally:
            state['memo'].clear()
            state['files'].clear()
            _VALIDATION.reset(token)


def _validation(task, evidence, candidates=None, ledger=None, supplement=None, task_dir=None):
    state = _VALIDATION.get()
    if state is None:
        return None
    bound = state['inputs']
    if (task is not bound[0] or evidence is not bound[1] or supplement is not bound[5]
            or (candidates is not None and candidates is not bound[2])
            or (ledger is not None and ledger is not bound[4])
            or (task_dir is not None and Path(task_dir).resolve() != state['root'])):
        return None
    return state


def _guard_file(state, value, expected_sha256='', expected_bytes=None):
    """Hash a unique actual path now and again at the outer view boundary."""
    if state is None:
        return
    path = Path(value).absolute()
    prior = state['files'].get(path)
    try:
        if prior is None:
            prior = {'sha256':sha256_file(path), 'resolved_path':path.resolve(), 'bytes':path.stat().st_size}
            state['files'][path] = prior
        if ((expected_sha256 and expected_sha256 != prior['sha256'])
                or (expected_bytes is not None and expected_bytes != prior['bytes'])):
            raise ValueError('PUBLIC_IDENTITY_VIEW_FILE_BINDING_CHANGED')
    except (OSError, ValueError):
        state['error'] = 'PUBLIC_IDENTITY_VIEW_FILE_BINDING_CHANGED'
        raise ValueError(state['error'])


def _guard_retained(state, task_dir, value, expected_sha256, expected_bytes=None):
    if state is None:
        return
    root = Path(task_dir).resolve()
    direct = root / str(value)
    if not direct.resolve().is_relative_to(root):
        _guard_file(state, root/'recovery-manifest.json')
    try:
        path = resolve_retained_path(root, value, expected_sha256=expected_sha256, expected_bytes=expected_bytes)
    except (OSError, ValueError):
        state['error'] = 'PUBLIC_IDENTITY_VIEW_FILE_BINDING_CHANGED'
        raise ValueError(state['error'])
    _guard_file(state, path, expected_sha256, expected_bytes)
    # Preserve the original symlink/path identity as well as the resolved file.
    if direct.is_file():
        _guard_file(state, direct, expected_sha256, expected_bytes)


def _guard_run(state, task_dir, evidence, run):
    if state is None:
        return
    for raw in run.get('raw_paths', []):
        _guard_retained(state,task_dir,raw,run.get('payload_digest',''))
    def visit(value):
        if isinstance(value,dict):
            if value.get('path') and value.get('sha256'):
                _guard_retained(state,task_dir,value['path'],value['sha256'],value.get('bytes'))
            for child in value.values():
                visit(child)
        elif isinstance(value,list):
            for child in value:
                visit(child)
    for rows in evidence.get('collections',{}).values():
        if isinstance(rows,list):
            for entry in rows:
                if isinstance(entry,dict) and entry.get('source_run_id') == run.get('run_id'):
                    visit(entry)


def enabled(task):
    return (task.get('retrieval_workflow_revision') == 'api-first-v3'
        and task.get('public_discovery_routing_revision') == 'public-discovery-v1')


def public_sales_lead(task, candidate):
    return (enabled(task) and candidate.get('right_type') == 'unknown'
        and candidate.get('source_index') == 'google_lens'
        and candidate.get('match_type') in {'visual_matches','exact_matches'}
        and not any(candidate.get(k) for k in ('publication_number','application_number','grant_number',
            'registration_number','serial_number','record_number','claims','claim','claim_text'))
        and isinstance(candidate.get('sources'),list) and bool(candidate['sources'])
        and all(isinstance(ref,dict) and ref.get('provider') == 'serpapi_google_lens'
            and ref.get('source_collection') in {'visual_matches','exact_matches'}
            and not (ref.get('identity_observation') or {}).get('identifiers') for ref in candidate['sources']))


def _text(value):
    return isinstance(value, str) and bool(value.strip())


def _review_valid(request):
    return (isinstance(request,dict) and request.get('reading_purpose') == 'source_association'
        and request.get('individual_image_use') == 'not_used_for_expression_or_authorship'
        and isinstance(request.get('unresolved_facts'),list)
        and all(_text(v) for v in request['unresolved_facts'])
        and GAPS <= set(request['unresolved_facts'])
        and isinstance(request.get('shared_query_ids'),list) and len(request['shared_query_ids']) == 5
        and all(_text(v) for v in request['shared_query_ids']) and len(set(request['shared_query_ids'])) == 5
        and all(_text(request.get(k)) for k in ('reviewer','reason','resume_condition')))


def _events(evidence, task):
    state = _VALIDATION.get()
    if state is not None and state['inputs'][0] is task and state['inputs'][1] is evidence:
        key = ('events',)
        if key not in state['memo']:
            state['memo'][key] = _validated_events(evidence,task)
        return state['memo'][key]
    return _validated_events(evidence,task)


def _validated_events(evidence, task):
    events = evidence.get(EVENTS, [])
    if not isinstance(events, list):
        raise ValueError('PUBLIC_IDENTITY_EVENTS_INVALID')
    previous = ''
    for event in events:
        if not isinstance(event,dict):
            raise ValueError('PUBLIC_IDENTITY_EVENTS_INVALID')
        unsigned = {k:v for k,v in event.items() if k != 'event_id'}
        if (not _review_valid(event) or event.get('revision') != REVISION or event.get('previous_event_id') != previous
                or event.get('event_id') != stable_id('PUBLIC-ID', task['task_id'], sha256_json(unsigned))):
            raise ValueError('PUBLIC_IDENTITY_HISTORY_CHANGED')
        previous = event['event_id']
    return events


def binding(task_dir, task, evidence, candidates, ledger, request, supplement=None):
    """Re-read exact sources and shared public investigation before any reuse."""
    from decision_workflow import triage_summary, candidate_content_sha256, candidate_identity_fingerprint
    from source_result_processing import _retained_run, _latest_decisions
    from assessment_v24 import evidence_index
    if (not isinstance(request,dict) or not enabled(task) or request.get('jurisdiction') != 'UNLOCATED'
            or request.get('right_type') != 'unknown'
            or len(task.get('target_jurisdictions', [])) != 1):
        raise ValueError('PUBLIC_IDENTITY_SCOPE_INVALID')
    state = _validation(task,evidence,candidates,ledger,supplement,task_dir)
    _guard_file(state,task_dir/'task.json')
    _guard_file(state,task_dir/'search-plan.json')
    country = task['target_jurisdictions'][0]
    cid, sid = request.get('candidate_id'), request.get('scenario_id')
    matches = [c for c in candidates.get('copyright_assets', []) if c.get('candidate_id') == cid]
    if len(matches) != 1:
        raise ValueError('PUBLIC_IDENTITY_CANDIDATE_INVALID')
    candidate = matches[0]
    if not public_sales_lead(task,candidate):
        raise ValueError('PUBLIC_IDENTITY_NOT_PUBLIC_SALES_LEAD')
    records = triage_summary(task, candidates, ledger, evidence=evidence, supplement=supplement)['records']
    decisions = [r for r in records if r.get('candidate_id') == cid and r.get('scenario_id') == sid
        and r.get('jurisdiction') == 'UNLOCATED' and r.get('right_type') == 'unknown']
    if (len(decisions) != 1 or not decisions[0].get('current')
            or decisions[0].get('decision') != 'selected' or decisions[0].get('next_actions')):
        raise ValueError('PUBLIC_IDENTITY_CURRENT_ASSOCIATION_REQUIRED')
    annotation = decisions[0]['annotation']
    relation = annotation.get('candidate_relation', {})
    if not relation.get('identity_gaps') or not relation.get('direction_ids') or not relation.get('product_object_ids'):
        raise ValueError('PUBLIC_IDENTITY_ASSOCIATION_BASIS_REQUIRED')
    source_refs = candidate.get('sources', [])
    if not source_refs:
        raise ValueError('PUBLIC_IDENTITY_ORIGINAL_SOURCE_REQUIRED')
    sources = []
    for ref in source_refs:
        if (ref.get('provider') != 'serpapi_google_lens'
                or ref.get('source_collection') not in {'visual_matches', 'exact_matches'}
                or (ref.get('identity_observation') or {}).get('identifiers')):
            raise ValueError('PUBLIC_IDENTITY_NOT_PUBLIC_SALES_LEAD')
        runs = [r for r in evidence.get('source_runs', []) if r.get('run_id') == ref.get('source_run_id')]
        if (len(runs) != 1 or runs[0].get('status') != 'success' or runs[0].get('jurisdiction') != country
                or runs[0].get('source_environment') in {'test_fixture','sandbox','non_production'}
                or runs[0].get('fixture') or runs[0].get('test_only')):
            raise ValueError('PUBLIC_IDENTITY_SOURCE_SCOPE_INVALID')
        run = runs[0]
        _guard_run(state,task_dir,evidence,run)
        if run.get('submission_state') == 'not_submitted':
            from runtime_v24 import physical_response_source
            source = physical_response_source(task_dir, evidence, run)
            if source is None:
                raise ValueError('PUBLIC_IDENTITY_SOURCE_RECEIPT_INVALID')
            _guard_run(state,task_dir,evidence,source)
        elif run.get('submission_state') != 'submitted':
            raise ValueError('PUBLIC_IDENTITY_SOURCE_RECEIPT_INVALID')
        index, raw_body = _retained_run(task_dir, run, evidence)
        positions = [r['position'] for r in index.get('rows', []) if r.get('raw_sha256') == ref.get('source_record_sha256')]
        dispositions = _latest_decisions(evidence, run['run_id'], index)
        if (len(positions) != 1 or positions[0] not in dispositions
                or dispositions[positions[0]].get('outcome') not in {'candidate','duplicate_source'}
                or cid not in dispositions[positions[0]].get('candidate_ids', [])):
            raise ValueError('PUBLIC_IDENTITY_SOURCE_POSITION_NOT_REVIEWED')
        fields = ref.get('record_fields', {})
        if not fields.get('title') or not fields.get('url'):
            raise ValueError('PUBLIC_IDENTITY_SOURCE_FIELDS_REQUIRED')
        source_row = next(r for r in index['rows'] if r['position'] == positions[0])
        original = json.loads(raw_body)[source_row['collection']][source_row['collection_position']-1]
        if (source_row['collection'] != ref['source_collection']
                or original.get('title') != fields['title'] or original.get('link') != fields['url']
                or any(original.get(k) for k in ('publication_number','registration_number','serial_number','claims','claim'))):
            raise ValueError('PUBLIC_IDENTITY_SOURCE_FIELDS_CHANGED')
        sources.append({'run_id':run['run_id'], 'run_sha256':sha256_json(run),
            'source_anchor':ref.get('source_anchor'), 'record_sha256':ref['source_record_sha256'],
            'position':positions[0], 'reading_fields':{'title':fields['title'],'url':fields['url']}})
    plan = load_json(task_dir / 'search-plan.json')
    registry = evidence_index(evidence)
    registry.update({e['evidence_id']:e for e in (supplement or {}).get('evidence', [])})
    package_key = ('shared',sid,country,tuple(sorted(request.get('shared_query_ids',[]))))
    if state is not None and package_key in state['memo']:
        shared, dependencies = state['memo'][package_key]
    else:
        shared, dependencies = _shared_packages(task_dir,task,evidence,plan,registry,sid,country,
            request.get('shared_query_ids',[]),state)
        if state is not None:
            state['memo'][package_key] = (shared,dependencies)
    return {'candidate_identity_sha256':candidate_identity_fingerprint('copyright_assets',candidate),
        'candidate_content_sha256':candidate_content_sha256(candidate,evidence,supplement,task=task),
        'annotation_id':annotation['annotation_id'],'annotation_sha256':sha256_json(annotation),
        'target_jurisdictions':[country],'sources':sources,'shared_public_packages':shared,
        'external_dependencies':dependencies}


def _shared_packages(task_dir, task, evidence, plan, registry, sid, country, shared_query_ids, state):
    from record_asset_provenance import INVESTIGATION_STEPS, investigation_complete, external_information_actions
    from assessment_v24 import _retained_artifacts_complete
    shared, dependencies = [], []
    for right in ('copyright','trade_dress'):
        for step in INVESTIGATION_STEPS[right]:
            queries = [q for q in plan.get('queries',{}).get('asset_provenance',[]) if
                q.get('right_type') == right and q.get('search_dimension') == step
                and q.get('scenario_id') == sid and q.get('jurisdiction') == country
                and q.get('query_id') in shared_query_ids]
            # Generated scope rows may store scenario binding in the existing list.
            if not queries:
                from workflow_v24 import scenario_row_bindings
                queries = [q for q in plan.get('queries',{}).get('asset_provenance',[]) if
                    q.get('right_type') == right and q.get('search_dimension') == step
                    and q.get('jurisdiction') == country and q.get('query_id') in shared_query_ids
                    and any(b.get('scenario_id') == sid for b in scenario_row_bindings(task,q))]
            if len(queries) != 1:
                raise ValueError('PUBLIC_IDENTITY_SHARED_PLAN_REQUIRED')
            query = queries[0]
            entries = [e for rows in evidence.get('collections',{}).values() if isinstance(rows,list)
                for e in rows if e.get('provider') == 'asset_provenance' and e.get('query_id') == query['query_id']
                and e.get('plan_entry_sha256') == sha256_json(query)]
            usable = []
            for entry in entries:
                source_runs = [r for r in evidence.get('source_runs',[]) if r.get('run_id') == entry.get('source_run_id')]
                if (len(source_runs) != 1 or source_runs[0].get('status') != 'success'
                        or source_runs[0].get('query_id') != query['query_id']
                        or source_runs[0].get('plan_entry_sha256') != sha256_json(query)
                        or source_runs[0].get('source_environment') in {'test_fixture','sandbox','non_production'}
                        or source_runs[0].get('fixture') or source_runs[0].get('test_only')):
                    continue
                payload = entry.get('payload',{})
                for artifact in payload.get('artifacts',[]):
                    _guard_file(state,artifact.get('path'),artifact.get('sha256',''),artifact.get('bytes'))
                    _guard_retained(state,task_dir,artifact.get('path'),artifact.get('sha256',''),artifact.get('bytes'))
                actions = external_information_actions(task,payload,query,sid,registry)
                public = {**payload,'outstanding_actions':[]} if actions else payload
                if not investigation_complete(task,public,query,sid,registry) or not _retained_artifacts_complete(payload):
                    continue
                for artifact in payload.get('artifacts',[]):
                    resolve_retained_path(task_dir,artifact.get('path'),expected_sha256=artifact.get('sha256'))
                usable.append((entry,actions,source_runs[0]))
            if not usable:
                raise ValueError('PUBLIC_IDENTITY_SHARED_READING_INCOMPLETE')
            entry, actions, source_run = usable[-1]
            read_refs = {ref for step_record in entry['payload'].get('investigation_steps',[])
                for ref in step_record.get('evidence_refs',[])}
            shared.append({'evidence_id':entry['evidence_id'],'sha256':sha256_json(entry),
                'query_id':query['query_id'],'plan_entry_sha256':sha256_json(query),
                'run_id':source_run['run_id'],'run_sha256':sha256_json(source_run),
                'read_evidence_sha256':{ref:sha256_json(registry[ref]) for ref in sorted(read_refs)}})
            dependencies.extend(actions)
    if not dependencies:
        raise ValueError('PUBLIC_IDENTITY_EXTERNAL_DEPENDENCY_REQUIRED')
    return shared, dependencies


def current(task, evidence, candidates, ledger, scope, supplement=None, task_dir=None):
    if not enabled(task):
        return None
    try:
        matches = [e for e in _events(evidence,task) if all(e.get(k) == scope.get(k)
            for k in ('candidate_id','scenario_id','jurisdiction','right_type'))]
        if not matches:
            return None
        event = matches[-1]
        root = Path(task_dir or event['task_root']).resolve()
        state = _validation(task,evidence,candidates,ledger,supplement,root)
        key = ('current',event['event_id'])
        if state is not None and key in state['memo']:
            return state['memo'][key]
        _guard_file(state,root/'task.json')
        if load_json(root/'task.json').get('task_id') != task['task_id']:
            return None
        expected = binding(root,task,evidence,candidates,ledger,event,supplement)
        result = event if expected == event.get('binding') else None
        if result is not None and state is not None:
            state['memo'][key] = result
        return result
    except (ValueError,OSError,KeyError,TypeError):
        return None


def record(task_dir, request):
    from provider_utils import evidence_lock
    from workflow_v24 import scenario_supplement
    task_dir = Path(task_dir).resolve()
    if not _review_valid(request):
        raise ValueError('PUBLIC_IDENTITY_REVIEW_REQUIRED')
    with evidence_lock(task_dir):
        task,evidence,candidates,ledger = [load_json(task_dir/n) for n in
            ('task.json','evidence.json','normalized-candidates.json','materiality-annotations.json')]
        if task.get('state') == 'completed':
            raise ValueError('PUBLIC_IDENTITY_COMPLETED_READ_ONLY')
        supplement = scenario_supplement(task_dir,task=task,evidence=evidence)
        bound = binding(task_dir,task,evidence,candidates,ledger,request,supplement)
        item = {k:request[k] for k in ('candidate_id','scenario_id','jurisdiction','right_type',
            'reading_purpose','individual_image_use','unresolved_facts','shared_query_ids','reviewer','reason','resume_condition')}
        item.update(revision=REVISION,task_root=str(task_dir),binding=bound)
        events = _events(evidence,task)
        for prior in reversed(events):
            if all(prior.get(k) == v for k,v in item.items()):
                return prior
        item.update(previous_event_id=events[-1]['event_id'] if events else '',recorded_at=now_iso())
        item['event_id'] = stable_id('PUBLIC-ID',task['task_id'],sha256_json(item))
        evidence.setdefault(EVENTS,[]).append(item)
        atomic_write_json(task_dir/'evidence.json',evidence)
        return item


def limitation(event, work):
    return {**work,'state':'blocked','reason':'PUBLIC_IDENTITY_BOUNDED_UNKNOWN',
        'coverage_status':'unknown','official_verification':'not_verified',
        'reasoning':event['reason'],'resume_condition':event['resume_condition'],
        'delivery_limit':{'kind':'public_identity_bounded','event_id':event['event_id'],
            'event_sha256':sha256_json(event),'unresolved_facts':event['unresolved_facts']}}
