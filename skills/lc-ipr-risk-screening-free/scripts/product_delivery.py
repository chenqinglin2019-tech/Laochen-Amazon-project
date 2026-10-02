"""Versioned image and fact handoff for the product collection stage.

This contract is activated by a reviewed product-scope-v2 record. Historical
scope records retain their original image and fact behavior.
"""
from __future__ import annotations

from copy import deepcopy

from common import sha256_json
from product_entry import target_binding, public_image_url_valid

REVISION = "image-fact-v1"
FACT_NATURE = {"direct_observation", "page_claim", "user_statement", "analysis_inference"}
FACT_VERIFICATION = {"verified", "claim_only", "unverified", "conflict"}
IMAGE_VISIBILITY = {"sufficient", "limited", "not_visible", "unknown"}
VISUAL_RIGHTS = {"design", "unregistered_design", "trademark_figurative", "copyright", "trade_dress"}


def enabled(task):
    value = task.get("product_delivery_revision")
    if value is None:
        return False
    if value != REVISION:
        raise ValueError("PRODUCT_DELIVERY_REVISION_INVALID")
    return True


def _text(value):
    return isinstance(value, str) and bool(value.strip())


def image_identity(task):
    return sha256_json(target_binding(task))


def validate_image(task):
    selection = task.get("product", {}).get("query_image")
    if not isinstance(selection, dict) or selection.get("status") not in {"selected", "needs_clarification", "unavailable"}:
        raise ValueError("QUERY_IMAGE_SELECTION_REQUIRED")
    if not _text(selection.get("reason")) or selection.get("target_sha256") != image_identity(task):
        raise ValueError("QUERY_IMAGE_TARGET_OR_REASON_INVALID")
    images = task.get("images", [])
    if not isinstance(images, list):
        raise ValueError("QUERY_IMAGE_LIST_INVALID")
    mains = [image for image in images if image.get("role") == "main"]
    if selection["status"] == "selected":
        if len(mains) != 1 or mains[0].get("image_id") != selection.get("image_id") or mains[0].get("sha256") != selection.get("sha256"):
            raise ValueError("QUERY_IMAGE_MAIN_BINDING_INVALID")
        if selection.get("source_url", "") != mains[0].get("source_url", ""):
            raise ValueError("QUERY_IMAGE_SOURCE_CHANGED")
        if selection.get("source_kind") not in {"amazon_public_url", "other_public_url", "user_file"}:
            raise ValueError("QUERY_IMAGE_SOURCE_KIND_INVALID")
        return mains[0]
    if mains or not _text(selection.get("question")) and selection["status"] == "needs_clarification":
        raise ValueError("QUERY_IMAGE_UNRESOLVED_STATE_INVALID")
    return None


def validate_scope(task, data):
    if data.get("delivery_revision") != REVISION:
        raise ValueError("PRODUCT_DELIVERY_SCOPE_REVISION_REQUIRED")
    validate_image(task)
    product_id = task.get("product", {}).get("product_id")
    images = {image.get("image_id") for image in task.get("images", [])}
    for obj in data["objects"]:
        visual = obj.get("visual_evidence")
        if not isinstance(visual, dict) or visual.get("main_visibility") not in IMAGE_VISIBILITY:
            raise ValueError("OBJECT_MAIN_IMAGE_VISIBILITY_REQUIRED")
        refs = visual.get("image_ids")
        if not isinstance(refs, list) or any(ref not in images for ref in refs):
            raise ValueError("OBJECT_IMAGE_REFERENCE_INVALID")
        if (visual["main_visibility"] != "sufficient" and obj.get("scope_status") == "included"
                and set(obj.get("right_types", [])) & VISUAL_RIGHTS and not _text(visual.get("limitation_reason"))):
            raise ValueError("OBJECT_MAIN_IMAGE_LIMITATION_REQUIRED")
    for fact in data["facts"]:
        if (fact.get("nature") not in FACT_NATURE or fact.get("verification") not in FACT_VERIFICATION
                or not isinstance(fact.get("version"), int) or isinstance(fact.get("version"), bool)
                or fact["version"] < 1 or not isinstance(fact.get("applies_to"), dict)
                or fact["applies_to"].get("product_id") != product_id):
            raise ValueError("PRODUCT_FACT_DELIVERY_FIELDS_REQUIRED")
        if fact["nature"] in {"page_claim", "analysis_inference"} and fact["verification"] == "verified":
            raise ValueError("PRODUCT_CLAIM_CANNOT_BE_VERIFIED_FACT")
        if fact["status"] == "conflict" and fact["verification"] != "conflict":
            raise ValueError("PRODUCT_FACT_CONFLICT_MISMATCH")
        if fact["verification"] == "verified" and fact["status"] != "confirmed":
            raise ValueError("PRODUCT_FACT_VERIFICATION_MISMATCH")
    permissions = data.get("image_permissions", [])
    if not isinstance(permissions, list):
        raise ValueError("IMAGE_PERMISSIONS_INVALID")
    seen_permissions = set()
    for item in permissions:
        if (not isinstance(item, dict) or item.get("provider") != "serpapi_google_lens"
                or item.get("purpose") != "image_discovery" or item.get("status") not in {"allowed", "not_allowed", "unknown"}
                or not isinstance(item.get("source_refs"), list) or not item["source_refs"]
                or not _text(item.get("reason"))):
            raise ValueError("IMAGE_PERMISSION_BASIS_REQUIRED")
        key = (item["provider"], item["purpose"])
        if key in seen_permissions:
            raise ValueError("IMAGE_PERMISSION_DUPLICATE")
        seen_permissions.add(key)
    return data


def validate_fact_origins(data, evidence):
    retained = {row.get('evidence_id'): row for row in evidence.get('collections',{}).get('product',[])}
    retained.update({row.get('evidence_id'): row for row in evidence.get('collections',{}).get('scope_sources',[])})
    for fact in data.get('facts',[]):
        sources = [retained.get(ref,{}) for ref in fact.get('source_refs',[])]
        if fact.get('nature') == 'page_claim' and not any(
                source.get('source')=='amazon_browser' or source.get('kind')=='document' for source in sources):
            raise ValueError('PRODUCT_PAGE_CLAIM_SOURCE_REQUIRED')
        if fact.get('nature') == 'user_statement' and not any(
                source.get('source')=='user_materials' or source.get('kind')=='user_statement' for source in sources):
            raise ValueError('PRODUCT_USER_STATEMENT_SOURCE_REQUIRED')


def selected_public_image(task, provider="serpapi_google_lens", purpose="image_discovery"):
    """Return only a bound, permitted main URL. No local-file upload exists."""
    if not enabled(task):
        return next((image for image in task.get("images", [])
                     if str(image.get("source_url", "")).startswith("https://")), None)
    image = validate_image(task)
    if image is None or not public_image_url_valid(str(image.get("source_url", ""))):
        return None
    permissions = task.get("product_scope", {}).get("image_permissions", [])
    if not any(row.get("provider") == provider and row.get("purpose") == purpose and row.get("status") == "allowed"
               for row in permissions):
        return None
    return image


def query_row_binding(task, image):
    if not enabled(task):
        return {}
    return {"query_image_id": image["image_id"], "query_image_sha256": image["sha256"],
            "query_target_sha256": image_identity(task)}


def validate_image_query(task, provider, row):
    """Called immediately before actual image submission for v2 tasks."""
    if not enabled(task) or provider != "serpapi_google_lens":
        return None
    image = selected_public_image(task)
    if (image is None or row.get("image_url") != image.get("source_url")
            or row.get("query_image_id") != image.get("image_id")
            or row.get("query_image_sha256") != image.get("sha256")
            or row.get("query_target_sha256") != image_identity(task)):
        return "QUERY_IMAGE_INPUT_OR_PERMISSION_UNAVAILABLE"
    return None


def fact_for_path(task, path):
    if not enabled(task):
        return None
    return next((fact for fact in task.get("product_scope", {}).get("facts", []) if fact.get("source_path") == path), None)


def fact_refs_for_row(task, row):
    if not enabled(task):
        return []
    refs = []
    for path in row.get("derived_from", []):
        fact = fact_for_path(task, path)
        if fact and fact["fact_id"] not in {item["fact_id"] for item in refs}:
            refs.append({"fact_id": fact["fact_id"], "version": fact["version"],
                         "nature": fact["nature"], "verification": fact["verification"]})
    return refs


def bind_fact_versions(task, row):
    if enabled(task):
        row["product_delivery_revision"] = REVISION
        row["product_fact_refs"] = fact_refs_for_row(task, row)
    return row


def validate_fact_query(task, row):
    if not enabled(task):
        return None
    if row.get("product_delivery_revision") != REVISION or row.get("product_fact_refs") != fact_refs_for_row(task, row):
        return "PRODUCT_FACT_VERSION_REVIEW_REQUIRED"
    return None


def project(task):
    """Four-part handoff; derived from one reviewed scope, never hand-edited."""
    if not enabled(task):
        raise ValueError('PRODUCT_DELIVERY_NOT_ENABLED')
    scope = task['product_scope']
    selection = task['product']['query_image']
    directions = scope['directions']
    def affected(*, fact_id=None, object_id=None):
        return [row['direction_id'] for row in directions
                if fact_id in row['fact_ids'] or object_id in row['object_ids']]
    can_continue = [row['direction_id'] for row in directions if
                    all(next(f for f in scope['facts'] if f['fact_id'] == fid)['status'] == 'confirmed'
                        for fid in row['fact_ids']) and
                    all(next(o for o in scope['objects'] if o['object_id'] == oid)['scope_status'] == 'included'
                        for oid in row['object_ids'])]
    gaps = [{'kind':'fact','fact_id':fact['fact_id'],'question':fact.get('question',''),
             'reason':fact['reason'], 'affected_direction_ids':affected(fact_id=fact['fact_id'])}
            for fact in scope['facts'] if fact['status']!='confirmed']
    from product_feedback import pending as pending_feedback, unavailable, structure_policy_enabled, structural_fact
    if structure_policy_enabled(task):
        for gap in gaps:
            fact = next(row for row in scope['facts'] if row['fact_id'] == gap['fact_id'])
            if structural_fact(fact): gap.update(question='', availability='unavailable', judgment='无法判定')
    gaps.extend({'kind':'downstream_fact_feedback','request_id':request['request_id'],
                 'fact_id':request['fact_id'],'candidate_id':request.get('candidate_id') or None,
                 'purpose':request['purpose'],'minimum_information':request['minimum_information'],
                 'question':request['question'],'reason':request['reason'],
                 'affected_direction_ids':[request['direction_id']]}
                for request in pending_feedback(task))
    gaps.extend({'kind':'downstream_fact_feedback', 'request_id':request['request_id'],
                 'fact_id':request['fact_id'],'candidate_id':request.get('candidate_id') or None,
                 'purpose':request['purpose'],'minimum_information':request['minimum_information'],
                 'question':'','reason':request['reason'],'availability':'unavailable','judgment':'无法判定',
                 'affected_direction_ids':[request['direction_id']]} for request in unavailable(task))
    gaps.extend({'kind':'object','object_id':obj['object_id'],'question':obj.get('question',''),
                 'reason':obj['reason'], 'affected_direction_ids':affected(object_id=obj['object_id'])}
                for obj in scope['objects'] if obj['scope_status']=='pending')
    gaps.extend({'kind':'image_visibility','object_id':obj['object_id'],
                 'reason':obj['visual_evidence'].get('limitation_reason',''),
                 'affected_direction_ids':affected(object_id=obj['object_id'])} for obj in scope['objects']
                if obj['scope_status']=='included' and obj['visual_evidence']['main_visibility']!='sufficient')
    if selection['status']!='selected':
        gaps.append({'kind':'query_image','reason':selection['reason'],'question':selection.get('question',''),
                     'affected_action':'image_discovery'})
    elif not selected_public_image(task):
        gaps.append({'kind':'image_route','reason':'No supported public main URL or provider-and-purpose permission.',
                     'question':'Confirm a public main image URL and its provider-specific permission.',
                     'provider':'serpapi_google_lens','affected_action':'image_discovery'})
    return {'revision':REVISION,
        'product_range':{'product_id':task['product']['product_id'],'target_sha256':image_identity(task),
                         'scope_sha256':scope['scope_sha256'],'role':task['product'].get('input_role'),
                         'role_source':task['product'].get('input_role_source'),
                         'jurisdictions':task.get('target_jurisdictions',[]),
                         'scenarios':task.get('execution_scenario_ids',[])},
        'facts_and_clues':deepcopy(scope['facts']), 'objects_and_marks':deepcopy(scope['objects']),
        'gaps_and_conflicts':gaps,
        'can_continue_direction_ids':can_continue,
        'query_image':deepcopy(selection),'image_permissions':deepcopy(scope.get('image_permissions',[]))}
