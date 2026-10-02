#!/usr/bin/env python3
"""Save user-supplied credentials from stdin; never echo credential values."""
import json
import os
from pathlib import Path
import re
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
API_FIELDS = {'EPO_OPS_CONSUMER_KEY', 'EPO_OPS_CONSUMER_SECRET', 'EUIPO_CLIENT_ID',
              'EUIPO_CLIENT_SECRET', 'JPO_API_USERNAME', 'JPO_API_PASSWORD',
              'INPI_USERNAME', 'INPI_PASSWORD', 'SERPER_API_KEY', 'SIGNA_API_KEY',
              'SERPAPI_API_KEY', 'RAPIDAPI_KEY'}


def _read(path, default):
    if path.is_symlink():
        raise ValueError('CREDENTIAL_SYMLINK_REFUSED')
    return path.read_text(encoding='utf-8-sig') if path.exists() else default


def _write(path, text):
    if path.is_symlink():
        raise ValueError('CREDENTIAL_SYMLINK_REFUSED')
    fd, temporary = tempfile.mkstemp(prefix='.credential-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8', newline='\n') as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        if os.name == 'posix':
            path.chmod(0o600)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def configure(root, payload):
    if not isinstance(payload, dict) or not payload or set(payload) - {'backend_token', 'api_keys'}:
        raise ValueError('INVALID_CREDENTIAL_INPUT')
    api = payload.get('api_keys', {})
    if not isinstance(api, dict) or not set(api) <= API_FIELDS:
        raise ValueError('UNKNOWN_API_KEY_NAME')
    if api and not (root / '.env').exists():
        raise ValueError('API_KEYS_UNSUPPORTED_BY_THIS_SKILL')
    values = list(api.values()) + ([payload['backend_token']] if 'backend_token' in payload else [])
    if not values or any(not isinstance(v, str) or not v.strip() or v != v.strip()
                         or any(c in v for c in '\r\n\x00') for v in values):
        raise ValueError('INVALID_CREDENTIAL_VALUE')
    writes = []
    if 'backend_token' in payload:
        path = root / 'config.json'
        config = json.loads(_read(path, '{"backend_url":"https://mcp.yixunkuajing.com","backend_token":""}'))
        if not isinstance(config, dict):
            raise ValueError('INVALID_CONFIG')
        config['backend_token'] = payload['backend_token']
        writes.append((path, json.dumps(config, ensure_ascii=False, indent=2) + '\n'))
    if api:
        path = root / '.env'
        lines = _read(path, '').splitlines()
        seen = set()
        for i, line in enumerate(lines):
            if not line.strip() or line.lstrip().startswith('#'):
                continue
            match = re.fullmatch(r'\s*([A-Z][A-Z0-9_]*)\s*=.*', line)
            if not match or match[1] in seen:
                raise ValueError('INVALID_ENV')
            key = match[1]; seen.add(key)
            if key in api:
                lines[i] = key + '="' + api[key] + '"'
        for key in sorted(set(api) - seen):
            lines.append(key + '="' + api[key] + '"')
        writes.append((path, '\n'.join(lines) + '\n'))
    # Git cannot retain 0600. Secure the existing .env when receiving a token
    # even when the user has not supplied a third-party key yet.
    env_path = root / '.env'
    if env_path.is_symlink():
        raise ValueError('CREDENTIAL_SYMLINK_REFUSED')
    if env_path.exists() and not env_path.is_file():
        raise ValueError('INVALID_ENV')
    for path, content in writes:
        _write(path, content)
    if os.name == 'posix' and env_path.exists():
        env_path.chmod(0o600)
    return {'ok': True, 'updated_files': [p.name for p, _ in writes],
            'api_key_names': sorted(api)}


def main():
    try:
        result = configure(ROOT, json.load(sys.stdin))
    except (ValueError, OSError, UnicodeError):
        print('{"ok":false,"error":"CREDENTIAL_CONFIGURATION_FAILED"}')
        return 2
    print(json.dumps(result))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
