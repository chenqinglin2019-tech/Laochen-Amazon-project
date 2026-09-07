"""Turn reviewed, external design units into per-job executable briefs.

This module never interprets screenshots as product evidence, copies their
pixels, calls a model, or overrides an explicitly authored local layout.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RECIPES = {'photo_overlay', 'header_footer', 'photo_sidebar', 'scene_grid', 'detail_callouts', 'steps'}


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()


def validate_units(document):
    errors, ids = [], set()
    if not isinstance(document, dict) or document.get('schema_version') != 1 or document.get('asset_policy') != 'external_regions_only':
        return ['Invalid design unit document']
    if not isinstance(document.get('units'), list):
        return ['Design units must be a list']
    for unit in document['units']:
        if not isinstance(unit, dict):
            errors.append('Design unit must be an object'); continue
        identifier = unit.get('id')
        if not isinstance(identifier, str) or not identifier or identifier in ids:
            errors.append('Missing or duplicate design unit ID')
        ids.add(identifier)
        region = unit.get('unit_region_norm')
        if (not isinstance(region, list) or len(region) != 4 or
                any(isinstance(v, bool) or not isinstance(v, (int,float)) or not math.isfinite(v) or not 0 <= v <= 1 for v in region) or
                region[2] <= 0 or region[3] <= 0 or region[0]+region[2] > 1.000001 or region[1]+region[3] > 1.000001):
            errors.append(f'{identifier}: invalid finished-design region')
        path, sha = unit.get('external_path'), unit.get('sha256')
        if not isinstance(path, str) or not Path(path).is_absolute():
            errors.append(f'{identifier}: source must be absolute')
        if not isinstance(sha, str) or len(sha) != 64 or any(c not in '0123456789abcdef' for c in sha):
            errors.append(f'{identifier}: invalid source SHA256')
        if unit.get('recipe') not in RECIPES or unit.get('product_evidence') is not False or unit.get('reviewed') is not True:
            errors.append(f'{identifier}: unreviewed unit, unknown recipe, or product-evidence confusion')
        if not isinstance(unit.get('generation'), dict) or not isinstance(unit.get('layout'), dict):
            errors.append(f'{identifier}: generation/layout observations required')
    return errors


def _recipe(tags):
    words = ' '.join(tags).lower()
    if 'step' in words: return 'steps'
    if any(t in words for t in ('detail', 'callout')): return 'detail_callouts'
    if 'grid' in words: return 'scene_grid'
    if any(t in words for t in ('strip', 'footer', 'header')): return 'header_footer'
    if any(t in words for t in ('split', 'sidebar')): return 'photo_sidebar'
    return 'photo_overlay'


def _finished_design_tags(tags):
    """Discard relationships between original/finished halves of sample boards.

    These are catalog metadata, not a recipe for the final product poster.
    Genuine split layouts remain supported through ``split``/``sidebar`` cues.
    """
    return [tag for tag in tags if not (
        ('_left_' in tag and tag.endswith('_right')) or
        tag.startswith(('before_after', 'original_vs_', 'comparison_board')))]


def _generic_unit(manifest, base, job):
    from lc_style_reference import prepare_selection, DEFAULT_INDEX
    context = {'product': manifest.get('product_truth', {}).get('product', ''),
               'category': manifest.get('category') or manifest.get('product_truth', {}).get('category', ''),
               'intents': job.get('selling_job', '')}
    if not isinstance(context['product'], str) or not context['product'].strip():
        return None  # Empty init scaffold is gated by product evidence, not a selector exception.
    # Existing selection remains a cache, not a second source of product facts.
    target = base / manifest.get('style_reference_selection_path', 'style_reference_selection.json')
    selection = prepare_selection(context, target)
    if selection.get('selection_status') != 'selected': return None
    index = json.loads(DEFAULT_INDEX.read_text(encoding='utf-8'))
    candidates = [selection.get('primary')] + selection.get('auxiliaries', [])
    records = {r['id']: r for r in index['references']}
    desired = _recipe([job.get('selling_job','')])
    ranked = sorted((records[x['id']] for x in candidates if x and x['id'] in records),
                    key=lambda r: _recipe(_finished_design_tags(r.get('composition', []))) != desired)
    if not ranked: return None
    sample = ranked[0]
    tags = _finished_design_tags(sample.get('composition', []))
    recipe = _recipe(tags)
    return {'id': sample['id'], 'external_path':sample['external_path'], 'sha256':sample['sha256'],
            'recipe':recipe, 'generation': {'composition_cues':tags, 'lighting':sample.get('lighting',[])},
            'layout':{'recipe':recipe, 'headline_tone':'serif' if 'editorial_hero' in sample.get('image_intent',[]) else 'sans',
                      'structure_cues':tags}, 'unit_region_norm':sample.get('design_region_norm'),
            'reference_kind':'generic_design_cues', 'product_evidence':False}


def prepare_design_briefs(manifest, base, selected):
    """Route new projects to text templates without reading legacy image indices."""
    from lc_template_workflow import uses_templates, prepare_template_briefs, validate_template_inputs
    from lc_style_reference import ReferenceIndexError
    errors = validate_template_inputs(manifest)
    if errors:
        raise ReferenceIndexError('; '.join(errors))
    selected = set(selected)
    templated = {j['id'] for j in manifest.get('jobs', [])
                 if j['id'] in selected and uses_templates(manifest, j)}
    result = {'changed': [], 'cached': [], 'needs_input': []}
    if templated:
        result = prepare_template_briefs(manifest, base, templated)
    legacy = selected - templated
    if legacy:
        old = _prepare_external_design_briefs(manifest, base, legacy)
        for key in result:
            result[key].extend(old[key])
    return result


def _prepare_external_design_briefs(manifest, base, selected):
    """Compile opted-in jobs. Explicit units > confirmed brief > generic library.

Documented project inputs: design_reference_units_path (optional),
design_reference_ids (optional list), job.design_reference_id (optional), and
job.design_overrides={generation:{...},layout:{...}}. Legacy jobs are untouched.
"""
    from lc_style_reference import ReferenceIndexError
    base, selected = Path(base), set(selected)
    path = Path(manifest.get('design_reference_units_path', ROOT/'assets/layouts/design_reference_units.json'))
    if not path.is_absolute(): path = base/path
    atlas = json.loads(path.read_text(encoding='utf-8')) if path.is_file() else {'schema_version':1,'asset_policy':'external_regions_only','units':[]}
    errors = validate_units(atlas)
    if errors: raise ReferenceIndexError('; '.join(errors))
    units = {u['id']:u for u in atlas['units']}
    changed, cached, missing = [], [], []
    verified = {}
    for job in manifest.get('jobs', []):
        if job['id'] not in selected or not (job.get('text_mode') or job.get('layout',{}).get('version') == 3): continue
        if job.get('kind') == 'main' or job.get('text_mode') == 'none': continue
        explicit = job.get('design_reference_id')
        project_ids = manifest.get('design_reference_ids', [])
        if not isinstance(project_ids, list) or any(not isinstance(v,str) for v in project_ids):
            raise ReferenceIndexError('design_reference_ids must be a list of IDs')
        if not explicit and not project_ids and job.get('design_brief') and not job.get('design_resolution'):
            # Authored brief has higher priority than automatic category matching.
            continue
        if explicit:
            unit = units.get(explicit)
        elif project_ids:
            wanted = job.get('layout',{}).get('recipe') or _recipe([job.get('selling_job','')])
            candidates = [units[v] for v in project_ids if v in units]
            unit = next((u for u in candidates if u['recipe'] == wanted), candidates[0] if candidates else None)
        else:
            unit = _generic_unit(manifest, base, job)
        if unit:
            source = Path(unit['external_path'])
            key = (str(source), unit['sha256'])
            if key not in verified:
                verified[key] = source.is_file() and hashlib.sha256(source.read_bytes()).hexdigest() == unit['sha256']
            if not verified[key]: unit = None
        if unit is None:
            job['design_resolution'] = {
                'status':'needs_input', 'required': bool(explicit or project_ids),
                'reason':'Missing or changed design reference; do not claim reference matching.'}
            missing.append(job['id']); continue
        override = job.get('design_overrides', {})
        if not isinstance(override, dict) or any(k not in {'generation','layout'} for k in override):
            raise ReferenceIndexError('design_overrides accepts generation/layout objects only')
        if any(not isinstance(v,dict) for v in override.values()): raise ReferenceIndexError('design override must be an object')
        brief = {'version':1,'reference_ids':[unit['id']],
                 'generation':{**copy.deepcopy(unit['generation']), **copy.deepcopy(override.get('generation',{}))},
                 'layout':{**copy.deepcopy(unit['layout']), **copy.deepcopy(override.get('layout',{}))}}
        signature = _digest({'unit':unit,'overrides':override})
        resolution = {'status':'selected','input_hash':signature,'brief_hash':_digest(brief),
                      'source': 'user_reference' if explicit or project_ids else 'generic_library',
                      'reference': {k:unit.get(k) for k in ('id','external_path','sha256','unit_region_norm','reference_kind')}}
        if job.get('design_brief') == brief and job.get('design_resolution') == resolution:
            cached.append(job['id']); continue
        job['design_brief'], job['design_resolution'] = brief, resolution
        changed.append(job['id'])
    return {'changed':changed,'cached':cached,'needs_input':missing}
