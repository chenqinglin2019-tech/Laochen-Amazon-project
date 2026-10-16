"""Bind new final-review execution runtimes without rewriting historical audits."""
from pathlib import Path
import json
import os
import re

from common import atomic_write_json, load_json, sha256_file
from review_isolation import MACOS, TOOL_FREE, select_backend

FILENAME = 'native-runtime.json'
SCHEMA = 'IPR-NATIVE-RUNTIME-BINDING/1.0'


def _path(value):
    if not isinstance(value, str) or not value or not Path(value).is_absolute():
        raise ValueError('FINAL_REVIEW_RETAINED_RUNTIME_INVALID')
    return str(Path(value).resolve())


def retained_runtime(output_dir):
    """Infer only identities actually retained. An old missing hash stays unknown."""
    output_dir = Path(output_dir)
    binding_path = output_dir / FILENAME
    records = []
    if binding_path.is_file():
        value = load_json(binding_path)
        if (not isinstance(value, dict) or set(value) != {'schema', 'binary', 'binary_sha256', 'backend'}
                or value.get('schema') != SCHEMA or value.get('backend') not in {MACOS, TOOL_FREE}
                or not isinstance(value.get('binary_sha256'), str)
                or not re.fullmatch('[0-9a-f]{64}', value['binary_sha256'])):
            raise ValueError('FINAL_REVIEW_RETAINED_RUNTIME_INVALID')
        records.append({'binary': _path(value.get('binary')), 'binary_sha256': value['binary_sha256'],
                        'backend': value['backend']})
    for chain in ('1', '2'):
        parent = output_dir / chain
        if not parent.is_dir():
            continue
        for directory in sorted(parent.iterdir()):
            if not directory.is_dir() or '.attempt-' in directory.name:
                continue
            audit_path = directory / 'audit.json'
            audit = load_json(audit_path) if audit_path.is_file() else None
            if audit is not None and not isinstance(audit, dict):
                raise ValueError('FINAL_REVIEW_RETAINED_RUNTIME_INVALID')
            profiles = [directory / name for name in ('sandbox.sb', 'isolation-policy.json')
                        if (directory / name).is_file()]
            if len(profiles) > 1:
                raise ValueError('FINAL_REVIEW_RETAINED_ISOLATION_BACKEND_CHANGED')
            if not profiles:
                continue
            profile = profiles[0]
            if audit and sha256_file(profile) != audit.get('profile_sha256'):
                raise ValueError('FINAL_REVIEW_RETAINED_AUDIT_CHANGED')
            if profile.name == 'isolation-policy.json':
                value = load_json(profile)
                fingerprint = value.get('codex_binary_sha256')
                if not isinstance(fingerprint, str) or not re.fullmatch('[0-9a-f]{64}', fingerprint):
                    raise ValueError('FINAL_REVIEW_RETAINED_RUNTIME_INVALID')
                records.append({'binary': _path(value.get('codex_binary')),
                                'binary_sha256': fingerprint, 'backend': TOOL_FREE})
            else:
                # This exact JSON-quoted rule is emitted by sandbox_profile.
                literals = re.findall(r'^\(allow process-exec \(literal ("(?:[^"\\]|\\.)*")\)\)$',
                                      profile.read_text(encoding='utf-8'), flags=re.M)
                if len(literals) != 1:
                    raise ValueError('FINAL_REVIEW_RETAINED_RUNTIME_INVALID')
                records.append({'binary': _path(json.loads(literals[0])),
                                'binary_sha256': None, 'backend': MACOS})
            if audit and audit.get('native_command') is not None:
                command = audit['native_command']
                backend = records[-1]['backend']
                position = 3 if backend == MACOS else 0
                if (not isinstance(command, list) or len(command) <= position + 1
                        or command[position + 1] != 'exec'
                        or _path(command[position]) != records[-1]['binary']):
                    raise ValueError('FINAL_REVIEW_RETAINED_RUNTIME_CONFLICT')
    if not records:
        return None
    paths = {row['binary'] for row in records}
    backends = {row['backend'] for row in records}
    hashes = {row['binary_sha256'] for row in records if row['binary_sha256'] is not None}
    if len(paths) != 1 or len(backends) != 1 or len(hashes) > 1:
        raise ValueError('FINAL_REVIEW_RETAINED_RUNTIME_CONFLICT')
    return {'binary': paths.pop(), 'backend': backends.pop(),
            'binary_sha256': hashes.pop() if hashes else None}


def resume_runtime(output_dir, explicit=None, requested='auto'):
    """No discovery/capability calls: successful old logs need no running CLI."""
    recorded = retained_runtime(output_dir)
    backend = recorded['backend'] if recorded else select_backend(requested)
    if requested != 'auto' and requested != backend:
        raise ValueError('FINAL_REVIEW_RETAINED_ISOLATION_BACKEND_CHANGED')
    chosen = explicit or os.environ.get('LC_IPR_CODEX_BINARY')
    if chosen and recorded and str(Path(chosen).expanduser().resolve()) != recorded['binary']:
        raise ValueError('FINAL_REVIEW_RETAINED_RUNTIME_CHANGED')
    return (Path(recorded['binary']) if recorded else None), backend


def ensure_fresh_runtime(output_dir, binary, backend, task, *, resume_existing=False):
    """Called only before a fresh native slot; never upgrade or re-sign old slots."""
    output_dir = Path(output_dir)
    recorded = retained_runtime(output_dir)
    if recorded:
        if backend != recorded['backend']:
            raise ValueError('FINAL_REVIEW_RETAINED_ISOLATION_BACKEND_CHANGED')
        if binary is None or str(Path(binary).resolve()) != recorded['binary']:
            raise ValueError('FINAL_REVIEW_RETAINED_RUNTIME_CHANGED')
        path = Path(recorded['binary'])
        if not path.is_file():
            raise ValueError('FINAL_REVIEW_RETAINED_RUNTIME_UNAVAILABLE')
        if recorded['binary_sha256'] is not None and sha256_file(path) != recorded['binary_sha256']:
            raise ValueError('FINAL_REVIEW_RETAINED_RUNTIME_CHANGED')
        return
    if resume_existing:
        raise ValueError('FINAL_REVIEW_RETAINED_RUNTIME_UNCONFIRMED')
    from execution_efficiency import revised
    if not revised(task):
        return
    if binary is None or not Path(binary).is_file():
        raise ValueError('REPORT_REVIEW_HOST_NATIVE_CLI_REQUIRED')
    atomic_write_json(output_dir / FILENAME, {'schema': SCHEMA, 'binary': str(Path(binary).resolve()),
        'binary_sha256': sha256_file(Path(binary)), 'backend': backend})
