#!/usr/bin/env python3
"""Standard-library runtime preflight (V8): 64-bit Python >= 3.11 with Pillow and NumPy.

Never imports production/auth code or Pillow itself. An existing compatible Python is
always preferred; installation is a separate, explicitly authorized operation that
creates a private venv with pinned wheels. Authorization here records permission to
install dependencies, NOT account authentication or a claim about the host's Codex
permission settings.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
# Compatible ranges are accepted as found; `install` pins the tested versions.
REQUIREMENTS = {"python_min": [3, 11],
                "pillow": {"install": "12.3.0", "min": "11.0.0", "below": "13"},
                "numpy": {"install": "2.3.5", "min": "1.26.0", "below": "3"}}
PACKAGES = ("pillow", "numpy")
AUTHORIZED = {"full-access", "user-confirmed"}
# -E ignores PYTHONPATH/PYTHONHOME, -P keeps the current directory off sys.path (no
# planted module shadowing); user site-packages stay visible like a normal run.
PROBE_FLAGS = ("-E", "-P", "-B")
PYTHON_PROBE = """import json,sys,struct
try:
 import PIL
 pillow=PIL.__version__
except ImportError:
 pillow=None
try:
 import numpy
 numpy_version=numpy.__version__
except ImportError:
 numpy_version=None
print(json.dumps({'version':list(sys.version_info[:3]),'bits':struct.calcsize('P')*8,'pillow':pillow,'numpy':numpy_version}))
"""
# Real behaviour, not presence: the studio modules import, a main image is cut out,
# composited and verified as exact 255 on the decoded file, and XMP disclosure survives.
VERIFY_SMOKE = r"""import json, sys, tempfile
from pathlib import Path
sys.path.insert(0, sys.argv[1])
import numpy
from PIL import Image, ImageDraw
import studio_catalog, studio_export, studio_main, studio_plan, studio_project, studio_prompt  # noqa: F401
checks = []
scene = Image.new("RGB", (600, 600), (248, 248, 248))
ImageDraw.Draw(scene).rounded_rectangle((180, 120, 420, 480), 20, fill=(30, 60, 140))
foreground, matte, _ = studio_main.cutout(scene)
result, placed, _ = studio_main.compose(foreground, matte, (1000, 1000))
with tempfile.TemporaryDirectory() as temp:
    report = studio_main.export(result, placed, Path(temp) / "main.jpg")
    if not report["verify"]["ok"]:
        raise SystemExit("main image white check failed: " + json.dumps(report["verify"]))
    checks.append("main_white_" + report["format"])
    studio_export.export_jpeg(result, Path(temp) / "secondary.jpg", people=True)
    checks.append("xmp_disclosure")
print(json.dumps({"passed": True, "checks": checks}))
"""
VERIFIED_TTL_SECONDS = 7 * 24 * 3600
# Runtime-facing sources whose change must force a real (uncached) verification.
VERIFIED_SOURCES = ("scripts/runtime_bootstrap.py", "scripts/studio_main.py", "scripts/studio_export.py")
OVERRIDE_ENV = ("LC_STUDIO_PYTHON",)


class BootstrapError(RuntimeError):
    pass


def _json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _sha(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _unique(values):
    return list(dict.fromkeys(str(value) for value in values if value))


def _windows():
    return platform.system() == "Windows"


def _version(text):
    numbers = re.findall(r"\d+", str(text or ""))[:3]
    return tuple(int(number) for number in numbers) + (0,) * (3 - len(numbers)) if numbers else None


def _compatible(package, version):
    spec, parsed = REQUIREMENTS[package], _version(version)
    return parsed is not None and _version(spec["min"]) <= parsed < _version(spec["below"])


def _host_info():
    system, machine = platform.system(), platform.machine().lower()
    version = platform.mac_ver()[0] if system == "Darwin" else platform.version()
    warnings = []
    if system == "Windows" and machine not in {"amd64", "x86_64"}:
        warnings.append("Only Windows x64 is in this skill's platform scope; Windows ARM/32-bit is not covered by the unchanged auth binaries")
    return {"system": system, "machine": machine, "version": version, "warnings": warnings,
            "validation": "Local verify is required; platform mapping tests are not target-machine tests"}


def _run(argv, *, env=None, timeout=20):
    """Bound output; never print inherited environment or package-manager config."""
    try:
        result = subprocess.run([str(arg) for arg in argv], env=env, text=True,
                                encoding="utf-8", errors="replace", capture_output=True, timeout=timeout, check=False)
    except (OSError, subprocess.SubprocessError) as exc:
        raise BootstrapError(f"{Path(str(argv[0])).name}: {type(exc).__name__}: {exc}") from exc
    if result.returncode:
        message = (result.stderr or result.stdout).strip()[-2400:]
        # Proxy/package server URLs may contain user credentials. They are not
        # needed to diagnose a missing wheel or an inaccessible download.
        message = re.sub(r"(https?://)[^\s/@]+:[^\s/@]+@", r"\1[redacted]@", message)
        raise BootstrapError(f"{Path(str(argv[0])).name} exited {result.returncode}: {message}")
    return result.stdout.strip()


class RuntimeBootstrap:
    def __init__(self, root=ROOT, cache_root=None):
        self.root = Path(root).resolve()
        digest = hashlib.sha256(json.dumps(REQUIREMENTS, sort_keys=True).encode()).hexdigest()[:16]
        override = os.environ.get("LC_AMAZON_STUDIO_CACHE", "").strip()
        default_cache = (Path(override).expanduser() / "runtime" if override else
                         Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData/Local") / "lc-amazon-image-studio/runtime"
                         if _windows() else Path.home() / ".cache/lc-amazon-image-studio/runtime")
        self.cache_root = Path(cache_root) if cache_root else default_cache
        self.cache = self.cache_root / digest
        self.selection_path = self.cache / "selection.json"
        self.bundled = Path.home() / ".cache/codex-runtimes/codex-primary-runtime/dependencies"

    @property
    def fallback_cache(self):
        """Where stamps go when the cache cannot be written (e.g. a host sandbox)."""
        user = re.sub(r"[^A-Za-z0-9_.-]", "_", os.environ.get("USER") or os.environ.get("USERNAME") or "user")
        return Path(tempfile.gettempdir()).resolve() / f"lc-amazon-image-studio-{user}" / "runtime" / self.cache.name

    def _selection(self):
        for path in (self.selection_path, self.fallback_cache / "selection.json"):
            try:
                value = _json(path)
                if isinstance(value, dict) and value:
                    return value
            except (OSError, ValueError):
                continue
        return {}

    def _candidates(self):
        selected = self._selection()
        python_name = "Scripts/python.exe" if _windows() else "bin/python"
        # Private venvs from any earlier lock (V7 installs pinned the same wheels) are probed too.
        return _unique([*(os.environ.get(name) for name in OVERRIDE_ENV), selected.get("python"),
                        sys.executable, shutil.which("python3"), shutil.which("python"),
                        self.bundled / "python/bin/python3", self.bundled / "python/python.exe",
                        *self.cache.glob(f"python-*/{python_name}"), *sorted(self.cache_root.glob(f"*/python-*/{python_name}")),
                        *self._launcher_pythons()])

    @staticmethod
    def _launcher_pythons():
        """Windows launcher listing only: never ask it to download a Python."""
        launcher = shutil.which("py") if _windows() else None
        if not launcher:
            return []
        try:
            listed = _run([launcher, "-0p"])
        except BootstrapError:
            return []
        result = []
        for line in listed.splitlines():
            match = re.match(r"^\s*-\S+\s+\*?\s*(.+?\.exe)\s*$", line, re.IGNORECASE)
            if match:
                result.append(match.group(1).strip().strip('"'))
        return result

    def inspect(self):
        selected, usable, usable_probe, versions = None, None, {}, {}
        for candidate in self._candidates():
            if not Path(candidate).is_file():
                continue
            try:
                probe = json.loads(_run([candidate, *PROBE_FLAGS, "-c", PYTHON_PROBE]))
                if tuple(probe["version"]) < tuple(REQUIREMENTS["python_min"]) or probe.get("bits") != 64:
                    continue
            except (BootstrapError, ValueError, KeyError, TypeError):
                continue
            if usable is None:
                usable, usable_probe = candidate, probe
            if all(_compatible(name, probe.get(name)) for name in PACKAGES):
                selected = candidate
                versions = {"python": ".".join(map(str, probe["version"])), "pillow": probe["pillow"], "numpy": probe["numpy"]}
                break
        missing = []
        if not selected:
            if not usable:
                missing.append({"name": "python", "version": ">=3.11 64-bit", "installable": False,
                                "reason": "64-bit Python >=3.11 unavailable; ask the user to install a supported Python first (see SKILL.md §0)"})
            else:
                for name in PACKAGES:
                    found = usable_probe.get(name)
                    if not _compatible(name, found):
                        spec = REQUIREMENTS[name]
                        missing.append({"name": name, "version": spec["install"], "installable": True, "found": found,
                                        "reason": f"{name} {spec['min']}..<{spec['below']} required (found {found or 'none'})"})
        python = selected or usable
        commands = {"cwd": str(self.root), "python": python, "env": {}}
        if python:
            commands["studio_argv_prefix"] = [python, "-X", "utf8", str(self.root / "scripts/studio.py")]
        return {"ready": not missing, "verified": False, "verification_required": True,
                "next_action": "verify" if not missing else "Ask the user to confirm installing the listed dependencies",
                "missing": missing, "installable": [item["name"] for item in missing if item["installable"]],
                "needs_confirmation": bool(missing), "selected": {"python": selected}, "versions": versions,
                "commands": commands, "usable_python": usable, "cache_dir": str(self.cache), "platform": _host_info()}

    def _prepare_cache(self):
        # Install only inside a dedicated cache subtree; never follow pre-created
        # symlink components into a system interpreter or the skill itself.
        for path in [self.cache, *self.cache.parents]:
            if path.is_symlink():
                raise BootstrapError(f"Cache path must not contain symlinks: {path}")
        self.cache.mkdir(parents=True, exist_ok=True)
        target = self.cache / "pip-cache"
        if target.is_symlink() or (target.exists() and not target.is_dir()):
            raise BootstrapError(f"Installer cache target must be a real directory: {target}")

    def _install_python(self, python):
        target = Path(tempfile.mkdtemp(prefix="python-", dir=self.cache))
        _run([python, "-I", "-m", "venv", target], timeout=180)
        binary = target / ("Scripts/python.exe" if _windows() else "bin/python")
        env = os.environ.copy()
        # --isolated alone still reads pip GLOBAL/SITE configuration. The
        # documented null config disables those sources as well.
        env["PIP_CONFIG_FILE"] = os.devnull
        _run([binary, "-I", "-m", "pip", "--isolated", "install", "--disable-pip-version-check", "--no-input",
              "--only-binary=:all:", "--cache-dir", self.cache / "pip-cache", "--index-url", "https://pypi.org/simple",
              f"Pillow=={REQUIREMENTS['pillow']['install']}", f"numpy=={REQUIREMENTS['numpy']['install']}"], env=env, timeout=600)
        return str(binary)

    def verify(self, report):
        if not report.get("ready"):
            raise BootstrapError("Required dependencies are missing; cannot verify runtime")
        env = os.environ.copy()
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        env.pop("PYTHONPATH", None)
        output = _run([report["selected"]["python"], *PROBE_FLAGS, "-c", VERIFY_SMOKE, str(self.root / "scripts")],
                      env=env, timeout=120)
        try:
            result = json.loads(output.splitlines()[-1])
        except (ValueError, IndexError) as exc:
            raise BootstrapError("Runtime smoke test printed no result") from exc
        if not result.get("passed"):
            raise BootstrapError("Runtime smoke test failed")
        return result

    @property
    def verified_path(self):
        return self.cache / "verified.json"

    def _identity(self, selected):
        """Cheap identity of the verified runtime: file stats, sources and platform."""
        def stat(value):
            try:
                info = Path(value).stat()
                return [str(value), info.st_size, info.st_mtime_ns]
            except (OSError, TypeError):
                return [str(value), None, None]
        sources = {name: _sha(self.root / name) if (self.root / name).is_file() else None for name in VERIFIED_SOURCES}
        return {"lock": self.cache.name, "python": stat(selected.get("python")), "sources": sources,
                "platform": [platform.system(), platform.release(), platform.machine(), sys.version.split()[0]],
                "env": {name: os.environ.get(name) for name in OVERRIDE_ENV}}

    def _publish(self, report):
        """Publish runtime paths (never account data) plus a time-limited verified stamp.

        Returns the directory written. When the cache is not writable (host sandbox),
        the stamp goes to a per-user temp directory instead; a stamp that cannot be
        written anywhere only costs a re-verification next time.
        """
        stamp = {"schema": 2, "verified_at": time.time(), "selected": report["selected"],
                 "versions": report.get("versions", {}), "commands": report["commands"],
                 "identity": self._identity(report["selected"])}
        errors = []
        for directory in (self.cache, self.fallback_cache):
            try:
                if directory == self.cache:
                    self._prepare_cache()
                else:
                    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
                for name, payload in (("selection.json", report["selected"]), ("verified.json", stamp)):
                    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", prefix=Path(name).stem + "-", suffix=".json",
                                                     dir=directory, delete=False) as stream:
                        json.dump(payload, stream, ensure_ascii=False, indent=2)
                        temporary = Path(stream.name)
                    os.replace(temporary, directory / name)
                return directory
            except (OSError, BootstrapError) as exc:
                errors.append(f"{directory}: {exc}")
        raise OSError("; ".join(errors))

    def cached_report(self):
        """Return a still-valid verification without re-running the smoke test, else None (read-only)."""
        stamp = None
        for path in (self.verified_path, self.fallback_cache / "verified.json"):
            try:
                candidate = _json(path)
                if (candidate.get("schema") == 2 and time.time() - float(candidate["verified_at"]) <= VERIFIED_TTL_SECONDS
                        and candidate["identity"] == self._identity(candidate["selected"])):
                    stamp = candidate
                    break
            except (OSError, ValueError, KeyError, TypeError):
                continue
        if stamp is None:
            return None
        return {"ready": True, "verified": True, "verification_required": False, "cached_verification": True,
                "verified_at": stamp["verified_at"], "missing": [], "installable": [], "needs_confirmation": False,
                "selected": stamp["selected"], "versions": stamp["versions"], "commands": stamp["commands"],
                "cache_dir": str(self.cache), "next_action": "Use commands.python for subsequent studio commands"}

    def invalidate(self):
        for path in (self.verified_path, self.fallback_cache / "verified.json"):
            try:
                path.unlink()
            except OSError:
                pass

    def verified_report(self, fresh=False):
        if not fresh:
            cached = self.cached_report()
            if cached:
                return cached
        report = self.inspect()
        if not report["ready"]:
            self.invalidate()
            return report
        try:
            report["verification"] = self.verify(report)
            report.update({"verified": True, "verification_required": False,
                           "next_action": "Use commands.python for subsequent studio commands"})
            try:
                report["stamp_dir"] = str(self._publish(report))
            except OSError as exc:
                # Verification itself passed; only the cache stamp could not be stored.
                report.update(stamp_written=False, warning=f"Verification passed but its cache stamp could not be written ({exc}); the next verify repeats the check.")
        except (BootstrapError, OSError, ValueError) as exc:
            self.invalidate()
            report.update({"ready": False, "verified": False, "needs_confirmation": True, "error": str(exc),
                           "next_action": "Review failed runtime verification with the user; do not begin production or install system packages automatically"})
        return report

    def install(self, authorization="unknown"):
        report = self.inspect()
        if authorization not in AUTHORIZED:
            report.update({"needs_confirmation": bool(report["missing"]), "installation_performed": False,
                           "installation_attempted": False,
                           "next_action": "Ask the user to confirm installing the listed dependencies; do not infer full access"
                           if report["missing"] else "verify"})
            return report
        if any(not item["installable"] for item in report["missing"]):
            report.update({"needs_confirmation": True, "installation_performed": False, "installation_attempted": False,
                           "next_action": "Ask the user to install a supported 64-bit Python >=3.11 first (SKILL.md §0)"})
            return report
        installed, attempted = [], False
        try:
            if report["missing"]:
                self._prepare_cache()
                attempted = True
                self._install_python(report["usable_python"])
                installed = [item["name"] for item in report["missing"]]
            report = self.inspect()
            if not report["ready"]:
                raise BootstrapError("Installed runtime does not satisfy the requirements")
            report["verification"] = self.verify(report)
            # Only publish paths after the real smoke test succeeds.
            self._publish(report)
            report.update({"needs_confirmation": False, "verified": True, "verification_required": False,
                           "next_action": "Use commands.python for subsequent studio commands",
                           "installation_performed": bool(installed), "installation_attempted": attempted, "installed": installed})
        except (BootstrapError, OSError, ValueError) as exc:
            report = self.inspect()
            report.update({"ready": False, "verified": False, "needs_confirmation": True, "installation_performed": bool(installed),
                           "installation_attempted": attempted, "partial_cache": str(self.cache) if attempted else None,
                           "installed": installed, "error": str(exc),
                           "next_action": "Stop dependency setup. Review the error with the user; do not use sudo, install OS packages, change pinned versions or bypass verification"})
        return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("inspect", "verify", "install"))
    parser.add_argument("--authorization", choices=("unknown", "restricted", "full-access", "user-confirmed"), default="unknown",
                        help="Explicit installer permission supplied by Agent/user; never account authentication")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--fresh", action="store_true", help="verify: ignore a still-valid cached verification")
    args = parser.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    try:
        bootstrap = RuntimeBootstrap()
        report = (bootstrap.inspect() if args.command == "inspect" else
                  bootstrap.verified_report(fresh=args.fresh) if args.command == "verify" else bootstrap.install(args.authorization))
    except (BootstrapError, OSError, ValueError) as exc:
        report = {"ready": False, "missing": [], "installable": [], "needs_confirmation": True, "error": str(exc)}
    if args.json:
        print(json.dumps(report, ensure_ascii=False, separators=(",", ":")))
    else:
        print("Runtime ready" if report["ready"] else "Runtime not ready")
        for item in report.get("missing", []):
            print(f"- {item['name']}: {item['reason']}")
        if report.get("error"):
            print(report["error"])
        print(json.dumps(report.get("commands", {}), ensure_ascii=False, indent=2))
    return 0 if report["ready"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
