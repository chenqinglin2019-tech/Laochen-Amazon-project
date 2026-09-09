"""Explicit synthetic evidence for keyword tests; never used in production."""
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('keyword_quality_tests', ROOT / 'scripts/keyword_quality.py')
keywords = importlib.util.module_from_spec(spec)
spec.loader.exec_module(keywords)


def write(root, name, value):
    (root / name).write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')


def classify(record, decision='eligible', code='identity', facts=None):
    record.update(initial_decision=decision, decision=decision, reason_code=code,
                  reason='依据测试资料，本词指向猫轮廓门框装饰；按完整搜索对象判断。',
                  query_intent='寻找猫轮廓门框装饰', intent_group='door-frame-cat',
                  role='identity', label='high', fact_ids=facts or [], measurement_ids=[],
                  identity_basis=True, evidence='测试资料 product_identity 明确产品类型；非现实产品结论。',
                  applies_to=['all'], reviewer='fixture-first', promotion_condition='核实具体材料或使用意图后再评估。')
    return record


def make_run(root, profile=None, words=None):
    if profile is None:
        profile = {'site': 'US', 'listing_mode': 'single',
                   'product_identity': {'canonical_name': 'Black Cat Door Corner Decor',
                                        'protected_terms': ['Black Cat Door Corner Decor']},
                   'facts': [{'fact_id': 'metal', 'field': 'material', 'value': 'metal', 'status': 'confirmed', 'source_ref': 'synthetic specification'},
                             {'fact_id': 'iron', 'field': 'material', 'value': None, 'status': 'unknown', 'source_ref': 'not stated'},
                             {'fact_id': 'shape', 'field': 'shape', 'value': 'black cat silhouette', 'status': 'confirmed', 'source_ref': 'synthetic drawing'},
                             {'fact_id': 'purpose', 'field': 'function', 'value': 'ornament on indoor door frame', 'status': 'confirmed', 'source_ref': 'synthetic specification'}]}
    words = words or ['black cat door corner', 'topper corner door', 'nosy black cat bathroom door topper',
                      'microchip cat door', 'cat iron wall decoration', 'courtyard decoration black cat',
                      'halloween black cat decor', 'bat wall decor', 'metal black cat silhouette',
                      'black cat door sign', 'lightweight cat decor', '猫咪门角装饰',
                      ' Black Cat Door Corner ', 'cat’s door topper', "cat's door topper"]
    write(root, keywords.PROFILE, profile)
    write(root, keywords.RAW, {'keywords': words, 'raw': {'keyword_data': [{'keyword': words[0], 'searches': 0}]}})
    ledger = keywords.prepare(root)
    for record in keywords.all_records(ledger):
        classify(record)
        word = record['keyword']
        if word in ('microchip cat door', 'bat wall decor'):
            classify(record, 'excluded', 'product_mismatch', ['purpose' if word.startswith('microchip') else 'shape'])
            record['intent_group'] = word
        elif word in ('cat iron wall decoration', 'courtyard decoration black cat', 'halloween black cat decor', 'black cat door sign', 'lightweight cat decor'):
            classify(record, 'deferred', 'unknown_fact')
            record['intent_group'] = word
            if word.startswith('cat iron'):
                record['fact_ids'] = ['iron']; record['identity_basis'] = False
    write(root, keywords.DECISIONS, ledger)
    return profile, ledger
