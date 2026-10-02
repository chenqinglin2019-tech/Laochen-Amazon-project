#!/usr/bin/env python3
"""Record source-backed applicability decisions for retained candidates."""
from __future__ import annotations

import argparse
from pathlib import Path

from common import atomic_write_json, load_json, now_iso, sha256_json, stable_id, resolve_retained_path
from execution_lock import execution_lock
from product_change import enabled, verify, retain_applicability


def record(task_dir: Path, input_path: Path):
    task_dir, input_path = task_dir.resolve(), input_path.resolve()
    with execution_lock(task_dir,'product'):
        task=load_json(task_dir/'task.json'); evidence=load_json(task_dir/'evidence.json')
        verify(task,evidence,task_dir)
        if not enabled(task) or task.get('product_change_pending'):
            raise ValueError('PRODUCT_CHANGE_CURRENT_SCOPE_REQUIRED')
        payload=load_json(input_path)
        if (not isinstance(payload,dict) or payload.get('schema_version')!='product-applicability-v1'
                or payload.get('product_version')!=task['product_change_version']
                or payload.get('target_sha256')!=task['product_identity']['sha256']
                or payload.get('scope_sha256')!=task.get('product_scope',{}).get('scope_sha256')
                or not isinstance(payload.get('reviews'),list) or not payload['reviews']):
            raise ValueError('PRODUCT_APPLICABILITY_INPUT_INVALID')
        from annotate_materiality import iter_candidates
        candidates={item['candidate_id']:item for _,item in iter_candidates(load_json(task_dir/'normalized-candidates.json'))}
        known={row.get('evidence_id') for values in evidence.get('collections',{}).values()
               if isinstance(values,list) for row in values if isinstance(row,dict)}
        events={event['change_id']:event for event in task['product_change_history']}
        saved={(row['change_id'],row['candidate_id']):row for row in task.get('product_applicability_reviews',[])}
        added=[]
        for input_row in payload['reviews']:
            if not isinstance(input_row,dict): raise ValueError('PRODUCT_APPLICABILITY_ROW_INVALID')
            cid=input_row.get('candidate_id'); eid=input_row.get('change_id')
            event=events.get(eid); candidate=candidates.get(cid)
            refs=input_row.get('source_refs')
            if (not event or not candidate or cid not in event.get('affected_candidate_ids',[])
                    or input_row.get('status') not in {'usable','not_applicable','needs_info'}
                    or not str(input_row.get('reviewer','')).strip() or not str(input_row.get('reason','')).strip()
                    or not isinstance(refs,list) or not refs or not set(refs)<=known):
                raise ValueError('PRODUCT_APPLICABILITY_ROW_INVALID')
            row={'change_id':eid,'candidate_id':cid,'status':input_row['status'],
                 'reviewer':input_row['reviewer'],'reason':input_row['reason'],
                 'source_refs':list(refs),'old_evidence_refs':list(candidate.get('evidence_refs',[])),
                 'product_version':task['product_change_version'],
                 'target_sha256':task['product_identity']['sha256'],
                 'scope_sha256':task['product_scope']['scope_sha256']}
            row['review_id']=stable_id('REV',task['task_id'],eid,cid,str(task['product_change_version']))
            previous=saved.get((eid,cid))
            if previous:
                if {k:v for k,v in previous.items() if k not in {'reviewed_at','sha256'}}!=row:
                    raise ValueError('PRODUCT_APPLICABILITY_REVIEW_IMMUTABLE')
            else:
                receipt=next((item for item in evidence.get('collections',{}).get('product_applicability',[])
                              if item.get('review_id')==row['review_id']),None)
                if receipt:
                    path=resolve_retained_path(task_dir,receipt['path'],expected_sha256=receipt['sha256'])
                    retained=load_json(path)
                    if {k:v for k,v in retained.items() if k not in {'reviewed_at','sha256'}}!=row:
                        raise ValueError('PRODUCT_APPLICABILITY_REVIEW_IMMUTABLE')
                    row=retained
                else:
                    row['reviewed_at']=now_iso()
                    row['sha256']=sha256_json(row)
                saved[(eid,cid)]=row; added.append(row)
        if not added:
            return 'success'
        task['product_applicability_reviews']=list(saved.values())
        task['updated_at']=now_iso()
        for row in added: retain_applicability(task_dir,task,evidence,row)
        verify(task,evidence,task_dir)
        atomic_write_json(task_dir/'evidence.json',evidence)
        atomic_write_json(task_dir/'task.json',task)
        return 'success'


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--task-dir',required=True,type=Path)
    parser.add_argument('--input',required=True,type=Path)
    args=parser.parse_args()
    print(record(args.task_dir,args.input))


if __name__=='__main__': main()
