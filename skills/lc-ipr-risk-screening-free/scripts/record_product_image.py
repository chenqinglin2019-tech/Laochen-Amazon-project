#!/usr/bin/env python3
"""Retain image transformations without replacing originals or rotating query mains."""
from __future__ import annotations

import argparse
from copy import deepcopy
from pathlib import Path
import shutil

from common import atomic_write_json, image_info, load_json, now_iso, sha256_file, sha256_json, stable_id
from execution_lock import execution_lock
from product_change import append_image_supplement, retain_event
from product_entry import assert_frozen, evidence_errors
import product_scope as ps


def record(task_dir: Path, input_path: Path):
    task_dir,input_path=task_dir.resolve(),input_path.resolve()
    with execution_lock(task_dir,'product'):
        task=load_json(task_dir/'task.json'); evidence=load_json(task_dir/'evidence.json')
        assert_frozen(task)
        errors=evidence_errors(task,evidence,task_dir)
        if errors: raise ValueError('; '.join(errors))
        if not ps.enabled(task): raise ValueError('PRODUCT_SCOPE_REQUIRED_FOR_IMAGE_CHANGE')
        ps.verify(task,evidence,task_dir)
        payload=load_json(input_path)
        if (not isinstance(payload,dict) or payload.get('schema_version')!='product-image-change-v1'
                or payload.get('relation') not in {'recompression','crop','additional_view'}
                or payload.get('expected_target_sha256')!=task['product_identity']['sha256']
                or payload.get('expected_scope_sha256')!=task['product_scope']['scope_sha256']
                or not isinstance(payload.get('review'),dict)
                or not str(payload['review'].get('reviewer','')).strip()
                or not str(payload['review'].get('reason','')).strip()):
            raise ValueError('PRODUCT_IMAGE_CHANGE_INPUT_INVALID')
        original=next((row for row in task['images'] if row.get('image_id')==payload.get('original_image_id')),None)
        if not original: raise ValueError('PRODUCT_IMAGE_ORIGINAL_MISSING')
        review=payload['review']; relation=payload['relation']
        if (review.get('content_effect') not in {'same_content','new_information'}
                or relation=='recompression' and review['content_effect']!='same_content'
                or relation=='additional_view' and review['content_effect']!='new_information'):
            raise ValueError('PRODUCT_IMAGE_CONTENT_REVIEW_REQUIRED')
        file=Path(payload.get('path','')).expanduser()
        file=(input_path.parent/file).resolve() if not file.is_absolute() else file.resolve()
        if not file.is_file(): raise ValueError('PRODUCT_IMAGE_CHANGE_FILE_MISSING')
        digest=sha256_file(file); mime,width,height=image_info(file)
        if not mime.startswith('image/') or min(width,height)<=0:
            raise ValueError('PRODUCT_IMAGE_CHANGE_FILE_INVALID')
        destination=task_dir/'raw'/'product_images'/f'{digest}{file.suffix.lower()}'
        destination.parent.mkdir(parents=True,exist_ok=True)
        if destination.is_file():
            if sha256_file(destination)!=digest: raise ValueError('PRODUCT_IMAGE_RETAINED_FILE_CHANGED')
        else:
            shutil.copyfile(file,destination)
            if sha256_file(destination)!=digest: raise ValueError('PRODUCT_IMAGE_CHANGED_DURING_COPY')
        image_id='IMG-S-'+digest[:16]
        record={'image_id':image_id,'original_image_id':original['image_id'],
                'relation':relation,'content_effect':review['content_effect'],
                'reviewer':review['reviewer'],'reason':review['reason'],
                'product_id':task['product']['product_id'],'target_sha256':task['product_identity']['sha256'],
                'path':str(destination),'sha256':digest,'bytes':destination.stat().st_size,
                'mime_type':mime,'width':width,'height':height,'recorded_at':now_iso()}
        eid=stable_id('EV','product_image',task['task_id'],image_id,relation)
        record['evidence_id']=eid
        retained=evidence['collections'].setdefault('product_images',[])
        previous=next((row for row in retained if row.get('evidence_id')==eid),None)
        if previous:
            if {k:v for k,v in previous.items() if k!='recorded_at'}!={k:v for k,v in record.items() if k!='recorded_at'}:
                raise ValueError('PRODUCT_IMAGE_RELATION_CONFLICT')
            return 'success'
        if relation in {'recompression','crop'} and review['content_effect']=='same_content':
            # A byte-only derivative remains outside the active evidence and
            # product images. Its relationship is independently retained; old
            # queries and judgments do not change just because the hash did.
            ledger=task_dir/'image-relationships.json'
            data=load_json(ledger) if ledger.is_file() else {'schema_version':'product-image-relationships-v1','task_id':task['task_id'],'items':[]}
            if (data.get('schema_version')!='product-image-relationships-v1'
                    or data.get('task_id')!=task['task_id'] or not isinstance(data.get('items'),list)):
                raise ValueError('PRODUCT_IMAGE_RELATION_LEDGER_INVALID')
            old=next((row for row in data['items'] if row.get('evidence_id')==eid),None)
            if old:
                if {k:v for k,v in old.items() if k!='recorded_at'}!={k:v for k,v in record.items() if k!='recorded_at'}:
                    raise ValueError('PRODUCT_IMAGE_RELATION_CONFLICT')
                return 'success'
            data['items'].append(record)
            atomic_write_json(ledger,data)
            receipts=evidence['collections'].setdefault('product_image_relationships',[])
            for receipt in receipts: receipt['ledger_sha256']=sha256_file(ledger)
            receipts.append({
                'evidence_id':eid,'ledger_path':str(ledger),
                'ledger_sha256':sha256_file(ledger),'record_sha256':sha256_json(record)})
            atomic_write_json(task_dir/'evidence.json',evidence)
            return 'success'
        fact_ids=payload.get('affected_fact_ids',[]); object_ids=payload.get('affected_object_ids',[])
        if (not isinstance(fact_ids,list) or not isinstance(object_ids,list) or not (fact_ids or object_ids)
                or not set(fact_ids)<={row['fact_id'] for row in task['product_scope']['facts']}
                or not set(object_ids)<={row['object_id'] for row in task['product_scope']['objects']}):
            raise ValueError('PRODUCT_IMAGE_IMPACT_REQUIRED')
        if task.get('product_change_pending'): raise ValueError('PRODUCT_CHANGE_SCOPE_REVIEW_PENDING')
        image={key:record[key] for key in ('image_id','path','sha256','bytes','mime_type','width','height')}
        image.update(role='product_view',source_kind='user_file',original_image_id=original['image_id'],
                     relation=relation,collected_at=record['recorded_at'])
        task['images'].append(image)
        task['product']['media_identity']=sorted({row['sha256'] for row in task['images']})
        retained.append(record)
        plan=load_json(task_dir/'search-plan.json') if (task_dir/'search-plan.json').is_file() else {}
        event=append_image_supplement(task_dir,task,evidence,plan,image_id=image_id,evidence_id=eid,
            fact_ids=fact_ids,object_ids=object_ids,reason=review['reason'])
        retain_event(task_dir,task,evidence,event)
        task['updated_at']=now_iso()
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
