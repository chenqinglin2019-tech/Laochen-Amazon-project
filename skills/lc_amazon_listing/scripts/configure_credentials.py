#!/usr/bin/env python3
"""Receive a user-provided backend token through stdin, without echoing it."""
import json
import os
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def configure(root, payload):
    if not isinstance(payload, dict) or set(payload) != {'backend_token'}:
        raise ValueError('EXPECTED_BACKEND_TOKEN_ONLY')
    token = payload['backend_token']
    if not isinstance(token, str) or not token.strip() or token != token.strip() or any(ord(c) < 32 or ord(c) == 127 for c in token):
        raise ValueError('INVALID_TOKEN')
    path = root / 'config.json'
    if path.is_symlink():
        raise ValueError('CONFIG_SYMLINK_REFUSED')
    config = json.loads(path.read_text(encoding='utf-8-sig')) if path.exists() else {
        'backend_url': 'https://mcp.yixunkuajing.com', 'backend_token': ''}
    if not isinstance(config, dict):
        raise ValueError('INVALID_CONFIG')
    config['backend_token'] = token
    fd, temporary = tempfile.mkstemp(prefix='.credential-', dir=root)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8', newline='\n') as stream:
            json.dump(config, stream, ensure_ascii=False, indent=2)
            stream.write('\n'); stream.flush(); os.fsync(stream.fileno())
        os.replace(temporary, path)
        if os.name == 'posix':
            path.chmod(0o600)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return {'ok': True, 'updated_file': 'config.json'}


def main():
    try:
        result = configure(ROOT, json.load(sys.stdin))
    except (ValueError, OSError, UnicodeError):
        print('{"ok":false,"error":"CREDENTIAL_CONFIGURATION_FAILED"}')
        return 2
    print(json.dumps(result)); return 0


if __name__ == '__main__':
    raise SystemExit(main())
