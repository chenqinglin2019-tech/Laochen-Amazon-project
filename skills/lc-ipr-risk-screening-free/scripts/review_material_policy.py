"""Versioned original inventory; preserves the public-only transmission boundary."""
from copy import deepcopy
from pathlib import Path
from common import load_json, resolve_retained_path, stable_id
from review_judgment import ModelJudgmentError

REVISION = 'classified-public-originals-v1'
MANIFEST_REVISION = 'public-originals-v3'


def enabled(task):
    revision = task.get('review_material_policy_revision')
    if revision not in (None, REVISION):
        raise ValueError('REVIEW_MATERIAL_POLICY_REVISION_INVALID')
    return revision == REVISION


def file_inventory(packet):
    from report_review_host import review_payload_view
    found = {}
    def visit(value, refs=(), scope=None):
        if isinstance(value, list):
            for item in value:
                visit(item, refs, scope)
        elif isinstance(value, dict):
            reference = value.get('evidence_id') or value.get('image_id')
            refs = (reference,) if reference else refs
            scope = {**(scope or {}), **{key: value[key] for key in
                ('scenario_id', 'jurisdiction', 'right_type', 'candidate_id', 'object_id')
                if isinstance(value.get(key), str)}}
            if value.get('path') and value.get('sha256'):
                key = (str(value['path']), value['sha256'])
                row = found.setdefault(key, {'path': key[0], 'sha256': key[1], 'source_refs': [],
                    'affected_scopes': [], 'public': False, 'bytes': value.get('bytes')})
                row['source_refs'] = sorted(set(row['source_refs']) | set(refs))
                if scope and scope not in row['affected_scopes']:
                    row['affected_scopes'].append(deepcopy(scope))
                # An API record's own media row (the SerpApi adapter's retained copy of a drawing named by the record,
                # with its source field and public address) is a public original like any registered source.
                address = value.get('source_url') or (value.get('url') if value.get('source_field') else None)
                row['public'] = row['public'] or str(address or '').startswith(('http://', 'https://'))
            for key, child in value.items():
                if key != 'retained_originals':
                    visit(child, refs, scope)
    visit(review_payload_view(packet))
    scope = (packet.get('task') or {}).get('product_scope') or {}
    objects = {row['object_id']: row for row in scope.get('objects', [])}
    facts = {row['fact_id']: row for row in scope.get('facts', [])}
    for item in found.values():
        refs = set(item['source_refs'])
        for direction in scope.get('directions', []):
            bound = [objects[oid] for oid in direction.get('object_ids', []) if oid in objects]
            bound += [facts[fid] for fid in direction.get('fact_ids', []) if fid in facts]
            if not any(refs & (set(row.get('source_refs', [])) |
                    set((row.get('visual_evidence') or {}).get('image_ids', []))) for row in bound):
                continue
            affected = {key: direction[key] for key in ('scenario_id', 'right_type', 'direction_id') if key in direction}
            if affected and affected not in item['affected_scopes']:
                item['affected_scopes'].append(affected)
    # A second retained copy of a registered public original (the SerpApi adapter keeps a detail record's drawings
    # next to the record without an address; the core dossier registers the same bytes with their public address)
    # is that public original: classify() verifies the bytes, so the copy carries the same transmission basis
    # (r5c real run: REVIEW_MATERIAL_CLASSIFICATION_REQUIRED on such a copy stopped the final review).
    public_bytes = {item['sha256'] for item in found.values() if item['public']}
    for item in found.values():
        if not item['public'] and item['sha256'] in public_bytes:
            item['public'] = True
    return list(found.values())


def _file_key(row):
    return (str(row.get('path')), row.get('sha256')) if row.get('path') and row.get('sha256') else None


def _history_receipts(packet, task, evidence, root):
    """Bind formal receipt files to the exact history supplied to reviewers.

    product_scope.verify has already verified feedback/change recorders, their
    original files and historical dependencies. A valid disk receipt alone does
    not establish that its facts are present in this particular model packet.
    """
    from report_review_host import review_payload_view
    import product_change
    import product_feedback
    contracts = (
        ('product_feedback', 'product_feedback_history', 'event_id', 'product_feedback'),
        ('product_changes', 'product_change_history', 'change_id', 'product_change'),
        ('product_applicability', 'product_applicability_reviews', 'review_id', 'product_applicability'),
    )
    collections = evidence.get('collections', {})
    if not any(collections.get(name) or task.get(history) for name, history, _, _ in contracts):
        return {}
    if packet.get('task', {}).get('task_id') != task.get('task_id'):
        raise ValueError('REVIEW_INTERNAL_RECEIPT_INLINE_MISMATCH')
    expected = {'task': task, 'evidence_digest': packet.get('evidence_digest'),
                'evidence': {'collections': {name: collections.get(name, []) for name, _, _, _ in contracts}}}
    if packet.get('module_scope'):
        from module_review import module_packet
        candidate_file = root / 'normalized-candidates.json'
        expected['candidates'] = load_json(candidate_file) if candidate_file.is_file() else {}
        expected = module_packet(expected, packet['module_scope']['module_id'])
    internal = {}
    for collection, history, identity, namespace in contracts:
        records = task.get(history, [])
        receipts = collections.get(collection, [])
        if not isinstance(receipts, list) or len(receipts) != len(records):
            raise ValueError('REVIEW_INTERNAL_RECEIPT_HISTORY_MISMATCH')
        if receipts and not (product_feedback.enabled(task) if collection == 'product_feedback'
                             else product_change.enabled(task)):
            raise ValueError('REVIEW_INTERNAL_RECEIPT_CONTRACT_REQUIRED')
        actual_rows = (packet.get('evidence') or {}).get('collections', {}).get(collection, [])
        if (review_payload_view(actual_rows) != review_payload_view(expected['evidence']['collections'][collection])
                or review_payload_view(packet.get('task', {}).get(history, []))
                != review_payload_view(expected['task'].get(history, []))):
            raise ValueError('REVIEW_INTERNAL_RECEIPT_INLINE_MISMATCH')
        for receipt in receipts:
            matches = [row for row in records if row.get(identity) == receipt.get(identity)]
            if (len(matches) != 1 or not receipt.get(identity)
                    or receipt.get('evidence_id') != stable_id('EV', namespace, task['task_id'], receipt[identity])):
                raise ValueError('REVIEW_INTERNAL_RECEIPT_HISTORY_MISMATCH')
            path = resolve_retained_path(root, receipt.get('path', ''), expected_sha256=receipt.get('sha256', ''))
            if load_json(path) != matches[0]:
                raise ValueError('REVIEW_INTERNAL_RECEIPT_CHANGED')
            internal[_file_key(receipt)] = receipt
    return internal


def _verified_registrations(packet, task_dir):
    """Only actual recorder receipts establish local/inline classifications."""
    root = Path(task_dir)
    if not (root / 'task.json').is_file() or not (root / 'evidence.json').is_file():
        return {}, set()
    task, evidence = load_json(root / 'task.json'), load_json(root / 'evidence.json')
    internal, local = {}, set()
    import product_scope
    if product_scope.enabled(task):
        product_scope.verify(task, evidence, root)
        for event in evidence.get('collections', {}).get('product_scope', []):
            path = resolve_retained_path(root, event['path'], expected_sha256=event['sha256'])
            raw = load_json(path)
            if (raw != event.get('payload') or raw.get('scope') != event.get('scope')
                    or raw.get('result_task') != event.get('result_task')
                    or not isinstance(raw.get('scope'), dict)):
                raise ValueError('PRODUCT_SCOPE_RECEIPT_CHANGED')
            internal[_file_key(event)] = event
            local.update(_file_key(source) for source in raw.get('sources', [])
                         if source.get('kind') == 'document' and _file_key(source))
        history_receipts = _history_receipts(packet, task, evidence, root)
    else:
        history_receipts = {}
    from product_entry import enabled as product_enabled, evidence_errors
    if product_enabled(task):
        errors = evidence_errors(task, evidence, root)
        if errors:
            raise ValueError('REVIEW_REGISTERED_PRODUCT_INVALID: ' + '; '.join(errors))
        for event in evidence.get('collections', {}).get('product', []):
            if event.get('source') != 'user_materials':
                continue
            runs = [run for run in evidence.get('source_runs', []) if run.get('provider') == 'user_materials'
                and run.get('status') == 'success' and event.get('evidence_id') in run.get('evidence_ids', [])]
            if not runs:
                raise ValueError('REVIEW_REGISTERED_PRODUCT_RECEIPT_MISSING')
            for run in runs:
                if len(run.get('raw_paths', [])) != 1:
                    raise ValueError('REVIEW_REGISTERED_PRODUCT_RECEIPT_INVALID')
                raw = resolve_retained_path(root, run['raw_paths'][0], expected_sha256=run['payload_digest'])
                if load_json(raw) != event:
                    raise ValueError('REVIEW_REGISTERED_PRODUCT_RECEIPT_CHANGED')
            local.update(_file_key(row) for row in event.get('sources', [])
                if row.get('kind') in {'image', 'specification', 'description'} and _file_key(row))
            local.update(_file_key(row) for row in event.get('images', []) if _file_key(row))
        local.update(_file_key(row) for row in evidence.get('collections', {}).get('product_images', [])
            if _file_key(row) and any(_file_key(image) == _file_key(row) for image in task.get('images', [])))
    # The packet must contain the exact actual inline projection, not merely a
    # path pointing to a valid receipt in the task directory.
    from report_review_host import review_payload_view
    actual_rows = (packet.get('evidence') or {}).get('collections', {}).get('product_scope', [])
    referenced_keys = {_file_key(row) for row in file_inventory(packet)}
    for key, event in internal.items():
        expected = event
        if packet.get('module_scope'):
            from module_review import module_packet
            candidate_file = root / 'normalized-candidates.json'
            projected = module_packet({'task': packet['task'], 'evidence_digest': packet.get('evidence_digest'),
                'candidates': load_json(candidate_file) if candidate_file.is_file() else {},
                'evidence': {'collections': {'product_scope': [event]}}}, packet['module_scope']['module_id'])
            expected = projected['evidence']['collections']['product_scope'][0]
        matches = [row for row in actual_rows if _file_key(row) == key]
        # Only validate keys that this packet actually references (a module
        # can legitimately omit records outside its rights scope).
        if key in referenced_keys and (
                len(matches) != 1 or review_payload_view(matches[0]) != review_payload_view(expected)):
            raise ValueError('REVIEW_INTERNAL_RECEIPT_INLINE_MISMATCH')
    return {**internal, **history_receipts}, local


def classify(packet, task_dir):
    inventory = file_inventory(packet)
    internal, local = _verified_registrations(packet, task_dir)
    result = []
    for item in inventory:
        resolve_retained_path(Path(task_dir), item['path'], expected_sha256=item['sha256'],
                              expected_bytes=item.get('bytes'))
        key = (item['path'], item['sha256'])
        if not item['public'] and key not in internal and key not in local:
            raise ValueError('REVIEW_MATERIAL_CLASSIFICATION_REQUIRED: ' + Path(item['path']).name)
        category = ('public_original' if item['public'] else 'inline_internal_receipt'
                    if key in internal else 'not_transmitted')
        result.append({**{key: value for key, value in item.items() if key != 'public'},
            'classification': category,
            'reason': {'public_original': 'Registered HTTP(S) source; original reading uses the existing public-material contract.',
                'inline_internal_receipt': 'Recorder contract and retained bytes verified; structured factual content is already inline, not a separate legal original.',
                'not_transmitted': 'No registered public transmission basis. Original bytes were not sent or read by the reviewers; only explicit inline facts may be considered.'}[category]})
    return result


def attach_inventory(packet, task_dir):
    originals = packet['retained_originals']
    classified = classify(packet, task_dir)
    originals.update(revision=MANIFEST_REVISION, material_policy_revision=REVISION,
        file_inventory=classified,
        inline_internal_receipts=[deepcopy(row) for row in classified if row['classification'] == 'inline_internal_receipt'],
        not_transmitted=[deepcopy(row) for row in classified if row['classification'] == 'not_transmitted'])
    originals['reading_limitations'] += (' Local nonpublic originals are not transmitted. The not_transmitted inventory '
        'is an explicit reading gap, never a clearance or proof that the original was read. '
        'Internal receipt integrity is distinct from reading a legal original.')


def validate_inventory(packet):
    originals = packet.get('retained_originals') or {}
    if (originals.get('revision') != MANIFEST_REVISION
            or originals.get('material_policy_revision') != REVISION):
        raise ValueError('ADAPTIVE_MATERIAL_POLICY_MISMATCH')
    rows = originals.get('file_inventory')
    if not isinstance(rows, list):
        raise ValueError('ADAPTIVE_ORIGINAL_MANIFEST_INCOMPLETE')
    expected = {(row['path'], row['sha256']): row for row in file_inventory(packet)}
    actual = {}
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError('ADAPTIVE_ORIGINAL_MANIFEST_INCOMPLETE')
        key = (row.get('path'), row.get('sha256'))
        if key in actual or key not in expected:
            raise ValueError('ADAPTIVE_ORIGINAL_MANIFEST_INCOMPLETE')
        item = expected[key]
        if (row.get('classification') not in {'public_original', 'inline_internal_receipt', 'not_transmitted'}
                or item['public'] != (row['classification'] == 'public_original')
                or row.get('source_refs') != item['source_refs'] or row.get('affected_scopes') != item['affected_scopes']):
            raise ValueError('ADAPTIVE_ORIGINAL_CLASSIFICATION_MISMATCH')
        actual[key] = row
    if set(actual) != set(expected):
        raise ValueError('ADAPTIVE_ORIGINAL_MANIFEST_INCOMPLETE')
    for category, field in (('inline_internal_receipt', 'inline_internal_receipts'), ('not_transmitted', 'not_transmitted')):
        if originals.get(field) != [row for row in rows if row['classification'] == category]:
            raise ValueError('ADAPTIVE_ORIGINAL_CLASSIFICATION_MISMATCH')
    represented = {row['sha256'] for row in originals.get('materials', [])}
    if any(row['sha256'] not in represented for row in rows if row['classification'] == 'public_original'):
        raise ValueError('ADAPTIVE_ORIGINAL_MANIFEST_INCOMPLETE')


def validate_untransmitted_observations(raw, packet):
    """A reviewer must acknowledge the reading boundary, never invent reading."""
    originals = packet.get('retained_originals') or {}
    if enabled(packet.get('task') or {}) and not packet.get('modules'):
        validate_inventory(packet)
    statement = raw.get('final_review_statement')
    statement_limits = statement.get('limitations', '') if isinstance(statement, dict) else ''
    if packet.get('modules') and enabled(packet.get('task') or {}):
        for module in packet['modules']:
            for ack in module.get('judgment', {}).get('untransmitted_material_acknowledgements', {}).values():
                if not isinstance(statement_limits, str) or ack.get('limitations') not in statement_limits:
                    raise ModelJudgmentError('FINAL_REVIEW_UNTRANSMITTED_LIMITATION_DROPPED')
    if originals.get('revision') != MANIFEST_REVISION:
        return
    expected = {row['sha256'] for row in originals.get('not_transmitted', [])}
    if not expected:
        return
    values = raw.get('untransmitted_material_acknowledgements')
    if not isinstance(values, dict) or set(values) != expected:
        raise ModelJudgmentError('FINAL_REVIEW_UNTRANSMITTED_ACKNOWLEDGEMENTS_REQUIRED')
    for value in values.values():
        if (not isinstance(value, dict) or value.get('original_read') is not False
                or not isinstance(value.get('limitations'), str) or not value['limitations'].strip()):
            raise ModelJudgmentError('FINAL_REVIEW_UNTRANSMITTED_READING_CLAIM_INVALID')
        if not isinstance(statement_limits, str) or value['limitations'] not in statement_limits:
            raise ModelJudgmentError('FINAL_REVIEW_UNTRANSMITTED_LIMITATION_DROPPED')
