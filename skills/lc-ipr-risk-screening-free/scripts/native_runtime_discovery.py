"""Discover recipient-native Codex binaries and inspect CLI capability without login/model calls."""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import shutil
import sys

WRAPPERS = {'.cmd', '.bat', '.ps1', '.sh', '.js', '.py'}
MACH_HEADERS = {b'\xfe\xed\xfa\xce', b'\xce\xfa\xed\xfe', b'\xfe\xed\xfa\xcf',
                b'\xcf\xfa\xed\xfe', b'\xca\xfe\xba\xbe', b'\xbe\xba\xfe\xca',
                b'\xca\xfe\xba\xbf', b'\xbf\xba\xfe\xca'}
REQUIRED_OPTIONS = ('--ignore-user-config', '--ignore-rules', '--ephemeral', '--skip-git-repo-check',
                    '--json', '--sandbox', '--disable', '--enable', '--image', '--config', '--cd')


def validate_binary(candidate, platform=None):
    platform = platform or sys.platform
    path = Path(candidate).expanduser()
    if path.suffix.lower() in WRAPPERS:
        raise ValueError('REPORT_REVIEW_HOST_NATIVE_CLI_REQUIRED: a script wrapper is not accepted')
    try:
        if not path.is_file() or (platform != 'win32' and not os.access(path, os.X_OK)):
            raise OSError()
        with path.open('rb') as stream:
            header = stream.read(4)
            if platform == 'win32':
                stream.seek(0x3c)
                offset = int.from_bytes(stream.read(4), 'little')
                stream.seek(offset)
                native = (header[:2] == b'MZ' and stream.read(4) == b'PE\x00\x00'
                          and int.from_bytes(stream.read(2), 'little') == 0x8664)
            elif platform == 'darwin':
                native = header in MACH_HEADERS
            else:
                native = header == b'\x7fELF'
        if not native:
            raise OSError()
    except (OSError, ValueError, OverflowError):
        raise ValueError('REPORT_REVIEW_HOST_NATIVE_CLI_REQUIRED: missing or non-native executable') from None
    return path.resolve()


def _windows_package_roots(environment, probe):
    # Current-user package metadata only: no registry mutation, elevation or broad disk search.
    system = Path(environment.get('SystemRoot', r'C:\Windows'))
    powershell = system / 'System32/WindowsPowerShell/v1.0/powershell.exe'
    command = ("[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false); "
               "@(Get-AppxPackage | Where-Object { $_.Name -match '^OpenAI\\.(ChatGPT|Codex)' } | "
               "Select-Object -ExpandProperty InstallLocation) | ConvertTo-Json -Compress")
    rc, out, _ = probe([str(powershell), '-NoProfile', '-NonInteractive', '-Command', command])
    try:
        rows = json.loads(out) if rc == 0 and out.strip() else []
        rows = [rows] if isinstance(rows, str) else rows
        return [Path(row) for row in rows if isinstance(row, str) and row and Path(row).is_absolute()] if isinstance(rows, list) else []
    except ValueError:
        return []


def _package_binaries(root, names=('codex.exe',)):
    # Bounded scan of an identified application package; never traverse linked directories.
    count = 0
    for directory, dirs, files in os.walk(root, followlinks=False):
        parent = Path(directory)
        depth = len(parent.relative_to(root).parts)
        dirs[:] = sorted(d for d in dirs if depth < 8 and not (parent / d).is_symlink())
        count += len(dirs) + len(files)
        if count > 10000:
            return
        for name in sorted(files):
            if name.lower() in names:
                yield parent / name


def _npm_package_roots(command):
    """r9: the @openai/codex npm package (and its platform packages) behind a `codex` on PATH that is npm's JS
    launcher (macOS/Linux: <prefix>/lib/node_modules/@openai/codex/bin/codex.js); the native binary is inside."""
    try:
        real = Path(command).resolve()
    except OSError:
        return []
    for parent in real.parents:
        if parent.name == '@openai':
            return [parent / 'codex', *sorted(path for path in parent.glob('codex-*') if path.is_dir())]
    return []


def discover_binary(explicit=None, *, platform=None, environment=None, probe=None, home=None, capability=None):
    platform = platform or sys.platform
    environment = os.environ if environment is None else environment
    chosen = explicit or environment.get('LC_IPR_CODEX_BINARY')
    if chosen:
        # An invalid explicit override is an actionable error, never permission to fall back.
        path = validate_binary(chosen, platform)
        if capability is not None and capability(path).get('status') != 'cli_capable':
            raise ValueError('NATIVE_CODEX_REQUIRED_CAPABILITY_UNAVAILABLE')
        return path
    candidates = []
    if platform == 'darwin':
        for base in (Path('/Applications'), (home or Path.home()) / 'Applications'):
            for app in ('ChatGPT.app', 'Codex.app'):
                for relative in ('Contents/Resources/codex-cli/CodexCLI.app/Contents/MacOS/codex',
                                 'Contents/Resources/codex', 'Contents/Resources/codex-cli/codex',
                                 'Contents/Resources/codex-cli/bin/codex'):
                    candidates.append(base / app / relative)
    elif platform == 'win32':
        if probe is not None:
            roots = _windows_package_roots(environment, probe)
        else:
            roots = []
        local = environment.get('LOCALAPPDATA')
        if local:
            roots.extend(Path(local) / relative for relative in ('Programs/Codex', 'Programs/ChatGPT', 'Codex', 'ChatGPT'))
        # An npm global install exposes only a codex.cmd shim on PATH; the native
        # codex.exe lives in the package's vendor tree beside it. The shim itself is
        # never accepted (validate_binary rejects wrappers), only the PE inside the package.
        shim = shutil.which('codex.cmd', path=environment.get('PATH'))
        if shim:
            roots.append(Path(shim).parent / 'node_modules' / '@openai' / 'codex')
        appdata = environment.get('APPDATA')
        if appdata:
            roots.append(Path(appdata) / 'npm' / 'node_modules' / '@openai' / 'codex')
        for root in dict.fromkeys(roots):
            candidates.extend(_package_binaries(root))
    command = shutil.which('codex.exe' if platform == 'win32' else 'codex', path=environment.get('PATH'))
    if command:
        candidates.append(Path(command))
        if platform != 'win32':
            # r9: an npm-installed Codex on a Mac exposes only its JS launcher; look inside its package, as Windows does
            for root in _npm_package_roots(command):
                candidates.extend(_package_binaries(root, names=('codex',)))
    for candidate in dict.fromkeys(candidates):
        try:
            path = validate_binary(candidate, platform)
            if capability is not None and capability(path).get('status') != 'cli_capable':
                continue
            return path
        except ValueError:
            continue
    raise ValueError('REPORT_REVIEW_HOST_NATIVE_CLI_REQUIRED: pass --codex-binary or set LC_IPR_CODEX_BINARY')


def inspect_capability(binary, probe, disabled_features, backend):
    rc, version, _ = probe([str(binary), '--version'])
    # Return fixed diagnostics rather than arbitrary program/config output.
    match = re.fullmatch(r'codex(?:-cli)? [0-9][0-9A-Za-z.+_-]*\s*', version)
    result = {'status': 'unavailable', 'binary': str(binary), 'version': match[0].strip() if match else None,
              'isolation_backend': backend, 'login': 'not_run', 'model_execution': 'not_run',
              'model_availability': 'not_verified'}
    if rc != 0 or not match:
        return dict(result, reason='NATIVE_CODEX_VERSION_UNAVAILABLE')
    rc, help_text, _ = probe([str(binary), 'exec', '--help'])
    missing = [option for option in REQUIRED_OPTIONS if not re.search(re.escape(option) + r'(?:\s|[=<,])', help_text)]
    if rc != 0 or missing or 'read-only' not in help_text:
        return dict(result, reason='NATIVE_CODEX_REQUIRED_OPTIONS_UNAVAILABLE', missing_options=missing)
    rc, features, _ = probe([str(binary), 'features', 'list'])
    names = {line.split()[0] for line in features.splitlines() if line.split()}
    missing = sorted((set(disabled_features) | {'skip_host_skill_discovery'}) - names)
    if rc != 0 or missing:
        return dict(result, reason='NATIVE_CODEX_ISOLATION_FEATURES_UNAVAILABLE', missing_features=missing)
    return dict(result, status='cli_capable', reason=None)
