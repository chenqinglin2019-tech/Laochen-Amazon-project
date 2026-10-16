#!/usr/bin/env python3
"""Save the optional SerpApi backup key from stdin into the skill's .env; never echo credential values.

r8 (owner request 2026-10-16): a second SerpApi account. When the main key's account cannot cover a new task and the
backup's can, the task uses the backup (search_guard.check_capacity). The main key stays SERPAPI_API_KEY and is still
filled by configure_credentials.py; this script only adds or replaces SERPAPI_API_KEY_BACKUP, with the same atomic
0600 write. Input: {"SERPAPI_API_KEY_BACKUP": "..."} on stdin.
"""
import json
import re
import sys
from pathlib import Path

from configure_credentials import _read, _write

ROOT = Path(__file__).resolve().parents[1]
FIELD = 'SERPAPI_API_KEY_BACKUP'


def configure(root, payload):
    if not isinstance(payload, dict) or set(payload) != {FIELD}:
        raise ValueError('INVALID_CREDENTIAL_INPUT')
    value = payload[FIELD]
    if (not isinstance(value, str) or not value.strip() or value != value.strip()
            or any(c in value for c in '\r\n\x00"')):
        raise ValueError('INVALID_CREDENTIAL_VALUE')
    path = root / '.env'
    if not path.is_file():
        raise ValueError('API_KEYS_UNSUPPORTED_BY_THIS_SKILL')
    lines = _read(path, '').splitlines()
    for index, line in enumerate(lines):
        if re.fullmatch(r'\s*' + FIELD + r'\s*=.*', line):
            lines[index] = FIELD + '="' + value + '"'
            break
    else:
        lines.append(FIELD + '="' + value + '"')
    _write(path, '\n'.join(lines) + '\n')
    return {'ok': True, 'updated_files': ['.env'], 'api_key_names': [FIELD]}


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
