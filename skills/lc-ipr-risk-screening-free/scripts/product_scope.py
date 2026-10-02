"""Object scope and fact dependencies shared by recording, dispatch and reporting.

Only explicitly recorded, versioned scopes use this contract. Historical tasks
retain their original rules. No scope state is a relevance or legal conclusion.
"""
from __future__ import annotations
from copy import deepcopy
from pathlib import Path
import re
from common import load_json, resolve_retained_path, sha256_json

REVISION = 'object-scope-v1'
STATES = {'included', 'default_excluded', 'user_excluded', 'pending'}
RIGHTS = {'patent','utility_model','design','trademark_word','trademark_figurative','copyright','trade_dress','unregistered_design','enforcement'}
TEMPORARY = {'PRODUCT_SCOPE_WAITING', 'PRODUCT_SCOPE_REVIEW_REQUIRED'}
LABELS = {'included':'已纳入','default_excluded':'按默认未纳入','user_excluded':'用户明确未纳入','pending':'待确认'}
DEFAULT_ASSUMPTION = '默认拟销售功能、结构、外观一致但使用自己品牌的同款商品；这是范围假设，不证明实际拟售物一致，也不等于完成自有品牌清查。'


def enabled(task):
    value = task.get('product_scope_revision')
    if value is None:
        return False
    if value != REVISION:
        raise ValueError('PRODUCT_SCOPE_REVISION_INVALID')
    return True


def scope(task):
    data = task.get('product_scope')
    if not isinstance(data, dict) or data.get('status') != 'reviewed':
        raise ValueError('PRODUCT_SCOPE_REVIEW_REQUIRED')
    return data


def _text(value):
    return isinstance(value, str) and bool(value.strip())


def object_state(item):
    intent, relation = item.get('intent'), item.get('relation')
    if intent == 'use': return 'included'
    if intent == 'do_not_use': return 'user_excluded'
    if intent == 'uncertain': return 'pending'
    if intent != 'default': raise ValueError('OBJECT_INTENT_INVALID')
    if relation in {'target','integrated','own'}: return 'included'
    if item.get('kind') in {'brand','logo','photograph','packaging'}: return 'default_excluded'
    return 'included'


def object_scenario(item):
    return 'brand_reuse' if item['kind'] in {'brand','logo'} and item['relation']=='reference' else 'product_entry'


def validate(data):
    if not isinstance(data, dict) or set(data)-{'status','objects','facts','directions','reviewer','reasoning','evidence_id','scope_sha256','candidate_links','query_revalidations','delivery_revision','image_permissions'}:
        raise ValueError('PRODUCT_SCOPE_FIELDS_INVALID')
    if data.get('status')!='reviewed' or not _text(data.get('reviewer')) or not _text(data.get('reasoning')):
        raise ValueError('PRODUCT_SCOPE_REVIEW_REQUIRED')
    for group, idkey in [('objects','object_id'),('facts','fact_id'),('directions','direction_id')]:
        rows=data.get(group)
        if not isinstance(rows,list) or any(not isinstance(v,dict) or not _text(v.get(idkey)) for v in rows):
            raise ValueError('PRODUCT_SCOPE_'+group.upper()+'_INVALID')
        if len({v[idkey] for v in rows})!=len(rows): raise ValueError('PRODUCT_SCOPE_DUPLICATE_ID')
    objects={v['object_id']:v for v in data['objects']}; facts={v['fact_id']:v for v in data['facts']}
    for obj in objects.values():
        if obj.get('kind') not in {'product','brand','logo','pattern','photograph','packaging','other'} or obj.get('relation') not in {'target','integrated','reference','ancillary','own'}:
            raise ValueError('OBJECT_RELATION_REQUIRED')
        if not all(_text(obj.get(k)) for k in ('description','location','reason')) or not obj.get('source_refs'):
            raise ValueError('OBJECT_BASIS_REQUIRED')
        state=object_state(obj)
        if state!=obj.get('scope_status'): raise ValueError('OBJECT_SCOPE_STATE_MISMATCH')
        if not isinstance(obj.get('right_types'),list) or not set(obj['right_types'])<=RIGHTS:
            raise ValueError('OBJECT_RIGHTS_INVALID')
        if obj['intent']!='default' and not obj.get('statement_refs'): raise ValueError('OBJECT_USER_STATEMENT_REQUIRED')
        if state=='pending' and (not _text(obj.get('question')) or not _text(obj.get('checked_information'))):
            raise ValueError('OBJECT_TARGETED_QUESTION_REQUIRED')
    for fact in facts.values():
        from product_feedback import STRUCTURE_CATEGORIES
        if 'information_category' in fact and fact['information_category'] not in STRUCTURE_CATEGORIES | {'other'}:
            raise ValueError('PRODUCT_FACT_INFORMATION_CATEGORY_INVALID')
        if fact.get('status') not in {'confirmed','unknown','conflict'} or not _text(fact.get('source_path')) or not fact.get('source_refs') or not _text(fact.get('reason')):
            raise ValueError('PRODUCT_FACT_BASIS_REQUIRED')
        if fact['status']!='confirmed' and not _text(fact.get('question')): raise ValueError('PRODUCT_FACT_MINIMUM_QUESTION_REQUIRED')
        if 'value' not in fact: raise ValueError('PRODUCT_FACT_VALUE_REQUIRED')
    for direction in data['directions']:
        if direction.get('scenario_id') not in {'product_entry','brand_reuse','genuine_resale'} or direction.get('right_type') not in RIGHTS or not _text(direction.get('reason')):
            raise ValueError('PRODUCT_DIRECTION_SCOPE_REQUIRED')
        for key,known in [('fact_ids',facts),('object_ids',objects)]:
            if not isinstance(direction.get(key),list) or any(v not in known for v in direction[key]): raise ValueError('PRODUCT_DIRECTION_DEPENDENCY_INVALID')
        if not direction['fact_ids'] and not direction['object_ids']: raise ValueError('PRODUCT_DIRECTION_DEPENDENCY_REQUIRED')
        states={objects[o]['scope_status'] for o in direction['object_ids']}
        if len(states)>1: raise ValueError('PRODUCT_DIRECTION_MIXED_SCOPE_SPLIT_REQUIRED')
        if direction['right_type'].startswith('trademark'):
            if not direction['object_ids'] or any(objects[v]['kind'] not in {'brand','logo'} or (direction['scenario_id']!='genuine_resale' and object_scenario(objects[v])!=direction['scenario_id']) for v in direction['object_ids']):
                raise ValueError('TRADEMARK_OBJECT_SCENARIO_MISMATCH')
    links=data.get('candidate_links',[])
    if not isinstance(links,list): raise ValueError('CANDIDATE_SCOPE_LINKS_INVALID')
    seen=set()
    for link in links:
        if not isinstance(link,dict) or not _text(link.get('candidate_id')) or link['candidate_id'] in seen or not _text(link.get('reason')) or not link.get('source_refs'):
            raise ValueError('CANDIDATE_SCOPE_BASIS_REQUIRED')
        seen.add(link['candidate_id'])
        if not isinstance(link.get('object_ids'),list) or not link['object_ids'] or any(o not in objects for o in link['object_ids']):
            raise ValueError('CANDIDATE_SCOPE_OBJECT_REQUIRED')
    revalidations=data.get('query_revalidations',[])
    if not isinstance(revalidations,list): raise ValueError('QUERY_SCOPE_REVALIDATIONS_INVALID')
    for row in revalidations:
        if not isinstance(row,dict) or not all(_text(row.get(k)) for k in ('review_id','query_id','plan_entry_sha256','reason')) or not row.get('source_refs') or not isinstance(row.get('direction_digests'),dict):
            raise ValueError('QUERY_SCOPE_REVALIDATION_BASIS_REQUIRED')
    if len({r['query_id'] for r in revalidations})!=len(revalidations): raise ValueError('QUERY_SCOPE_REVALIDATION_DUPLICATE')
    if not isinstance(data.get('image_permissions',[]),list): raise ValueError('IMAGE_PERMISSIONS_INVALID')
    for row in data['objects']+data['facts']+links+revalidations+data.get('image_permissions',[]):
        for key in ('source_refs','statement_refs'):
            refs=row.get(key,[])
            if not isinstance(refs,list) or any(not _text(v) for v in refs): raise ValueError('PRODUCT_SCOPE_REFERENCE_INVALID')
    return data


def content(data):
    return {k:v for k,v in data.items() if k not in {'evidence_id','scope_sha256'}}


def verify(task, evidence, task_dir):
    if not enabled(task): return
    from product_change import verify as verify_changes
    verify_changes(task,evidence,task_dir)
    from product_feedback import verify as verify_feedback
    verify_feedback(task,evidence,task_dir)
    data=validate(scope(task))
    from product_delivery import enabled as delivery_enabled, validate_scope as validate_delivery, validate_fact_origins, project as delivery_project
    if delivery_enabled(task):
        validate_delivery(task,data)
        validate_fact_origins(data,evidence)
        if task.get('product_delivery')!=delivery_project(task): raise ValueError('PRODUCT_DELIVERY_PROJECTION_CHANGED')
    if data.get('scope_sha256')!=sha256_json(content(data)):
        raise ValueError('PRODUCT_SCOPE_CHANGED')
    records=evidence.get('collections',{}).get('product_scope',[])
    saved=next((v for v in records if v.get('evidence_id')==data.get('evidence_id')),None)
    if not saved or saved.get('scope')!=content(data): raise ValueError('PRODUCT_SCOPE_RECEIPT_MISSING')
    path=resolve_retained_path(Path(task_dir),saved['path'],expected_sha256=saved['sha256'])
    raw=load_json(path)
    if raw!=saved['payload'] or raw.get('scope')!=content(data) or raw.get('result_task')!=saved.get('result_task'): raise ValueError('PRODUCT_SCOPE_RECEIPT_CHANGED')
    sources={v['evidence_id']:v for v in evidence.get('collections',{}).get('scope_sources',[])}
    registry={v.get('evidence_id') for rows in evidence.get('collections',{}).values() if isinstance(rows,list) for v in rows if isinstance(v,dict)}
    bound_sources={v['evidence_id']:v for v in raw.get('sources',[])}
    for permission in data.get('image_permissions',[]):
        if permission['status']=='allowed' and any(sources.get(ref,{}).get('kind') not in {'user_statement','document'} for ref in permission['source_refs']):
            raise ValueError('IMAGE_PERMISSION_SOURCE_INVALID')
    for row in data['objects']+data['facts']+data.get('candidate_links',[])+data.get('query_revalidations',[])+data.get('image_permissions',[]):
        refs=row.get('source_refs',[])+row.get('statement_refs',[])
        if any(ref not in registry for ref in refs): raise ValueError('PRODUCT_SCOPE_SOURCE_MISSING')
        for ref in refs:
            source=sources.get(ref)
            if source and source!=bound_sources.get(ref): raise ValueError('PRODUCT_SCOPE_SOURCE_RECEIPT_CHANGED')
            if source and source.get('path'):
                resolve_retained_path(Path(task_dir),source['path'],expected_sha256=source['sha256'],expected_bytes=source['bytes'])
            if source and 'text' in source and sha256_json(source['text'])!=source['sha256']:
                raise ValueError('PRODUCT_SCOPE_SOURCE_CHANGED')
        if row.get('statement_refs') and any(sources.get(ref,{}).get('kind')!='user_statement' for ref in row['statement_refs']):
            raise ValueError('PRODUCT_SCOPE_STATEMENT_SOURCE_INVALID')
    if task.get('execution_scenario_ids')!=saved['result_task'].get('execution_scenario_ids'):
        raise ValueError('PRODUCT_SCOPE_SCENARIO_PROJECTION_CHANGED')
    if task['product'].get('scope_objects')!=data['objects']:
        raise ValueError('PRODUCT_SCOPE_OBJECT_PROJECTION_CHANGED')


def _value(task,path):
    if not path.startswith(('product.','images[')): return None,False
    value=task
    try:
        for token,index in re.findall(r'([\w]+)|\[(\d+)\]',path):
            value=value[int(index)] if index else value[token]
        return value,True
    except (KeyError,IndexError,TypeError): return None,False


def direction_state(task,direction):
    data=scope(task); objects={v['object_id']:v for v in data['objects']}; facts={v['fact_id']:v for v in data['facts']}
    selected=[objects[v] for v in direction['object_ids']]
    if any(v['scope_status']=='pending' for v in selected): return 'awaiting_user'
    if selected and any(v['scope_status'] in {'default_excluded','user_excluded'} for v in selected): return 'out_of_scope'
    for fid in direction['fact_ids']:
        fact=facts[fid]
        if fact['status']!='confirmed': return 'awaiting_user'
        value,exists=_value(task,fact['source_path'])
        if fact['source_path'].startswith(('product.','images[')) and (not exists or sha256_json(value)!=sha256_json(fact['value'])):
            return 'awaiting_review'
    return 'ready'


def direction_digest(task,direction):
    data=scope(task); facts={v['fact_id']:v for v in data['facts']}; objects={v['object_id']:v for v in data['objects']}
    return sha256_json({'direction':{k:direction[k] for k in ('direction_id','scenario_id','right_type','fact_ids','object_ids')},
        'facts':[{k:v for k,v in facts[f].items() if k not in {'reason','question'}} for f in direction['fact_ids']],
        'objects':[{k:v for k,v in objects[o].items() if k not in {'reason','question','checked_information','location'}} for o in direction['object_ids']]})


def direction_content_digest(task,direction):
    """Immutable query content; new proof/status can validate the same request."""
    data=scope(task); facts={v['fact_id']:v for v in data['facts']};objects={v['object_id']:v for v in data['objects']}
    return sha256_json({'direction':{k:direction[k] for k in ('direction_id','scenario_id','right_type','fact_ids','object_ids')},
        'facts':[{k:facts[f].get(k) for k in ('source_path','value')} for f in direction['fact_ids']],
        'objects':[{k:objects[o].get(k) for k in ('object_id','kind','relation','scope_status','text','description','right_types')} for o in direction['object_ids']]})


def directions(task,sid=None,right=None):
    return [v for v in scope(task)['directions'] if (sid is None or v['scenario_id']==sid) and (right is None or v['right_type']==right)]


def matching(task,paths,right,sid=None):
    data=scope(task); facts={v['fact_id']:v for v in data['facts']}; indexes={v['object_id']:i for i,v in enumerate(data['objects'])}
    result=[]
    for d in directions(task,sid,right):
        sources={facts[f]['source_path'] for f in d['fact_ids']}|{f'product.scope_objects[{indexes[o]}]' for o in d['object_ids']}
        if set(paths)&sources: result.append(d)
    return result


def term_allowed(task,term,right):
    return any(direction_state(task,d)!='out_of_scope' for d in matching(task,[term['derived_from']],right))


def bind(task,row,bindings):
    paths=row.get('derived_from',[])
    matched=matching(task,paths,row.get('right_type'))
    if not matched and (row.get('candidate_id') or row.get('triage_candidate_id') or row.get('action_purpose')=='provenance'):
        matched=directions(task,row.get('scenario_id'),row.get('right_type'))
        cid=row.get('candidate_id') or row.get('triage_candidate_id')
        if cid:
            links=[v for v in scope(task).get('candidate_links',[]) if v['candidate_id']==cid]
            ids=set(links[0]['object_ids']) if links else set()
            matched=[d for d in matched if ids & set(d['object_ids'])]
    ids={b['scenario_id'] for b in bindings}
    matched=[d for d in matched if d['scenario_id'] in ids and direction_state(task,d)!='out_of_scope']
    row['product_scope_revision']=REVISION
    row['product_dependencies']=[{'direction_id':d['direction_id'],'scenario_id':d['scenario_id'],'sha256':direction_digest(task,d),'content_sha256':direction_content_digest(task,d),'right_type':d['right_type'],'fact_ids':list(d['fact_ids']),'object_ids':list(d['object_ids'])} for d in matched]
    return [b for b in bindings if any(d['scenario_id']==b['scenario_id'] for d in matched)]


def dependency_identity_matches(direction,ref,row):
    return (direction['scenario_id']==ref.get('scenario_id') and direction['right_type']==row.get('right_type')==ref.get('right_type')
            and direction['fact_ids']==ref.get('fact_ids') and direction['object_ids']==ref.get('object_ids'))


def binding_state(task,row,sid=None):
    if not enabled(task): return 'ready'
    if row.get('product_scope_revision')!=REVISION: return 'awaiting_review'
    paths=set(row.get('derived_from',[]))
    for fact in scope(task)['facts']:
        if fact['source_path'] in paths:
            if fact['status']!='confirmed': return 'awaiting_user'
            value,exists=_value(task,fact['source_path'])
            if fact['source_path'].startswith(('product.','images[')) and (not exists or sha256_json(value)!=sha256_json(fact['value'])): return 'awaiting_review'
    for i,obj in enumerate(scope(task)['objects']):
        if f'product.scope_objects[{i}]' in paths and obj['scope_status']!='included':
            return 'awaiting_user' if obj['scope_status']=='pending' else 'awaiting_review'
    current={d['direction_id']:d for d in directions(task)}
    refs=[v for v in row.get('product_dependencies',[]) if sid is None or v['scenario_id']==sid]
    if not refs: return 'awaiting_review'
    approvals=[v for v in scope(task).get('query_revalidations',[]) if v['query_id']==row.get('query_id') and v['plan_entry_sha256']==sha256_json(row)]
    revalidated=approvals[0]['direction_digests'] if approvals else {}
    states=[];valid_paths=set()
    facts={f['fact_id']:f for f in scope(task)['facts']}; indexes={o['object_id']:i for i,o in enumerate(scope(task)['objects'])}
    consumed=paths & ({f['source_path'] for f in facts.values()}|{f'product.scope_objects[{i}]' for i in indexes.values()})
    for ref in refs:
        d=current.get(ref['direction_id'])
        if not d or not dependency_identity_matches(d,ref,row): states.append('awaiting_review');continue
        state=direction_state(task,d)
        if state=='ready' and ref['sha256']!=direction_digest(task,d) and ref.get('content_sha256')!=direction_content_digest(task,d) and revalidated.get(d['direction_id'])!=direction_digest(task,d): state='awaiting_review'
        states.append(state)
        if state=='ready': valid_paths.update({facts[f]['source_path'] for f in d['fact_ids']}|{f'product.scope_objects[{indexes[o]}]' for o in d['object_ids']})
    if consumed-valid_paths and 'ready' in states: return 'awaiting_review'
    # A shared query is usable under any still-valid binding; coverage filters
    # the individual bindings separately. It does not clear the others' gaps.
    if 'ready' in states: return 'ready'
    return 'awaiting_user' if 'awaiting_user' in states else 'awaiting_review'


def dispatch_reason(task,row):
    if not enabled(task): return None
    state=binding_state(task,row)
    return None if state=='ready' else 'PRODUCT_SCOPE_WAITING' if state=='awaiting_user' else 'PRODUCT_SCOPE_REVIEW_REQUIRED'


def work_entries(task):
    if not enabled(task):
        return ([{'work_id':'WORK-product-scope-review','kind':'product_analysis','state':'ready','reason':'PRODUCT_SCOPE_REVIEW_REQUIRED'}]
                if task.get('product_scope_required') else [])
    data=scope(task); objects={o['object_id']:o for o in data['objects']}; facts={f['fact_id']:f for f in data['facts']}
    entries=[]
    for d in data['directions']:
        state=direction_state(task,d)
        if state in {'ready','out_of_scope'}: continue
        causes=[objects[o] for o in d['object_ids'] if objects[o]['scope_status']=='pending']+[facts[f] for f in d['fact_ids'] if facts[f]['status']!='confirmed']
        from product_feedback import structure_policy_enabled, structural_fact
        questions=list(dict.fromkeys(v['question'] for v in causes if v.get('question')
            and not (structure_policy_enabled(task) and v.get('fact_id') and structural_fact(v))))
        entries.append({'work_id':'WORK-'+sha256_json({'task':task['task_id'],'direction':d['direction_id'],'causes':causes})[:24],
            'scenario_id':d['scenario_id'],'right_type':d['right_type'],'direction_id':d['direction_id'],
            'kind':'user_information' if state=='awaiting_user' else 'product_analysis',
            'state':'awaiting_user' if state=='awaiting_user' else 'ready','reason':'PRODUCT_SCOPE_WAITING' if state=='awaiting_user' else 'PRODUCT_SCOPE_REVIEW_REQUIRED',
            'question':'；'.join(questions),'fact_ids':d['fact_ids'],'object_ids':d['object_ids'],
            'evidence_refs':list(dict.fromkeys(r for v in causes for r in v.get('source_refs',[]))),
            'reasoning':d['reason']})
    for gap in readiness(task)['gaps']:
        if gap['code'] in {'PRODUCT_CLUE_UNACCOUNTED','CLUE_DISPOSITIONS_INVALID'}:
            entries.append({'work_id':'WORK-clue-'+sha256_json(gap)[:24],'kind':'product_analysis','state':'ready','reason':gap['code'],'source_path':gap.get('source_path')})
    bound_facts={fid for direction in data['directions'] for fid in direction['fact_ids']}
    for fact in data['facts']:
        if (fact['fact_id'] in bound_facts or fact.get('status')=='confirmed'
                or not fact.get('source_path','').startswith('product.raw_capture.ocr_text[')):
            continue
        entries.append({'work_id':'WORK-clue-verify-'+sha256_json({'task':task['task_id'],'fact':fact})[:24],
            'kind':'user_information','state':'awaiting_user','reason':'PRODUCT_CLUE_VERIFICATION_REQUIRED',
            'source_path':fact['source_path'],'fact_ids':[fact['fact_id']],
            'question':fact['question'],'evidence_refs':fact['source_refs']})
    from product_feedback import pending as pending_feedback
    for request in pending_feedback(task):
        entries.append({'work_id':'WORK-feedback-'+request['request_id'],
            'kind':'user_information','state':'awaiting_user','reason':'PRODUCT_FACT_FEEDBACK_PENDING',
            'scenario_id':request['scenario_id'],'right_type':request['right_type'],
            'direction_id':request['direction_id'],'candidate_id':request.get('candidate_id') or None,
            'jurisdiction':request['jurisdiction'],'fact_ids':[request['fact_id']],
            'question':request['question'],'purpose':request['purpose'],
            'minimum_information':request['minimum_information'],
            'evidence_refs':request['source_refs']})
    bound={o for d in data['directions'] for o in d['object_ids']}
    for obj in data['objects']:
        if obj['object_id'] in bound or obj['scope_status'] not in {'included','pending'}: continue
        pending=obj['scope_status']=='pending'
        entries.append({'work_id':'WORK-'+sha256_json({'task':task['task_id'],'object':obj['object_id']})[:24],
            'kind':'user_information' if pending else 'product_analysis','state':'awaiting_user' if pending else 'ready',
            'reason':'PRODUCT_SCOPE_WAITING' if pending else 'PRODUCT_DIRECTION_UNREVIEWED',
            'object_ids':[obj['object_id']], 'question':obj.get('question',''), 'evidence_refs':obj['source_refs']})
    from product_feedback import unavailable, structure_limitation_entry
    for request in unavailable(task):
        limit = structure_limitation_entry(task, request=request)
        if limit: entries.append({'work_id':'WORK-feedback-'+request['request_id'], **limit})
    # Missing structural facts remain unknown but no longer create a user question.
    facts_by_id = {row['fact_id']: row for row in data['facts']}
    for entry in entries:
        if entry.get('reason') != 'PRODUCT_SCOPE_WAITING': continue
        unknown = [fid for fid in entry.get('fact_ids', []) if facts_by_id[fid]['status'] != 'confirmed']
        pending_objects = [oid for oid in entry.get('object_ids', []) if objects[oid]['scope_status'] == 'pending']
        limit = structure_limitation_entry(task, fact_ids=unknown, direction_id=entry.get('direction_id'))
        if limit and not pending_objects: entry.update(limit)
    for entry in entries: entry['question_asked']=entry['work_id'] in task.get('scope_questions_asked',[])
    return [{**entry,'jurisdiction':country} for entry in entries
            for country in ([entry['jurisdiction']] if entry.get('jurisdiction')
                            else task.get('target_jurisdictions',[]) or [None])]


def project_work(task,view,plan=None):
    if not enabled(task) and not task.get('product_scope_required'): return view
    result=deepcopy(view)
    entries=[v for v in result.get('entries',[]) if v.get('reason')!='PRODUCT_SCOPE_WAITING']
    for entry in entries:
        if entry.get('reason')=='PRODUCT_SCOPE_REVIEW_REQUIRED': entry.update(kind='product_analysis',state='ready')
    entries.extend(work_entries(task))
    for provider,rows in (plan or {}).get('queries',{}).items():
        for row in rows:
            from workflow_v24 import validated_query_cancellation, validated_query_substitution
            if validated_query_cancellation(task, plan, row) or validated_query_substitution(task, plan, row):
                continue
            if provider == 'asset_provenance':
                from record_asset_provenance import asset_scope
                scenario_ids = [binding.get('scenario_id') for binding in row.get('scenario_bindings', [])
                                if binding.get('scenario_id')]
                if scenario_ids and all(
                    row.get('asset_scope_sha256') != asset_scope(task, sid, row.get('right_type'))['scope_sha256']
                    for sid in scenario_ids
                ):
                    # A changed asset inventory creates a new immutable query row.
                    # Revalidating only product directions cannot update the old row's asset digest.
                    continue
                if not scenario_ids and not row.get('product_dependencies'):
                    current_scenarios = [scenario.get('scenario_id') for scenario in task.get('assessment_scenarios', [])
                                         if scenario.get('scenario_id')]
                    if current_scenarios and all(
                        (bound := asset_scope(task, sid, row.get('right_type')))['inventory_reviewed']
                        and not bound['asset_ids'] for sid in current_scenarios
                    ):
                        # No applicable mark or asset exists for this row in the reviewed current inventory.
                        continue
            if enabled(task) and binding_state(task,row)=='awaiting_review':
                entries.append({'work_id':'WORK-scope-'+row['query_id'],'query_id':row['query_id'],'provider':provider,
                    'scenario_id':row.get('scenario_id'),'jurisdiction':row.get('jurisdiction'),'right_type':row.get('right_type'),
                    'kind':'product_analysis','state':'ready','reason':'PRODUCT_SCOPE_REVIEW_REQUIRED'})
    result['entries']=entries
    result['counts']={s:sum(v.get('state')==s for v in entries) for s in ('ready','awaiting_review','awaiting_access','awaiting_user','submission_unknown','blocked')}
    if entries: result['status']='incomplete'
    result['work_view_sha256']=sha256_json({k:v for k,v in result.items() if k!='work_view_sha256'})
    return result


def scoped_content(task,sid,right,candidate_id=None):
    data=scope(task)
    ds=directions(task,sid,right)
    links=[v for v in data.get('candidate_links',[]) if v['candidate_id']==candidate_id]
    if candidate_id:
        ids=set(links[0]['object_ids']) if links else set()
        ds=[d for d in ds if ids & set(d['object_ids'])]
    return {'identity':task.get('product_identity',{}).get('sha256'),
        'candidate_links':links,
        'directions':[{'id':d['direction_id'],'digest':direction_digest(task,d),'state':direction_state(task,d)} for d in ds]}


def readiness(task):
    from product_entry import assert_frozen
    assert_frozen(task)
    validate(scope(task))
    # Preserve existing claim/clue obligations without reinstating the global
    # structure/analysis gate that this directional contract replaces.
    from workflow_v24 import product_analysis_readiness
    legacy=deepcopy(task);legacy.pop('product_scope_revision',None);legacy.pop('product_scope_required',None)
    result=product_analysis_readiness(legacy)
    facts=scope(task)['facts']
    gaps=[]
    for gap in result['gaps']:
        if gap['code'] in {'PRODUCT_STRUCTURE_MISSING','QUERY_TERMS_MISSING','PRODUCT_ANALYSIS_UNCONFIRMED','PRODUCT_ANALYSIS_STALE'}: continue
        if gap['code']=='PRODUCT_CLUE_UNACCOUNTED' and any(f['source_path']==gap.get('source_path') and sha256_json(f['value'])==gap.get('source_sha256') for f in facts): continue
        gaps.append({**gap,'blocking_planning':False})
    return {'ready':True,'gaps':gaps,'patent_claim_followup':result['patent_claim_followup']}


def required_rights(task,scenario,allowed):
    if not enabled(task): return allowed
    sid=scenario['scenario_id']
    data=scope(task)
    marks=[o for o in data['objects'] if o['kind'] in {'brand','logo'} and object_scenario(o)==sid and o['scope_status'] in {'included','pending'}]
    return allowed if marks else allowed-{'trademark_word','trademark_figurative'}


def asset_allowed(task,item):
    if not enabled(task): return True
    oid=item.get('object_id') or item.get('asset_id') or item.get('mark_id')
    obj=next((v for v in scope(task)['objects'] if v['object_id']==oid),None)
    if obj is None: raise ValueError('ASSET_SCOPE_OBJECT_REQUIRED: '+str(oid))
    return obj['scope_status']=='included'


def candidate_scope(task,sid,right,candidate,evidence=None):
    """Scope disposition only; never a fourth relevance decision."""
    links=[v for v in scope(task).get('candidate_links',[]) if v['candidate_id']==candidate.get('candidate_id')]
    if not links: return 'pending'
    objects={o['object_id']:o for o in scope(task)['objects']}
    relevant=[objects[o] for o in links[0]['object_ids'] if right in objects[o]['right_types'] and
              (sid=='genuine_resale' or object_scenario(objects[o])==sid)]
    if not relevant: return 'default_excluded'
    states={o['scope_status'] for o in relevant}
    # A single recalled right may relate to several independent product objects.
    # Keep its ready comparison reachable; other objects retain their own gaps.
    if 'included' in states:
        ds=[d for d in directions(task,sid,right) if set(d['object_ids']) & {o['object_id'] for o in relevant if o['scope_status']=='included'}]
        if any(direction_state(task,d)=='ready' for d in ds): return 'included'
        return 'pending'
    if 'pending' in states: return 'pending'
    return 'user_excluded' if states=={'user_excluded'} else 'default_excluded'


def coverage_gaps(task,sid,right):
    ds=directions(task,sid,right)
    if not ds:
        if task.get('retrieval_workflow_revision') == 'api-first-v3':
            # No applicable object means no product-direction dependency. This
            # does not establish legal exclusion or completed rights retrieval.
            relevant=[o for o in scope(task)['objects'] if right in o['right_types']
                and (sid=='genuine_resale' or object_scenario(o)==sid)
                and o['scope_status'] in {'included','pending'}]
            if not relevant: return []
        return ['PRODUCT_DIRECTION_UNREVIEWED']
    return ['PRODUCT_DEPENDENCY_'+direction_state(task,d).upper()+':'+d['direction_id'] for d in ds if direction_state(task,d) not in {'ready','out_of_scope'}]
