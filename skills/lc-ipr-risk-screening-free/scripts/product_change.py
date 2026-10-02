"""02B append-only product changes and bounded applicability checks.

The existing scope receipt remains the source of truth for revised facts. This
module records what changed and which retained results need a separate review.
"""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path

from common import atomic_write_json, load_json, sha256_file, sha256_json, stable_id, resolve_retained_path

REVISION = 'product-change-v1'
FACT_CONTENT = ('value', 'nature', 'verification', 'status', 'source_path', 'applies_to', 'source_refs')
OBJECT_CONTENT = ('kind', 'relation', 'intent', 'scope_status', 'description', 'location',
                  'right_types', 'visual_evidence', 'source_refs')


def enabled(task):
    revision = task.get('product_change_revision')
    if revision is None:
        return False
    if revision != REVISION:
        raise ValueError('PRODUCT_CHANGE_REVISION_INVALID')
    return True


def _changed(old, new, key, fields):
    before = {row[key]: row for row in old}
    after = {row[key]: row for row in new}
    return [{'id': identifier, 'before': deepcopy(before.get(identifier)),
             'after': deepcopy(after.get(identifier))}
            for identifier in sorted(before.keys() | after.keys())
            if before.get(identifier) is None or after.get(identifier) is None
            or any(before[identifier].get(field) != after[identifier].get(field) for field in fields)]


def scope_delta(old, new):
    facts = _changed(old.get('facts', []), new.get('facts', []), 'fact_id', FACT_CONTENT)
    objects = _changed(old.get('objects', []), new.get('objects', []), 'object_id', OBJECT_CONTENT)
    directions = _changed(old.get('directions', []), new.get('directions', []), 'direction_id',
                          ('scenario_id', 'right_type', 'fact_ids', 'object_ids'))
    return facts, objects, directions


def _candidate_ids(task_dir, evidence, query_ids, scope_keys):
    path = Path(task_dir) / 'normalized-candidates.json'
    if not path.is_file():
        return [], []
    from annotate_materiality import iter_candidates
    candidates = load_json(path)
    runs = {run.get('run_id'): run for run in evidence.get('source_runs', [])}
    affected, expanded = set(), set()
    for _, candidate in iter_candidates(candidates):
        cid = candidate.get('candidate_id')
        if not cid:
            continue
        source_queries = {runs.get(source.get('source_run_id'), {}).get('query_id')
                          for source in candidate.get('sources', []) if isinstance(source, dict)}
        if source_queries & query_ids:
            affected.add(cid)
        elif ((candidate.get('jurisdiction'), candidate.get('right_type')) in scope_keys
              or candidate.get('right_type') in {'',None,'unknown'}
              and candidate.get('jurisdiction') in {country for country,_ in scope_keys}):
            # Candidate source lineage does not prove which product facts a
            # later comparison used. Expand within plausible scope only.
            affected.add(cid)
            expanded.add(cid)
    return sorted(affected), sorted(expanded)


def scope_impact(task_dir, task, evidence, old, new, plan):
    facts, objects, directions = scope_delta(old, new)
    changed_facts = {row['id'] for row in facts}
    changed_objects = {row['id'] for row in objects}
    changed_directions = {row['id'] for row in directions}
    for direction in old.get('directions', []) + new.get('directions', []):
        if changed_facts & set(direction.get('fact_ids', [])) or changed_objects & set(direction.get('object_ids', [])):
            changed_directions.add(direction['direction_id'])
    query_ids, scope_keys = set(), set()
    for rows in plan.get('queries', {}).values():
        for row in rows:
            refs = row.get('product_dependencies', [])
            if (changed_facts & {ref.get('fact_id') for ref in row.get('product_fact_refs', [])}
                    or changed_directions & {ref.get('direction_id') for ref in refs}
                    or changed_objects & {oid for ref in refs for oid in ref.get('object_ids', [])}):
                query_ids.add(row['query_id'])
                scope_keys.add((row.get('jurisdiction'), row.get('right_type')))
    for direction in old.get('directions', []) + new.get('directions', []):
        if direction['direction_id'] in changed_directions:
            scope_keys.update((country,direction['right_type']) for country in task.get('target_jurisdictions',[]))
    candidates, expanded = _candidate_ids(task_dir, evidence, query_ids, scope_keys)
    return {'fact_changes': facts, 'object_changes': objects, 'direction_changes': directions,
            'affected_direction_ids': sorted(changed_directions), 'affected_query_ids': sorted(query_ids),
            'affected_candidate_ids': candidates, 'expanded_candidate_ids': expanded,
            'expansion_reason': ('Candidate comparison-to-product-fact lineage is not explicit; review was widened only within '
                                 'affected jurisdiction and right type.' if expanded else '')}


def append_scope_change(task_dir, task, evidence, old, new, plan, *, prior_scope_sha256, scope_sha256, reason):
    impact = scope_impact(task_dir, task, evidence, old, new, plan)
    if not (impact['fact_changes'] or impact['object_changes'] or impact['direction_changes']):
        return None
    from common import now_iso
    version = task.get('product_change_version', 1) + 1
    source_only = impact['fact_changes'] and not impact['object_changes'] and not impact['direction_changes'] and all(
        row['before'] is not None and row['after'] is not None and
        all(row['before'].get(field)==row['after'].get(field) for field in FACT_CONTENT if field!='source_refs')
        for row in impact['fact_changes'])
    kind = ('evidence_supplement' if source_only else 'fact_withdrawal' if impact['fact_changes'] and all(
        row['after'] is None or row['after'].get('status') != 'confirmed' for row in impact['fact_changes'])
        else 'fact_correction' if impact['fact_changes'] else 'scope_change')
    event = {'change_id': stable_id('CHG', task['task_id'], prior_scope_sha256, scope_sha256),
             'kind': kind, 'version': version, 'prior_scope_sha256': prior_scope_sha256,
             'scope_sha256': scope_sha256, 'target_sha256': task['product_identity']['sha256'],
             'reason': reason, 'at': now_iso(), **impact}
    event['sha256'] = sha256_json({key: value for key, value in event.items() if key != 'sha256'})
    task['product_change_revision'] = REVISION
    task['product_change_version'] = version
    task.setdefault('product_change_history', []).append(event)
    task.pop('outputs',None)
    if task.get('state') in {'ready_for_assessment','assessing','needs_review','completed'}:
        from common import add_history
        add_history(task,'collecting','Product scope changed; affected work and reviews require reassessment.')
    return event


def append_target_change(task_dir, task, evidence, old_task, plan, review, source_refs):
    from annotate_materiality import iter_candidates
    from common import now_iso
    rows = [row for values in plan.get('queries', {}).values() for row in values]
    candidate_path = Path(task_dir) / 'normalized-candidates.json'
    candidate_ids = sorted({item['candidate_id'] for _, item in iter_candidates(load_json(candidate_path))}) if candidate_path.is_file() else []
    version = task.get('product_change_version', 1) + 1
    event = {'change_id':stable_id('CHG',task['task_id'],old_task['product_identity']['sha256'],
                                    task['product_identity']['sha256'],review['kind']),
             'kind':review['kind'], 'version':version,
             'prior_target_sha256':old_task['product_identity']['sha256'],
             'target_sha256':task['product_identity']['sha256'],
             'prior_scope_sha256':old_task.get('product_scope',{}).get('scope_sha256',''),
             'scope_sha256':'', 'reason':review['reason'], 'source_refs':source_refs,
             'affected_direction_ids':[row['direction_id'] for row in old_task.get('product_scope',{}).get('directions',[])],
             'affected_query_ids':sorted({row['query_id'] for row in rows}),
             'affected_candidate_ids':candidate_ids,
             'expanded_candidate_ids':candidate_ids,
             'expansion_reason':'Target identity changed; every retained result requires applicability review, without automatic re-query.',
             'at':now_iso()}
    event['sha256']=sha256_json({k:v for k,v in event.items() if k!='sha256'})
    task['product_change_revision']=REVISION
    task['product_change_version']=version
    task.setdefault('product_change_history',[]).append(event)
    task['product_change_pending']=True
    task.pop('outputs',None)
    from common import add_history
    add_history(task,'collecting','Target changed; the current scope and affected results require review.')
    return event


def append_image_supplement(task_dir, task, evidence, plan, *, image_id, evidence_id,
                            fact_ids, object_ids, reason):
    from common import now_iso
    scope=task['product_scope']
    directions=[row for row in scope['directions'] if set(row['fact_ids']) & set(fact_ids)
                or set(row['object_ids']) & set(object_ids)]
    direction_ids={row['direction_id'] for row in directions}
    rows=[row for values in plan.get('queries',{}).values() for row in values
          if direction_ids & {ref.get('direction_id') for ref in row.get('product_dependencies',[])}]
    query_ids={row['query_id'] for row in rows}
    scope_keys={(row.get('jurisdiction'),row.get('right_type')) for row in rows}
    scope_keys.update((country,direction['right_type']) for direction in directions
                      for country in task.get('target_jurisdictions',[]))
    candidates,expanded=_candidate_ids(task_dir,evidence,query_ids,scope_keys)
    version=task.get('product_change_version',1)+1
    event={'change_id':stable_id('CHG',task['task_id'],scope['scope_sha256'],image_id),
           'kind':'image_supplement','version':version,
           'prior_scope_sha256':scope['scope_sha256'],'scope_sha256':scope['scope_sha256'],
           'target_sha256':task['product_identity']['sha256'],
           'image_id':image_id,'source_refs':[evidence_id], 'reason':reason,
           'affected_fact_ids':sorted(fact_ids),'affected_object_ids':sorted(object_ids),
           'affected_direction_ids':sorted(direction_ids),'affected_query_ids':sorted(query_ids),
           'affected_candidate_ids':candidates,'expanded_candidate_ids':expanded,
           'expansion_reason':('Candidate query lineage absent; expanded within affected jurisdiction and right.'
                               if expanded else ''),'at':now_iso()}
    event['sha256']=sha256_json({k:v for k,v in event.items() if k!='sha256'})
    task['product_change_revision']=REVISION
    task['product_change_version']=version
    task.setdefault('product_change_history',[]).append(event)
    task['product_change_pending']=True
    task.pop('outputs',None)
    if task.get('state') in {'ready_for_assessment','assessing','needs_review','completed'}:
        from common import add_history
        add_history(task,'collecting','A new image view requires affected fact and scope review.')
    return event


def retain_event(task_dir, task, evidence, event):
    path = Path(task_dir) / 'raw' / 'product_change' / (event['change_id'] + '.json')
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_file():
        if load_json(path) != event:
            raise ValueError('PRODUCT_CHANGE_RETAINED_EVENT_CONFLICT')
    else:
        atomic_write_json(path,event)
    eid = stable_id('EV','product_change',task['task_id'],event['change_id'])
    row = {'evidence_id':eid,'change_id':event['change_id'],'path':str(path),'sha256':sha256_file(path)}
    retained = evidence.setdefault('collections',{}).setdefault('product_changes',[])
    previous = next((item for item in retained if item.get('change_id') == event['change_id']),None)
    if previous and previous != row:
        raise ValueError('PRODUCT_CHANGE_RECEIPT_CONFLICT')
    if not previous:
        retained.append(row)


def retain_applicability(task_dir, task, evidence, review):
    path=Path(task_dir)/'raw'/'product_applicability'/(review['review_id']+'.json')
    path.parent.mkdir(parents=True,exist_ok=True)
    if path.is_file():
        if load_json(path)!=review: raise ValueError('PRODUCT_APPLICABILITY_RECEIPT_CONFLICT')
    else:
        atomic_write_json(path,review)
    eid=stable_id('EV','product_applicability',task['task_id'],review['review_id'])
    row={'evidence_id':eid,'review_id':review['review_id'],'path':str(path),'sha256':sha256_file(path)}
    retained=evidence.setdefault('collections',{}).setdefault('product_applicability',[])
    previous=next((item for item in retained if item.get('review_id')==review['review_id']),None)
    if previous and previous!=row: raise ValueError('PRODUCT_APPLICABILITY_RECEIPT_CONFLICT')
    if not previous: retained.append(row)


def unresolved_candidates(task):
    if not enabled(task):
        return []
    current = task.get('product_change_version', 1)
    reviewed = {(row.get('change_id'), row.get('candidate_id')): row
                for row in task.get('product_applicability_reviews', [])}
    missing = []
    for event in task.get('product_change_history', []):
        for cid in event.get('affected_candidate_ids', []):
            decision = reviewed.get((event['change_id'], cid))
            if (not decision or decision.get('product_version') != current
                    or decision.get('scope_sha256') != task.get('product_scope', {}).get('scope_sha256')
                    or decision.get('status') == 'needs_info'):
                missing.append({'change_id': event['change_id'], 'candidate_id': cid})
    return missing


def verify(task, evidence=None, task_dir=None):
    history = task.get('product_change_history', [])
    if not isinstance(history,list): raise ValueError('PRODUCT_CHANGE_HISTORY_INVALID')
    if evidence is not None:
        relationships=evidence.get('collections',{}).get('product_image_relationships',[])
        ledger_path=Path(task_dir)/'image-relationships.json' if task_dir is not None else None
        if not isinstance(relationships,list) or (relationships and (ledger_path is None or not ledger_path.is_file())):
            raise ValueError('PRODUCT_IMAGE_RELATION_LEDGER_MISSING')
        if relationships:
            try:
                ledger=load_json(resolve_retained_path(Path(task_dir),str(ledger_path),
                    expected_sha256=relationships[0].get('ledger_sha256','')))
                if (ledger.get('schema_version')!='product-image-relationships-v1'
                        or ledger.get('task_id')!=task.get('task_id')
                        or not isinstance(ledger.get('items'),list)
                        or len(ledger['items'])!=len(relationships)):
                    raise ValueError('PRODUCT_IMAGE_RELATION_LEDGER_INVALID')
                images={row.get('image_id') for row in task.get('images',[])}
                images.update(row.get('image_id') for item in evidence.get('collections',{}).get('product',[])
                              for row in item.get('images',[]))
                images.update(row.get('image_id') for row in evidence.get('collections',{}).get('product_images',[]))
                targets={task.get('product_identity',{}).get('sha256')}
                targets.update(row.get('prior_target_sha256') for row in history)
                for receipt,row in zip(relationships,ledger['items']):
                    if (receipt.get('ledger_sha256')!=relationships[0].get('ledger_sha256')
                            or receipt.get('evidence_id')!=row.get('evidence_id')
                            or receipt.get('record_sha256')!=sha256_json(row)
                            or row.get('target_sha256') not in targets
                            or row.get('original_image_id') not in images
                            or row.get('content_effect')!='same_content'):
                        raise ValueError('PRODUCT_IMAGE_RELATION_LEDGER_INVALID')
                    resolve_retained_path(Path(task_dir),row.get('path',''),
                        expected_sha256=row.get('sha256',''),expected_bytes=row.get('bytes'))
            except (OSError, TypeError, KeyError) as exc:
                raise ValueError('PRODUCT_IMAGE_RELATION_LEDGER_INVALID') from exc
    if not enabled(task):
        return
    if task.get('product_change_version') != (history[-1]['version'] if history else 1):
        raise ValueError('PRODUCT_CHANGE_HISTORY_INVALID')
    if [row.get('version') for row in history] != list(range(2,len(history)+2)):
        raise ValueError('PRODUCT_CHANGE_HISTORY_SEQUENCE_INVALID')
    seen = set()
    known = ({item.get('evidence_id') for group in evidence.get('collections', {}).values()
              if isinstance(group,list) for item in group if isinstance(item,dict)}
             if evidence is not None else set())
    for event in history:
        if (not isinstance(event, dict) or event.get('change_id') in seen or not event.get('reason')
                or event.get('sha256') != sha256_json({k: v for k, v in event.items() if k != 'sha256'})):
            raise ValueError('PRODUCT_CHANGE_EVENT_CHANGED')
        seen.add(event['change_id'])
        if evidence is not None and event.get('source_refs') and not set(event['source_refs']) <= known:
            raise ValueError('PRODUCT_CHANGE_SOURCE_MISSING')
        if evidence is not None:
            receipts=[row for row in evidence.get('collections',{}).get('product_changes',[])
                      if row.get('change_id')==event['change_id']]
            if len(receipts)!=1 or task_dir is None:
                raise ValueError('PRODUCT_CHANGE_RECEIPT_MISSING')
            path=resolve_retained_path(Path(task_dir),receipts[0].get('path',''),
                                       expected_sha256=receipts[0].get('sha256',''))
            if load_json(path)!=event:
                raise ValueError('PRODUCT_CHANGE_RECEIPT_CHANGED')
    retained_scopes = {row.get('scope_sha256') for row in task.get('product_scope_history', [])}
    if any(event.get('scope_sha256') and event['scope_sha256'] not in retained_scopes
           for event in history if event.get('kind') != 'target_change'):
        raise ValueError('PRODUCT_CHANGE_SCOPE_VERSION_MISMATCH')
    for row in task.get('product_applicability_reviews', []):
        event = next((item for item in history if item['change_id'] == row.get('change_id')), None)
        if (not event or row.get('candidate_id') not in event.get('affected_candidate_ids', [])
                or row.get('status') not in {'usable', 'not_applicable', 'needs_info'}
                or not row.get('reason') or not row.get('source_refs')
                or row.get('sha256')!=sha256_json({k:v for k,v in row.items() if k!='sha256'})):
            raise ValueError('PRODUCT_APPLICABILITY_REVIEW_INVALID')
        if evidence is not None:
            if not set(row['source_refs']) <= known:
                raise ValueError('PRODUCT_APPLICABILITY_SOURCE_MISSING')
            receipts=[item for item in evidence.get('collections',{}).get('product_applicability',[])
                      if item.get('review_id')==row.get('review_id')]
            if len(receipts)!=1 or task_dir is None:
                raise ValueError('PRODUCT_APPLICABILITY_RECEIPT_MISSING')
            path=resolve_retained_path(Path(task_dir),receipts[0].get('path',''),
                                       expected_sha256=receipts[0].get('sha256',''))
            if load_json(path)!=row:
                raise ValueError('PRODUCT_APPLICABILITY_RECEIPT_CHANGED')


def assessment_gate(task, evidence, assessments):
    verify(task)
    if enabled(task) and task.get('product_change_pending'):
        raise ValueError('PRODUCT_CHANGE_SCOPE_REVIEW_REQUIRED')
    missing = unresolved_candidates(task)
    if missing:
        raise ValueError('PRODUCT_CHANGE_APPLICABILITY_REVIEW_REQUIRED')
    excluded = {row['candidate_id'] for row in task.get('product_applicability_reviews', [])
                if row['product_version'] == task.get('product_change_version') and row['status'] == 'not_applicable'}
    if any(row.get('candidate_id') in excluded and not row.get('out_of_scope') for row in assessments):
        raise ValueError('PRODUCT_CHANGE_EXCLUDED_RESULT_IN_ASSESSMENT')


def dispatch_reason(task, row):
    if not enabled(task):
        return None
    if task.get('product_change_pending'):
        return 'PRODUCT_TARGET_CHANGE_REVIEW_REQUIRED'
    if row.get('product_target_sha256') and row['product_target_sha256'] != task['product_identity']['sha256']:
        return 'PRODUCT_TARGET_CHANGE_REVIEW_REQUIRED'
    if any(row.get('query_id') in event.get('affected_query_ids', [])
           for event in task.get('product_change_history', [])):
        return 'PRODUCT_CHANGE_QUERY_REVIEW_REQUIRED'
    return None
