"""Measure complete, decoded inputs before selecting two integrated sessions."""
from copy import deepcopy
import json
from common import sha256_json
from execution_efficiency import policy

REVISION = 'adaptive-double-review-v2'
UNIT_COUNT_REVISION = 'selected-scope-units-v1'


def required_review_unit_count(packet):
    """Use final assessment obligations, not candidate volume or priority flags.

    The task-bound revision preserves historical integrated execution receipts.
    Missing/stale triage remains a completion gap; it is not an invented need
    for a substantive candidate assessment or a clearance judgment.
    """
    from module_review import required_scopes, GROUPS
    task = packet['task']
    scopes = required_scopes(task, set().union(*GROUPS.values()))
    revision = task.get('review_unit_count_revision')
    if revision is None:
        return len(scopes)
    if revision != UNIT_COUNT_REVISION:
        raise ValueError('ADAPTIVE_UNIT_COUNT_REVISION_INVALID')
    from annotate_materiality import candidate_index, CANDIDATE_COLLECTIONS
    from decision_workflow import (decision_workflow_enabled, triage_summary,
        necessary_scenario_right_types, scenario_index, LEDGER_SCHEMA_VERSION)
    from final_review import unit_id
    if not scopes:
        raise ValueError('ADAPTIVE_REVIEW_SCOPES_UNMEASURABLE')
    units = {unit_id(scope) for scope in scopes}
    candidates = packet['candidates']
    if not isinstance(candidates, dict) or any(
            not isinstance(candidates.get(name, []), list)
            or any(not isinstance(row, dict) for row in candidates.get(name, []))
            for name in CANDIDATE_COLLECTIONS):
        raise ValueError('ADAPTIVE_REVIEW_CANDIDATES_UNMEASURABLE')
    indexed, errors = candidate_index(candidates)
    if errors:
        raise ValueError('ADAPTIVE_REVIEW_CANDIDATES_UNMEASURABLE')
    if not indexed:
        return len(units)
    if not decision_workflow_enabled(task):
        raise ValueError('ADAPTIVE_REVIEW_TRIAGE_UNMEASURABLE')
    ledger = packet['materiality_ledger']
    if (not isinstance(ledger, dict) or ledger.get('schema_version') != LEDGER_SCHEMA_VERSION
            or ledger.get('task_id') != task.get('task_id')
            or not isinstance(ledger.get('annotations'), list)
            or any(not isinstance(row, dict) for row in ledger['annotations'])):
        raise ValueError('ADAPTIVE_REVIEW_TRIAGE_UNMEASURABLE')
    necessary = {sid: necessary_scenario_right_types(task, scenario)
                 for sid, scenario in scenario_index(task).items()}
    records = triage_summary(task, candidates, ledger,
        evidence=packet['evidence'], supplement=packet.get('supplement'))['records']
    for row in records:
        if row['decision'] == 'selected' and row['right_type'] in necessary[row['scenario_id']]:
            units.add(unit_id(row))
    return len(units)


def measure(packet, images):
    from report_review_host import review_payload_view
    materials = (packet.get('retained_originals') or {}).get('materials')
    if not isinstance(materials, list):
        raise ValueError('ADAPTIVE_ORIGINAL_MANIFEST_REQUIRED')
    represented = {row['sha256'] for row in materials}
    def verify(value):
        if isinstance(value, dict):
            if value.get('path') and value.get('sha256') and value['sha256'] not in represented:
                raise ValueError('ADAPTIVE_ORIGINAL_MANIFEST_INCOMPLETE')
            for child in value.values():
                verify(child)
        elif isinstance(value, list):
            for child in value:
                verify(child)
    from review_material_policy import enabled as classified_materials, validate_inventory
    if classified_materials(packet['task']):
        validate_inventory(packet)
    else:
        verify(review_payload_view(packet))
    if any(row.get('kind') == 'unreadable_original' for row in materials):
        raise ValueError('ADAPTIVE_ORIGINAL_UNREADABLE')
    from common import sha256_bytes
    image_rows = [row for row in materials if row.get('kind') == 'actual_image']
    # a GIF / TIFF original is attached as its PNG (r5d4): the attachment carries its own hash beside the original's
    expected = {row.get('attachment'): row.get('attachment_sha256', row['sha256']) for row in image_rows}
    if len(expected) != len(image_rows) or expected != {name: sha256_bytes(data) for name, data in images.items()}:
        raise ValueError('ADAPTIVE_IMAGE_MANIFEST_MISMATCH')
    actual = {sha256_bytes(data) for data in images.values()}
    if actual != {row.get('attachment_sha256', row['sha256']) for row in materials if row.get('kind') == 'actual_image'}:
        raise ValueError('ADAPTIVE_IMAGE_MANIFEST_MISMATCH')
    texts = {row['sha256']: row.get('text', '') for row in materials}
    return {'review_text_chars': sum(len(v) for v in texts.values()),
            'review_images': len(actual),
            'review_units': required_review_unit_count(packet),
            'review_json_chars': len(json.dumps(review_payload_view(packet) if classified_materials(packet['task']) else packet,
                                                ensure_ascii=False, separators=(',', ':')))}


def prepare(frozen, task_dir, previous):
    from module_review import attach_originals
    from final_review import inputs, reuse_options
    if frozen['task'].get('final_review_execution_revision') != REVISION:
        return None
    limits = policy(frozen['task'])
    if limits is None:
        raise ValueError('ADAPTIVE_REVIEW_NEW_TASK_REQUIRED')
    # The unit count alone decides most multi-country tasks. Decide it before
    # decoding retained originals or serialising the whole packet; the module
    # route reads its own originals, and any unmeasurable input falls back to it.
    try:
        if required_review_unit_count(frozen) > limits['review_units']:
            return None
    except (ValueError, KeyError, TypeError, UnicodeError):
        return None
    packet = deepcopy(frozen)
    try:
        images = attach_originals(packet, task_dir)
    except ValueError as exc:
        # r5d24 (B0GLNPC6K8): the whole task's drawings (958 images, 104 MB - the screening pictures of 103 designs
        # nobody selected) exceed the integrated bundle; that is a size measure like the limits below, so the module
        # route, which carries each module's own originals, takes over instead of failing the final review
        if str(exc).startswith('FINAL_REVIEW_ORIGINAL_IMAGE_BUNDLE_TOO_LARGE'):
            return None
        raise
    try:
        counts = measure(packet, images)
        material = inputs(frozen['evidence'], frozen['candidates'], frozen['materiality_ledger'],
                          frozen['search_plan'], frozen['task'], frozen.get('supplement'))
        # Own prior receipt is part of the actual input, not an invisible allowance.
        for old in previous:
            if old:
                expanded = deepcopy(packet)
                expanded['review_reuse'] = reuse_options(old, material)
                expanded['previous_review'] = {'review_sha256': sha256_json(old), 'assessments': old['assessments']}
                counts['review_json_chars'] = max(counts['review_json_chars'], measure(expanded, images)['review_json_chars'])
        if any(counts[key] > limits[key] for key in counts):
            return None
    except (ValueError, KeyError, TypeError, UnicodeError):
        return None
    return packet, images, counts
