#!/usr/bin/env python3
"""Append sourced scope/fact updates without replacing product identity or history."""
from __future__ import annotations
import argparse
from copy import deepcopy
from pathlib import Path
import shutil
from common import atomic_write_json, load_json, now_iso, sha256_file, sha256_json, stable_id, resolve_retained_path
from execution_lock import execution_lock
from product_entry import assert_frozen, evidence_errors
import product_scope as ps


def record(task_dir: Path, input_path: Path, *, migrate=False):
    task_dir=task_dir.resolve(); input_path=input_path.resolve()
    with execution_lock(task_dir,'product'):
        task=load_json(task_dir/'task.json'); evidence=load_json(task_dir/'evidence.json')
        assert_frozen(task)
        errors=evidence_errors(task,evidence,task_dir)
        if errors: raise ValueError('; '.join(errors))
        if task.get('checkpoints',{}).get('credential_preflight',{}).get('status')!='success': raise ValueError('CREDENTIAL_PREFLIGHT_REQUIRED')
        if not task.get('product_scope_required') and not ps.enabled(task) and not migrate:
            raise ValueError('EXPLICIT_SCOPE_MIGRATION_REQUIRED')
        payload=load_json(input_path)
        if not isinstance(payload,dict) or set(payload)-{'schema_version','expected_scope_sha256','sources','scope','query_terms'} or payload.get('schema_version') not in {'product-scope-input-v1','product-scope-input-v2'}:
            raise ValueError('PRODUCT_SCOPE_INPUT_INVALID')
        from product_delivery import REVISION as DELIVERY_REVISION, enabled as delivery_enabled, validate_scope as validate_delivery, validate_fact_origins
        if delivery_enabled(task) and payload['schema_version']!='product-scope-input-v2':
            raise ValueError('PRODUCT_DELIVERY_DOWNGRADE_FORBIDDEN')
        request_hash=sha256_json(payload)
        events=evidence.setdefault('collections',{}).setdefault('product_scope',[])
        prior=next((v for v in events if v.get('request_sha256')==request_hash),None)
        current=task.get('product_scope',{}).get('scope_sha256','')
        prior_scope=deepcopy(task.get('product_scope',{}))
        base_task_sha256=sha256_json(task)
        if prior:
            if task.get('product_scope',{}).get('evidence_id')==prior['evidence_id']:
                ps.verify(task,evidence,task_dir);return 'success'
            if base_task_sha256!=prior.get('payload',{}).get('base_task_sha256'): raise ValueError('PRODUCT_SCOPE_STALE_REQUEST')
            task=deepcopy(prior['result_task'])
            ps.verify(task,evidence,task_dir)
            atomic_write_json(task_dir/'task.json',task)
            return 'success'
        if current!=payload.get('expected_scope_sha256',''): raise ValueError('PRODUCT_SCOPE_BASE_CHANGED')
        if ps.enabled(task): ps.verify(task,evidence,task_dir)
        sources=payload.get('sources',[])
        if not isinstance(sources,list): raise ValueError('PRODUCT_SCOPE_SOURCES_INVALID')
        retained=evidence['collections'].setdefault('scope_sources',[])
        aliases={}; seen=set()
        root=task_dir/'raw'/'product_scope'; root.mkdir(parents=True,exist_ok=True)
        for source in sources:
            if not isinstance(source,dict) or not ps._text(source.get('source_id')) or source['source_id'] in seen:
                raise ValueError('PRODUCT_SCOPE_SOURCE_ID_INVALID')
            seen.add(source['source_id'])
            kind=source.get('kind')
            if kind not in {'user_statement','document','agent_observation'}: raise ValueError('PRODUCT_SCOPE_SOURCE_KIND_INVALID')
            if bool(source.get('path'))==bool(source.get('text')): raise ValueError('PRODUCT_SCOPE_SOURCE_PATH_OR_TEXT_REQUIRED')
            if kind=='user_statement' and not ps._text(source.get('text')): raise ValueError('USER_STATEMENT_TEXT_REQUIRED')
            row={'kind':kind}
            if source.get('path'):
                path=(input_path.parent/Path(source['path']).expanduser()).resolve()
                if not path.is_file(): raise ValueError('PRODUCT_SCOPE_SOURCE_MISSING')
                digest=sha256_file(path); target=root/(digest+path.suffix)
                if not target.exists(): shutil.copyfile(path,target)
                if sha256_file(target)!=digest: raise ValueError('PRODUCT_SCOPE_SOURCE_CHANGED')
                row.update(path=str(target),sha256=digest,bytes=target.stat().st_size)
            else:
                if not ps._text(source['text']): raise ValueError('PRODUCT_SCOPE_SOURCE_TEXT_REQUIRED')
                row.update(text=source['text'],sha256=sha256_json(source['text']))
            eid=stable_id('EV','scope_source',task['task_id'],sha256_json(row))
            aliases[source['source_id']]=eid;row['evidence_id']=eid
            if not any(v.get('evidence_id')==eid for v in retained): retained.append(row)
        data=deepcopy(payload.get('scope'))
        if not isinstance(data,dict): raise ValueError('PRODUCT_SCOPE_REQUIRED')
        for group in ('objects','facts','candidate_links','query_revalidations','image_permissions'):
            for item in data.get(group,[]):
                for field in ('source_refs','statement_refs'):
                    if field in item:
                        if not isinstance(item[field],list) or any(not isinstance(v,str) for v in item[field]): raise ValueError('PRODUCT_SCOPE_REFERENCE_INVALID')
                        item[field]=[aliases.get(v,v) for v in item[field]]
                if group=='objects': item['scope_status']=ps.object_state(item)
        trial={**task,'product_scope':data}
        plan=load_json(task_dir/'search-plan.json') if (task_dir/'search-plan.json').is_file() else {}
        for approval in data.get('query_revalidations',[]):
            if not ps._text(approval.get('review_id')): raise ValueError('QUERY_SCOPE_REVALIDATION_ID_REQUIRED')
            previous=None
            for old_event in reversed(events):
                previous=next((v for v in old_event.get('scope',{}).get('query_revalidations',[]) if v.get('review_id')==approval['review_id']),None)
                if previous:
                    retained_path=resolve_retained_path(task_dir,old_event['path'],expected_sha256=old_event['sha256'])
                    raw_event=load_json(retained_path)
                    if raw_event!=old_event['payload'] or raw_event['scope']!=old_event['scope']:
                        raise ValueError('QUERY_SCOPE_REVALIDATION_RECEIPT_CHANGED')
                    break
            if previous:
                if {k:v for k,v in approval.items() if k!='direction_digests'}!={k:v for k,v in previous.items() if k!='direction_digests'}:
                    raise ValueError('QUERY_SCOPE_REVALIDATION_ID_REUSED')
                approval['direction_digests']=deepcopy(previous['direction_digests'])
                continue
            rows=[r for values in plan.get('queries',{}).values() for r in values if r.get('query_id')==approval.get('query_id')]
            if len(rows)!=1 or sha256_json(rows[0])!=approval.get('plan_entry_sha256'):
                raise ValueError('QUERY_SCOPE_REVALIDATION_PLAN_MISMATCH')
            ids={v['direction_id'] for v in rows[0].get('product_dependencies',[])}
            ds=[d for d in data.get('directions',[]) if d['direction_id'] in ids]
            refs={v['direction_id']:v for v in rows[0].get('product_dependencies',[])}
            if any(not ps.dependency_identity_matches(d,refs[d['direction_id']],rows[0]) for d in ds):
                raise ValueError('QUERY_SCOPE_REVALIDATION_IDENTITY_CHANGED')
            if not ids or len(ds)!=len(ids) or any(ps.direction_state(trial,d)!='ready' for d in ds):
                raise ValueError('QUERY_SCOPE_REVALIDATION_DEPENDENCY_NOT_READY')
            approval['direction_digests']={d['direction_id']:ps.direction_digest(trial,d) for d in ds}
        ps.validate(data)
        if payload['schema_version']=='product-scope-input-v2':
            validate_delivery(task,data)
            validate_fact_origins(data,evidence)
            previous={row['fact_id']:row for row in task.get('product_scope',{}).get('facts',[])}
            for fact in data['facts']:
                old=previous.get(fact['fact_id'])
                if old and (fact['version']<old.get('version',0) or
                        (fact['version']==old.get('version') and any(fact.get(k)!=old.get(k)
                         for k in ('value','nature','verification','status','source_path','applies_to')))):
                    raise ValueError('PRODUCT_FACT_VERSION_NOT_ADVANCED')
            task['product_delivery_revision']=DELIVERY_REVISION
        elif data.get('delivery_revision'):
            raise ValueError('PRODUCT_DELIVERY_INPUT_VERSION_REQUIRED')
        if data.get('candidate_links'):
            candidate_path=task_dir/'normalized-candidates.json'
            from annotate_materiality import iter_candidates
            known={v['candidate_id'] for _,v in iter_candidates(load_json(candidate_path))} if candidate_path.is_file() else set()
            if any(v['candidate_id'] not in known for v in data['candidate_links']): raise ValueError('CANDIDATE_SCOPE_CANDIDATE_UNKNOWN')
        if any(d['scenario_id']=='genuine_resale' for d in data['directions']) and not task['request'].get('genuine_resale'):
            raise ValueError('GENUINE_RESALE_EXPLICIT_REQUEST_REQUIRED')
        # Preserve scenario definitions and prior query hashes. Activation is
        # explicit work selection, not a redefinition of historical scenarios.
        execution=['product_entry']
        if any(o['scope_status']=='included' and ps.object_scenario(o)=='brand_reuse' for o in data['objects']): execution.append('brand_reuse')
        if task['request'].get('genuine_resale'): execution.append('genuine_resale')
        task['execution_scenario_ids']=execution
        task['product_scope_revision']=ps.REVISION
        task['product_scope_required']=True
        task['product']['scope_objects']=deepcopy(data['objects'])
        task['product']['scope_assumption']=ps.DEFAULT_ASSUMPTION
        # Only source-backed, explicitly supplied terms are added. Scope terms
        # themselves do not assert a provider query succeeded.
        if 'query_terms' in payload:
            if not isinstance(payload['query_terms'],list): raise ValueError('QUERY_TERMS_INVALID')
            task['query_terms']=deepcopy(payload['query_terms'])
        digest=sha256_json(ps.content(data)); eid=stable_id('EV','product_scope',task['task_id'],request_hash)
        task['product_scope']={**data,'scope_sha256':digest,'evidence_id':eid}
        if payload['schema_version']=='product-scope-input-v2':
            from product_delivery import project as delivery_project
            task['product_delivery']=delivery_project(task)
            if task.get('product_change_pending'):
                latest=task.get('product_change_history',[])[-1]
                if latest.get('kind')=='image_supplement':
                    image_id=latest['image_id']
                    source_ids=set(latest.get('source_refs',[]))
                    used=any(image_id in obj.get('visual_evidence',{}).get('image_ids',[]) for obj in data['objects'])
                    used=used or any(source_ids & set(fact.get('source_refs',[])) for fact in data['facts'])
                    if not used: raise ValueError('PRODUCT_IMAGE_SUPPLEMENT_SCOPE_BINDING_REQUIRED')
                task['product_change_pending']=False
            if current:
                from product_change import append_scope_change, retain_event
                change_event=append_scope_change(task_dir,task,evidence,prior_scope,data,plan,
                    prior_scope_sha256=current,scope_sha256=digest,reason=data['reasoning'])
                if change_event: retain_event(task_dir,task,evidence,change_event)
        from workflow_v24 import term_records
        term_records(task)
        raw=root/(eid+'.json')
        event_payload={'scope':ps.content(data),'sources':[v for v in retained if v['evidence_id'] in {ref for row in data['objects']+data['facts']+data.get('candidate_links',[])+data.get('query_revalidations',[])+data.get('image_permissions',[]) for key in ('source_refs','statement_refs') for ref in row.get(key,[])}],
                       'request_sha256':request_hash,'prior_scope_sha256':current,'base_task_sha256':base_task_sha256}
        if raw.exists():
            existing=load_json(raw)
            if {k:v for k,v in existing.items() if k!='result_task'}!=event_payload:
                raise ValueError('PRODUCT_SCOPE_RETAINED_EVENT_CONFLICT')
            task=deepcopy(existing['result_task']);event_payload=existing
        else:
            task.setdefault('product_scope_history',[]).append({'evidence_id':eid,'prior_scope_sha256':current,'scope_sha256':digest,'at':now_iso()})
            task['updated_at']=now_iso()
            event_payload['result_task']=deepcopy(task)
            atomic_write_json(raw,event_payload)
        event={'evidence_id':eid,'scope_sha256':digest,'scope':ps.content(data),'payload':event_payload,
               'path':str(raw),'sha256':sha256_file(raw),'request_sha256':request_hash,'result_task':deepcopy(task)}
        events.append(event)
        ps.verify(task,evidence,task_dir)
        atomic_write_json(task_dir/'evidence.json',evidence)
        atomic_write_json(task_dir/'task.json',task)
        return 'success'


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--task-dir',required=True,type=Path)
    parser.add_argument('--input',type=Path)
    parser.add_argument('--migrate',action='store_true')
    parser.add_argument('--mark-question-asked')
    args=parser.parse_args()
    if args.mark_question_asked:
        if args.input: parser.error('Use one action')
        with execution_lock(args.task_dir.resolve(),'product'):
            task=load_json(args.task_dir/'task.json')
            if args.mark_question_asked not in {v['work_id'] for v in ps.work_entries(task)}: raise ValueError('SCOPE_QUESTION_NOT_CURRENT')
            asked=task.setdefault('scope_questions_asked',[])
            if args.mark_question_asked not in asked: asked.append(args.mark_question_asked)
            atomic_write_json(args.task_dir/'task.json',task)
    elif args.input: print(record(args.task_dir,args.input,migrate=args.migrate))
    else: parser.error('--input or --mark-question-asked required')

if __name__=='__main__': main()
