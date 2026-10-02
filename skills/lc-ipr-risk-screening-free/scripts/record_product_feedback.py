#!/usr/bin/env python3
"""Record a downstream fact request or close it after a versioned scope update."""
from __future__ import annotations

import argparse
from pathlib import Path

from common import atomic_write_json, load_json, now_iso, sha256_file, sha256_json, stable_id, add_history
from execution_lock import execution_lock
from product_entry import evidence_errors
import product_feedback as pf
import product_scope as ps


def _text(value): return isinstance(value, str) and bool(value.strip())


def _retain(task_dir, task, evidence, row):
    row['sha256'] = sha256_json(row)
    path = task_dir/'raw'/'product_feedback'/(row['event_id']+'.json')
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_file():
        saved=load_json(path)
        if ({k:v for k,v in saved.items() if k not in {'at','sha256'}}
                != {k:v for k,v in row.items() if k not in {'at','sha256'}}):
            raise ValueError('PRODUCT_FEEDBACK_RECEIPT_CONFLICT')
        row.clear(); row.update(saved)
    else: atomic_write_json(path, row)
    receipt={
        'evidence_id':stable_id('EV','product_feedback',task['task_id'],row['event_id']),
        'event_id':row['event_id'],'path':str(path),'sha256':sha256_file(path)}
    retained=evidence['collections'].setdefault('product_feedback', [])
    existing=next((item for item in retained if item.get('event_id')==row['event_id']),None)
    if existing and existing!=receipt: raise ValueError('PRODUCT_FEEDBACK_RECEIPT_CONFLICT')
    if not existing: retained.append(receipt)
    task['product_feedback_revision'] = pf.REVISION
    task.setdefault('product_feedback_history', []).append(row)
    from product_delivery import project as delivery_project
    task['product_delivery']=delivery_project(task)
    task['updated_at'] = now_iso()
    task.pop('outputs', None)
    if task.get('state') in {'ready_for_assessment','assessing','needs_review','completed'}:
        add_history(task, 'collecting', 'A comparison needs a minimum product fact and targeted review.')


def record(task_dir: Path, input_path: Path):
    task_dir, input_path = task_dir.resolve(), input_path.resolve()
    with execution_lock(task_dir, 'product'):
        task = load_json(task_dir/'task.json')
        evidence = load_json(task_dir/'evidence.json')
        errors = evidence_errors(task, evidence, task_dir)
        if errors: raise ValueError('PRODUCT_EVIDENCE_INVALID: '+'; '.join(errors))
        if not ps.enabled(task) or task.get('product_delivery_revision') != 'image-fact-v1':
            raise ValueError('PRODUCT_FEEDBACK_SCOPE_V2_REQUIRED')
        if task.get('product_change_pending'):
            raise ValueError('PRODUCT_FEEDBACK_CURRENT_SCOPE_REQUIRED')
        payload = load_json(input_path)
        if not isinstance(payload, dict):
            raise ValueError('PRODUCT_FEEDBACK_INPUT_INVALID')
        if payload.get('action') == 'adopt_structure_policy':
            if (set(payload) - {'action', 'reviewer', 'reason'} or
                    not _text(payload.get('reviewer')) or not _text(payload.get('reason'))):
                raise ValueError('PRODUCT_STRUCTURE_POLICY_ADOPTION_BASIS_REQUIRED')
            # The new policy changes derived gaps, never archived source facts.
            before = sha256_json(task)
            task['product_structure_policy'] = pf.STRUCTURE_POLICY
            from product_delivery import project as delivery_project
            task['product_delivery'] = delivery_project(task)
            ps.verify(task, evidence, task_dir)
            task.setdefault('workflow_policy_updates', []).append({
                'policy': pf.STRUCTURE_POLICY, 'prior_task_sha256': before,
                'reviewer': payload['reviewer'], 'reason': payload['reason'],
                'input_sha256': sha256_json(payload), 'at': now_iso()})
            task['updated_at'] = now_iso()
            task.pop('outputs', None)
            atomic_write_json(task_dir/'task.json', task)
            return 'success'
        ps.verify(task, evidence, task_dir)
        pf.verify(task, evidence, task_dir)
        if not isinstance(payload, dict) or payload.get('schema_version') != pf.REVISION:
            raise ValueError('PRODUCT_FEEDBACK_INPUT_INVALID')
        known = {item.get('evidence_id') for group in evidence.get('collections',{}).values()
                 if isinstance(group,list) for item in group if isinstance(item,dict)}
        refs = payload.get('source_refs')
        if not isinstance(refs,list) or not refs or not set(refs)<=known:
            raise ValueError('PRODUCT_FEEDBACK_SOURCE_REQUIRED')
        if payload.get('action') == 'request':
            if (set(payload)-{'schema_version','action','stage','expected_target_sha256','expected_scope_sha256',
                              'direction_id','fact_id','candidate_id','jurisdiction','purpose',
                              'minimum_information','question','reason','requester','source_refs','information_category'}
                    or ('information_category' in payload and payload['information_category'] not in
                        pf.STRUCTURE_CATEGORIES | {'other'})
                    or payload.get('stage') not in {'search_planning','candidate_comparison'}
                    or payload.get('expected_target_sha256')!=task['product_identity']['sha256']
                    or payload.get('expected_scope_sha256')!=task['product_scope']['scope_sha256']
                    or payload.get('jurisdiction') not in task.get('target_jurisdictions',[])
                    or any(not _text(payload.get(key)) for key in
                           ('purpose','minimum_information','question','reason','requester'))):
                raise ValueError('PRODUCT_FEEDBACK_REQUEST_INVALID')
            direction = next((row for row in task['product_scope']['directions']
                              if row['direction_id']==payload.get('direction_id')), None)
            fact = next((row for row in task['product_scope']['facts']
                         if row['fact_id']==payload.get('fact_id')), None)
            if not direction or not fact or fact['fact_id'] not in direction['fact_ids']:
                raise ValueError('PRODUCT_FEEDBACK_DEPENDENCY_INVALID')
            candidate_id = payload.get('candidate_id') or ''
            if payload['stage']=='candidate_comparison':
                from annotate_materiality import iter_candidates
                path = task_dir/'normalized-candidates.json'
                candidates = {row['candidate_id']:row for _,row in iter_candidates(load_json(path))} if path.is_file() else {}
                candidate = candidates.get(candidate_id)
                if (not candidate or candidate.get('jurisdiction')!=payload['jurisdiction']
                        or candidate.get('right_type')!=direction['right_type']):
                    raise ValueError('PRODUCT_FEEDBACK_CANDIDATE_MISMATCH')
            elif candidate_id:
                raise ValueError('PRODUCT_FEEDBACK_CANDIDATE_UNEXPECTED')
            key = (payload['stage'], direction['direction_id'], fact['fact_id'],
                   candidate_id, payload['jurisdiction'])
            request_id = stable_id('FDB',task['task_id'],task['product_identity']['sha256'],
                                   task['product_scope']['scope_sha256'],*key)
            existing = next((row for row in pf.history(task) if row.get('request_id')==request_id
                             and row.get('kind') in {'requested','unavailable'}), None)
            if existing:
                if existing.get('input_sha256') != sha256_json(payload):
                    raise ValueError('PRODUCT_FEEDBACK_REQUEST_IMMUTABLE')
                return 'success'
            if any((row['stage'],row['direction_id'],row['fact_id'],row.get('candidate_id',''),
                    row['jurisdiction'])==key for row in pf.outstanding(task)):
                raise ValueError('PRODUCT_FEEDBACK_ALREADY_PENDING')
            row = {'event_id':stable_id('FDBEV','request',request_id),'request_id':request_id,
                   'kind':'requested','stage':payload['stage'],'direction_id':direction['direction_id'],
                   'scenario_id':direction['scenario_id'],'right_type':direction['right_type'],
                   'jurisdiction':payload['jurisdiction'],'fact_id':fact['fact_id'],
                   'fact_version':fact['version'],'candidate_id':candidate_id,
                   'product_change_version':task.get('product_change_version',1),
                   'target_sha256':task['product_identity']['sha256'],
                   'scope_sha256':task['product_scope']['scope_sha256'],
                   'purpose':payload['purpose'],'minimum_information':payload['minimum_information'],
                   'question':payload['question'],'reason':payload['reason'],
                   'requester':payload['requester'],'source_refs':refs,
                   'input_sha256':sha256_json(payload),'at':now_iso()}
            if 'information_category' in payload:
                row['information_category'] = payload['information_category']
            if pf.structure_request_unavailable(task, row):
                row.update(kind='unavailable', structure_policy=pf.STRUCTURE_POLICY,
                           structure_classification=pf.structure_request_classification(task, row))
        elif payload.get('action') == 'resolve':
            if (set(payload)-{'schema_version','action','request_id','expected_target_sha256',
                              'expected_scope_sha256','reviewer','reason','source_refs'}
                    or any(not _text(payload.get(key)) for key in
                           ('request_id','reviewer','reason'))
                    or payload.get('expected_target_sha256')!=task['product_identity']['sha256']
                    or payload.get('expected_scope_sha256')!=task['product_scope']['scope_sha256']):
                raise ValueError('PRODUCT_FEEDBACK_RESOLUTION_INPUT_INVALID')
            previous = next((row for row in pf.history(task) if row.get('kind')=='resolved'
                             and row.get('request_id')==payload['request_id']), None)
            if previous:
                if previous.get('input_sha256')!=sha256_json(payload):
                    raise ValueError('PRODUCT_FEEDBACK_RESOLUTION_IMMUTABLE')
                return 'success'
            request = next((row for row in pf.outstanding(task)
                            if row['request_id']==payload['request_id']), None)
            if not request or request['target_sha256']!=task['product_identity']['sha256']:
                raise ValueError('PRODUCT_FEEDBACK_REQUEST_NOT_PENDING')
            fact = next((row for row in task['product_scope']['facts']
                         if row['fact_id']==request['fact_id']), None)
            event = next((row for row in reversed(task.get('product_change_history',[]))
                          if row.get('target_sha256')==request['target_sha256']
                          and row.get('version',0)>request['product_change_version']
                          and any(change.get('id')==request['fact_id']
                                  and (change.get('after') or {}).get('version')==fact.get('version')
                                  for change in row.get('fact_changes',[]))), None) if fact else None
            if (not fact or fact.get('version',0)<=request['fact_version']
                    or fact.get('status')!='confirmed' or not set(refs)&set(fact.get('source_refs',[]))
                    or request['stage']=='candidate_comparison' and fact.get('verification')!='verified'
                    or not event or request.get('candidate_id')
                    and request['candidate_id'] not in event.get('affected_candidate_ids',[])):
                raise ValueError('PRODUCT_FEEDBACK_FACT_NOT_RESOLVED')
            row = {'event_id':stable_id('FDBEV','resolve',request['request_id'],
                                         task['product_scope']['scope_sha256']),
                   'request_id':request['request_id'],'kind':'resolved',
                   'target_sha256':task['product_identity']['sha256'],
                   'scope_sha256':task['product_scope']['scope_sha256'],
                   'fact_id':fact['fact_id'],'fact_version':fact['version'],
                   'change_id':event['change_id'],'reviewer':payload['reviewer'],
                   'reason':payload['reason'],'source_refs':refs,
                   'input_sha256':sha256_json(payload),'at':now_iso()}
        else:
            raise ValueError('PRODUCT_FEEDBACK_ACTION_INVALID')
        _retain(task_dir,task,evidence,row)
        pf.verify(task,evidence,task_dir)
        ps.verify(task,evidence,task_dir)
        atomic_write_json(task_dir/'evidence.json',evidence)
        atomic_write_json(task_dir/'task.json',task)
        return 'success'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--task-dir',required=True,type=Path)
    parser.add_argument('--input',required=True,type=Path)
    args = parser.parse_args()
    print(record(args.task_dir,args.input))


if __name__ == '__main__': main()
