"""10C file contracts and material disclosure, without claiming actual delivery."""
from __future__ import annotations
from common import sha256_json

REVISION = "report-package-stage-c-v1"
EXPORTS = {"markdown": "report.md", "csv": "report-findings.csv"}
CORE = ("report.html", "report-data.json", "report-manifest.json")
OPERATOR_APPENDICES = ("operator-appendix.html", "technical-audit.html")
STAGE_CARRIERS = {"reply", "html", "markdown", "csv"}


def enabled(task):
    revision = task.get("report_package_revision")
    if revision is None:
        return False
    if revision != REVISION:
        raise ValueError("REPORT_PACKAGE_REVISION_INVALID")
    return True


def choices(value, allowed, error):
    if not isinstance(value, list) or any(not isinstance(item, str) or item not in allowed for item in value) or len(value) != len(set(value)):
        raise ValueError(error)
    return sorted(value)


def core_files(data):
    return [*CORE, *(OPERATOR_APPENDICES if data.get('presentation_policy_revision') == 'operator-report-v1' else ())]


def contract(task, data):
    exports = choices(task.get("report_exports", []), EXPORTS, "REPORT_EXPORTS_INVALID")
    materials, gaps = [], []
    seen = set()
    index_rows = data.get('evidence_index', [])
    for position, row in enumerate(index_rows + [row for row in data.get('linked_files', []) if row.get('evidence_id')]):
        identifier = row.get("evidence_id")
        key = (identifier, row.get('path'))
        if key in seen:
            continue
        seen.add(key)
        if row.get("path") and row.get("sha256"):
            materials.append({"evidence_id": identifier, "status": "retained_required",
                **{key: row[key] for key in ("path", "sha256", "bytes") if key in row}})
        elif position < len(index_rows) and ((isinstance(row.get('payload'), dict) and row['payload']) or
                (isinstance(row.get('fact'), str) and row['fact'].strip())):
            materials.append({'evidence_id': identifier, 'status': 'retained_inline_evidence',
                'path': 'report-data.json', 'json_pointer': '/evidence_index/' + str(position),
                'record_sha256': sha256_json(row), 'original_file': 'not_claimed'})
        else:
            gaps.append({"evidence_id": identifier, "status": "not_obtained",
                "source_url": row.get("source_url"), "reason": row.get("source_note") or "未绑定可交付留存材料；URL／编号不是原文"})
    return {"revision": REVISION, "type": "report", "required_artifacts": [*core_files(data), *(EXPORTS[item] for item in exports)],
        "exports": exports, "materials": materials, "business_material_gaps": gaps,
        "actual_delivery": "not_verified"}


def material_files(data):
    files = {}
    for row in data['visual_evidence'] + data['evidence_index'] + data['linked_files']:
        if not row.get('path'):
            continue
        record = {key: row[key] for key in ('path', 'sha256', 'bytes') if key in row}
        previous = files.setdefault(row['path'], {**record, 'evidence_ids': []})
        if any(previous.get(key) != value for key, value in record.items()):
            raise ValueError('REPORT_MATERIAL_FILE_CONFLICT')
        if row.get('evidence_id') and row['evidence_id'] not in previous['evidence_ids']:
            previous['evidence_ids'].append(row['evidence_id'])
    for record in files.values():
        record['evidence_ids'].sort()
    return [files[path] for path in sorted(files)]


def report_files(data):
    package = data.get("report_package_stage_c")
    if package is None:
        return [*CORE, *EXPORTS.values()]
    exports = choices(package.get("exports"), EXPORTS, "REPORT_EXPORTS_INVALID")
    expected = [*core_files(data), *(EXPORTS[item] for item in exports)]
    if package.get("revision") != REVISION or package.get("required_artifacts") != expected:
        raise ValueError("REPORT_PACKAGE_CONTRACT_INVALID")
    return expected


def stage_carriers(task):
    if not enabled(task):
        return ["html", "markdown"]
    carriers = choices(task.get("stage_carriers", ["reply"]), STAGE_CARRIERS, "STAGE_CARRIERS_INVALID")
    if not carriers:
        raise ValueError("STAGE_CARRIER_REQUIRED")
    return carriers
