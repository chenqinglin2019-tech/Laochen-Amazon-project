#!/usr/bin/env python3
"""Standard-library runtime preflight; never imports production/auth or Pillow.

Installation is a separate, explicitly authorized operation. Authorization here
records permission to install dependencies, NOT account authentication or a claim
about the host's Codex permission settings.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
import platform
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.parse
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]
# Official LTS checked 2026-09-10. Existing valid Node is always preferred;
# the layout lock itself remains Node >= 20 and is not changed by bootstrap.
NODE_FALLBACK_VERSION = "24.21.0"
NODE_ORIGIN = "https://nodejs.org"
# Additional production dependency, matching the frozen bundled-runtime replay.
# Kept outside layout-runtime.json so adding bootstrap does not invalidate QA.
BOOTSTRAP_DEPENDENCIES = {"numpy_version": "2.3.5", "python_min": [3, 11],
                          "browser_installer": {"package": "playwright-core", "version": "1.61.0",
                                                "chromium_version": "149.0.7827.55", "chromium_revision": "1228"}}
AUTHORIZED = {"full-access", "user-confirmed"}
BROWSER_PATTERNS = (
    "chromium*/chrome-headless-shell*/chrome-headless-shell",
    "chromium*/chrome-headless-shell*/headless_shell.exe",
    "chromium*/chrome-headless-shell*/chrome-headless-shell.exe",
    "chromium*/chrome-*/chrome", "chromium*/chrome-*/chrome.exe",
    "chromium*/chrome-*/Chromium.app/Contents/MacOS/Chromium",
    "chromium*/chrome-*/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing",
)
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
BROWSER_SMOKE = """const {chromium}=require(process.argv[1]);
(async()=>{let b;try{b=await chromium.launch({executablePath:process.argv[2],headless:true,args:['--disable-gpu']});
const p=await b.newPage();await p.setContent('<p>Runtime preflight</p>');
await p.screenshot({type:'png'});console.log(JSON.stringify({passed:true}));
}finally{if(b)await b.close();}})().catch(e=>{console.error(e.message);process.exitCode=1;});"""


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


def _node_archive_spec(system=None, machine=None):
    system = system or platform.system()
    machine = (machine or platform.machine()).lower()
    archive_os = {"Darwin": "darwin", "Linux": "linux", "Windows": "win"}.get(system)
    arch = {"arm64": "arm64", "aarch64": "arm64", "x86_64": "x64", "amd64": "x64"}.get(machine)
    if not archive_os or not arch:
        raise BootstrapError(f"No approved Node archive for {system}/{machine}; ask user before external setup")
    folder = f"node-v{NODE_FALLBACK_VERSION}-{archive_os}-{arch}"
    return {"folder": folder, "filename": folder + (".zip" if system == "Windows" else ".tar.gz"),
            "binary": "node.exe" if system == "Windows" else "bin/node"}


def _host_info():
    system, machine = platform.system(), platform.machine().lower()
    version = platform.mac_ver()[0] if system == "Darwin" else platform.version()
    warnings = []
    supported = None
    if system == "Darwin":
        major = int(version.split(".")[0]) if version.split(".")[0].isdigit() else 0
        supported = major >= 14
        if not supported:
            warnings.append("Pinned Playwright documents macOS >=14; this OS requires target-machine verification and is not an officially supported production claim")
    elif system == "Windows":
        build = version.split(".")[2] if len(version.split(".")) > 2 else "0"
        win11 = platform.release() == "11" or (build.isdigit() and int(build) >= 22000)
        supported = win11
        if not win11:
            warnings.append("Windows 10 compatibility is not Playwright 1.62.1 official support; unchanged pinned runtime must pass verify on this machine")
        if machine not in {"amd64", "x86_64"}:
            warnings.append("Only Windows x64 is in this skill's platform scope; Windows ARM/32-bit is not covered by the unchanged auth binaries")
            supported = False
    return {"system": system, "machine": machine, "version": version,
            "playwright_official_os_support": supported, "warnings": warnings,
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
        # needed to diagnose a missing wheel, inaccessible download or OS library.
        message = re.sub(r"(https?://)[^\s/@]+:[^\s/@]+@", r"\1[redacted]@", message)
        raise BootstrapError(f"{Path(str(argv[0])).name} exited {result.returncode}: {message}")
    return result.stdout.strip()


def _official_download(url, target):
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme != "https" or parsed.netloc != "nodejs.org" or not parsed.path.startswith("/dist/"):
        raise BootstrapError("Node downloads must use https://nodejs.org/dist/")
    class OfficialRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, request, response, code, message, headers, newurl):
            redirected = urllib.parse.urlsplit(newurl)
            if redirected.scheme != "https" or redirected.netloc != "nodejs.org":
                raise BootstrapError("Node download redirected outside the official HTTPS origin")
            return super().redirect_request(request, response, code, message, headers, newurl)

    with urllib.request.build_opener(OfficialRedirect()).open(url, timeout=60) as response:
        redirected = urllib.parse.urlsplit(response.geturl())
        if redirected.scheme != "https" or redirected.netloc != "nodejs.org":
            raise BootstrapError("Node download redirected outside the official HTTPS origin")
        with Path(target).open("wb") as stream:
            shutil.copyfileobj(response, stream)


def _extract_node(archive, destination, expected_root):
    """No extractall: archive links/devices and path escapes are never followed."""
    def target_for(name):
        if "\\" in name:
            raise BootstrapError("Unsafe Node archive path")
        parts = PurePosixPath(name).parts
        if not parts or parts[0] != expected_root or ".." in parts or PurePosixPath(name).is_absolute():
            raise BootstrapError("Unsafe Node archive path")
        target = Path(destination).joinpath(*parts)
        if not target.resolve().is_relative_to(Path(destination).resolve()):
            raise BootstrapError("Unsafe Node archive target")
        return target

    if str(archive).endswith(".zip"):
        with zipfile.ZipFile(archive) as bundle:
            for item in bundle.infolist():
                target = target_for(item.filename)
                mode = item.external_attr >> 16
                if mode & 0o170000 == 0o120000:
                    raise BootstrapError("Unexpected symlink in Node zip")
                if item.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                else:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with bundle.open(item) as source, target.open("xb") as output:
                        shutil.copyfileobj(source, output)
    else:
        with tarfile.open(archive, "r:gz") as bundle:
            for item in bundle:
                target = target_for(item.name)
                if item.isdir():
                    target.mkdir(parents=True, exist_ok=True)
                elif item.isfile():
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with bundle.extractfile(item) as source, target.open("xb") as output:
                        shutil.copyfileobj(source, output)
                    target.chmod(item.mode & 0o777)
                elif item.issym():
                    # Invoke the bundled npm CLI with Node directly; no link is
                    # required and no archive-provided symlink is materialized.
                    continue
                else:
                    raise BootstrapError("Unexpected non-file in Node archive")


class RuntimeBootstrap:
    def __init__(self, root=ROOT, cache_root=None):
        self.root = Path(root).resolve()
        self.lock = _json(self.root / "assets/layout-runtime.json")
        for key in ("pillow_version", "playwright_version", "chromium_version"):
            if not re.fullmatch(r"\d+(?:\.\d+){2,3}", str(self.lock.get(key, ""))):
                raise BootstrapError(f"Invalid runtime lock: {key}")
        if not isinstance(self.lock.get("node_min_major"), int) or self.lock["node_min_major"] < 20:
            raise BootstrapError("Invalid Node minimum in runtime lock")
        digest = hashlib.sha256(json.dumps([self.lock, BOOTSTRAP_DEPENDENCIES], sort_keys=True).encode()).hexdigest()[:16]
        default_cache = (Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData/Local") / "lc-amazon-image-studio/runtime"
                         if _windows() else Path.home() / ".cache/lc-amazon-image-studio/runtime")
        self.cache_root = Path(cache_root) if cache_root else default_cache
        self.cache = self.cache_root / digest
        self.selection_path = self.cache / "selection.json"
        self.bundled = Path.home() / ".cache/codex-runtimes/codex-primary-runtime/dependencies"

    def _selection(self):
        try:
            value = _json(self.selection_path)
            return value if isinstance(value, dict) else {}
        except (OSError, ValueError):
            return {}

    def _candidates(self):
        selected = self._selection()
        python_name = "Scripts/python.exe" if _windows() else "bin/python"
        pythons = _unique([os.environ.get("LC_LAYOUT_PYTHON"), selected.get("python"),
                          sys.executable, shutil.which("python3"), shutil.which("python"),
                          self.bundled / "python/bin/python3", self.bundled / "python/python.exe",
                          *self.cache.glob(f"python-*/{python_name}"), *self._launcher_pythons()])
        nodes = _unique([os.environ.get("LC_LAYOUT_NODE"), selected.get("node"), shutil.which("node"),
                        self.bundled / "node/bin/node", self.bundled / "node/node.exe",
                        *self.cache.glob("node-*/node-*/bin/node"), *self.cache.glob("node-*/node-*/node.exe")])
        modules = _unique([os.environ.get("LC_LAYOUT_NODE_MODULES"), selected.get("modules"),
                          self.root / "node_modules", self.bundled / "node/node_modules",
                          *self.cache.glob("npm-*/node_modules")])
        browser_roots = _unique([os.environ.get("PLAYWRIGHT_BROWSERS_PATH"), self.cache / "browsers",
                                 Path.home() / "Library/Caches/ms-playwright", Path.home() / ".cache/ms-playwright",
                                 Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData/Local") / "ms-playwright" if _windows() else None])
        browsers = [os.environ.get("LC_LAYOUT_CHROMIUM"), selected.get("chromium")]
        for base in browser_roots:
            for pattern in BROWSER_PATTERNS:
                browsers.extend(sorted(Path(base).glob(pattern), reverse=True))
        return {"python": pythons, "node": nodes, "modules": modules, "chromium": _unique(browsers)}

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

    def _font_errors(self):
        errors = []
        try:
            manifest = _json(self.root / "assets/fonts/manifest.json")
            for item in manifest["fonts"]:
                path = self.root / "assets/fonts" / item["file"]
                if not path.is_file() or _sha(path) != item["sha256"]:
                    errors.append(f"{item['file']}: restore original bundled file (SHA-256 {item['sha256']})")
            for name in manifest["license_files"]:
                if not (self.root / "assets/fonts" / name).is_file():
                    errors.append(f"{name}: restore original bundled license")
        except (OSError, ValueError, KeyError, TypeError) as exc:
            errors.append(f"Bundled font manifest unavailable: {exc}")
        return errors

    def inspect(self):
        candidates = self._candidates()
        selected = {"python": None, "node": None, "modules": None, "chromium": None}
        usable_python = None
        best_python_probe = {}
        best_python_score = -1
        versions = {}
        for candidate in candidates["python"]:
            if not Path(candidate).is_file():
                continue
            try:
                probe = json.loads(_run([candidate, "-I", "-B", "-c", PYTHON_PROBE]))
                if tuple(probe["version"]) < tuple(BOOTSTRAP_DEPENDENCIES["python_min"]) or probe.get("bits") != 64:
                    continue
                score = int(probe.get("pillow") == self.lock["pillow_version"]) + int(probe.get("numpy") == BOOTSTRAP_DEPENDENCIES["numpy_version"])
                if score > best_python_score:
                    usable_python, best_python_probe, best_python_score = candidate, probe, score
                if score == 2:
                    selected["python"] = candidate
                    versions["python"] = ".".join(map(str, probe["version"]))
                    versions["pillow"] = probe["pillow"]
                    versions["numpy"] = probe["numpy"]
                    break
            except (BootstrapError, ValueError, KeyError, TypeError):
                continue
        for candidate in candidates["node"]:
            if not Path(candidate).is_file():
                continue
            try:
                version = _run([candidate, "--version"])
                if int(version.lstrip("v").split(".")[0]) >= self.lock["node_min_major"]:
                    selected["node"] = candidate
                    versions["node"] = version
                    break
            except (BootstrapError, ValueError):
                continue
        for candidate in candidates["modules"]:
            try:
                if _json(Path(candidate) / "playwright/package.json")["version"] == self.lock["playwright_version"]:
                    selected["modules"] = candidate
                    versions["playwright"] = self.lock["playwright_version"]
                    break
            except (OSError, ValueError, KeyError, TypeError):
                continue
        for candidate in candidates["chromium"]:
            if not Path(candidate).is_file():
                continue
            try:
                version = _run([candidate, "--version"])
                if re.search(r"(?<![\d.])" + re.escape(self.lock["chromium_version"]) + r"(?![\d.])", version):
                    selected["chromium"] = candidate
                    versions["chromium"] = self.lock["chromium_version"]
                    break
            except BootstrapError:
                continue
        missing = []
        if not selected["python"]:
            if not usable_python:
                missing.append({"name": "python", "version": ">=3.11 64-bit", "installable": False,
                                "reason": "64-bit Python >=3.11 unavailable (required by pinned NumPy); ask user to install a supported Python first"})
            else:
                for package, version in (("pillow", self.lock["pillow_version"]), ("numpy", BOOTSTRAP_DEPENDENCIES["numpy_version"])):
                    if best_python_probe.get(package) != version:
                        missing.append({"name": package, "version": version, "installable": True, "reason": f"Pinned {package} unavailable"})
        for key, name, version in (("node", "node", f">={self.lock['node_min_major']}"), ("modules", "playwright", self.lock["playwright_version"]),
                                   ("chromium", "chromium", self.lock["chromium_version"])):
            if not selected[key]:
                missing.append({"name": name, "version": version, "installable": True, "reason": "No matching local runtime found"})
        font_errors = self._font_errors()
        if font_errors:
            missing.append({"name": "bundled_fonts", "installable": False, "reason": "Restore original skill resources; never substitute fonts", "details": font_errors})
        env = {name: selected[key] for name, key in (("LC_LAYOUT_NODE", "node"), ("LC_LAYOUT_NODE_MODULES", "modules"), ("LC_LAYOUT_CHROMIUM", "chromium")) if selected[key]}
        commands = {"cwd": str(self.root), "python": selected["python"] or usable_python, "env": env}
        if commands["python"]:
            commands["doctor_argv"] = [commands["python"], "-X", "utf8", "-B", str(self.root / "scripts/lc_layout.py"), "--doctor"]
            commands["pipeline_argv_prefix"] = [commands["python"], "-X", "utf8", str(self.root / "scripts/lc_image_pipeline.py")]
        return {"ready": not missing, "verified": False, "verification_required": True,
                "next_action": "verify" if not missing else "Review missing dependencies and installation authorization",
                "missing": missing, "installable": [item["name"] for item in missing if item["installable"]],
                "needs_confirmation": bool(missing), "selected": selected, "versions": versions, "commands": commands,
                "usable_python": usable_python, "cache_dir": str(self.cache), "platform": _host_info()}

    def _prepare_cache(self):
        # Install only inside a dedicated cache subtree; never follow pre-created
        # symlink components into a system interpreter or the skill itself.
        for path in [self.cache, *self.cache.parents]:
            if path.is_symlink():
                raise BootstrapError(f"Cache path must not contain symlinks: {path}")
        self.cache.mkdir(parents=True, exist_ok=True)
        for name in ("browsers", "npm-cache", "pip-cache"):
            target = self.cache / name
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
              f"Pillow=={self.lock['pillow_version']}", f"numpy=={BOOTSTRAP_DEPENDENCIES['numpy_version']}"], env=env, timeout=600)
        return str(binary)

    def _install_node(self):
        spec = _node_archive_spec()
        target = Path(tempfile.mkdtemp(prefix="node-", dir=self.cache))
        folder, filename = spec["folder"], spec["filename"]
        origin = f"{NODE_ORIGIN}/dist/v{NODE_FALLBACK_VERSION}"
        checksums, archive = target / "SHASUMS256.txt", target / filename
        _official_download(f"{origin}/SHASUMS256.txt", checksums)
        matches = [line.split()[0] for line in checksums.read_text(encoding="utf-8").splitlines()
                   if len(line.split()) == 2 and line.split()[1] == filename]
        if len(matches) != 1 or not re.fullmatch(r"[0-9a-f]{64}", matches[0]):
            raise BootstrapError("Official SHA-256 manifest does not uniquely identify the Node archive")
        _official_download(f"{origin}/{filename}", archive)
        if _sha(archive) != matches[0]:
            raise BootstrapError("Node archive SHA-256 mismatch; archive was not extracted or executed")
        _extract_node(archive, target, folder)
        return str(target / folder / spec["binary"])

    @staticmethod
    def _npm_cli(node):
        binary = Path(node).resolve()
        candidates = [binary.parent / "node_modules/npm/bin/npm-cli.js", binary.parent.parent / "lib/node_modules/npm/bin/npm-cli.js",
                      binary.parent.parent / "node_modules/npm/bin/npm-cli.js"]
        npm = shutil.which("npm")
        if npm:
            candidates.append(Path(npm).resolve())
        return next((str(path) for path in candidates if path.is_file() and path.suffix == ".js"), None)

    def _install_playwright(self, node):
        return self._install_npm_package(node, "playwright", self.lock["playwright_version"], "npm-")

    def _install_npm_package(self, node, package, version, prefix):
        npm_cli = self._npm_cli(node)
        if not npm_cli:
            # A usable custom Node can be standalone; install the official Node
            # bundle privately only to obtain its npm, never replace that Node.
            npm_cli = self._npm_cli(self._install_node())
        if not npm_cli:
            raise BootstrapError("npm CLI unavailable in official Node bundle")
        target = Path(tempfile.mkdtemp(prefix=prefix, dir=self.cache))
        env = self._install_env(node)
        # npm rejects loading the same config source twice; two /dev/null paths
        # are not valid substitutes for its user AND global configuration.
        for role in ("user", "global"):
            config = target / f"{role}.npmrc"
            config.write_text("", encoding="utf-8")
            env[f"npm_config_{role}config"] = str(config)
        _run([node, npm_cli, "install", "--prefix", target, "--ignore-scripts", "--no-audit", "--no-fund", "--save-exact",
              "--registry=https://registry.npmjs.org", f"{package}@{version}"], env=env, timeout=600)
        return str(target / "node_modules")

    def _install_env(self, node):
        env = os.environ.copy()
        # Do not consume private registry tokens/configuration for public deps.
        for key in list(env):
            if key.lower().startswith(("npm_config_", "npm_token", "node_auth_token")) or key.upper() in {"NODE_OPTIONS", "NODE_PATH", "NODE_TLS_REJECT_UNAUTHORIZED"} or (key.upper().startswith("PLAYWRIGHT_") and (key.upper().endswith("DOWNLOAD_HOST") or key.upper() == "PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD")):
                env.pop(key)
        old_path = next((value for key, value in env.items() if key.upper() == "PATH"), "")
        for key in list(env):
            if key.upper() == "PATH":
                env.pop(key)
        node_dir = str(PureWindowsPath(node).parent) if _windows() else str(Path(node).parent)
        env.update({"PATH": node_dir + (";" if _windows() else os.pathsep) + old_path,
                    "npm_config_cache": str(self.cache / "npm-cache"), "PLAYWRIGHT_BROWSERS_PATH": str(self.cache / "browsers")})
        return env

    def _install_browser(self, node, modules):
        expected = BOOTSTRAP_DEPENDENCIES["browser_installer"]
        package = "playwright"
        installer_modules = Path(modules)
        if not self._browser_manifest_matches(installer_modules / "playwright-core/browsers.json", self.lock["chromium_version"]):
            if self.lock["chromium_version"] != expected["chromium_version"]:
                raise BootstrapError("No approved browser installer for this Chromium lock; do not substitute a browser version")
            # Runtime Playwright 1.62.1's default download is Chromium 151, but
            # frozen rendering uses 149. A separate official installer package
            # obtains 149; it is never selected as the rendering runtime.
            installer_modules = Path(self._install_npm_package(node, expected["package"], expected["version"], "browser-installer-"))
            package = expected["package"]
            installed_version = _json(installer_modules / package / "package.json").get("version")
            if installed_version != expected["version"] or not self._browser_manifest_matches(
                    installer_modules / package / "browsers.json", expected["chromium_version"], expected["chromium_revision"]):
                raise BootstrapError("Official browser installer does not bind both Chromium targets to the frozen version/revision; no browser was downloaded")
        cli = installer_modules / package / "cli.js"
        if not cli.is_file():
            raise BootstrapError(f"Browser installer CLI missing: {cli}")
        _run([node, str(cli), "install", "chromium"], env=self._install_env(node), timeout=900)
        return {"installer_package": package, "installer_modules": str(installer_modules),
                "chromium_version": self.lock["chromium_version"], "rendering_playwright_version": self.lock["playwright_version"]}

    @staticmethod
    def _browser_manifest_matches(path, version, revision=None):
        try:
            browsers = _json(path)["browsers"]
            for name in ("chromium", "chromium-headless-shell"):
                matching = [item for item in browsers if item.get("name") == name]
                if len(matching) != 1 or matching[0].get("browserVersion") != version or (revision is not None and matching[0].get("revision") != revision):
                    return False
            return True
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            return False

    def verify(self, report):
        if not report.get("ready"):
            raise BootstrapError("Required dependencies are missing; cannot verify runtime")
        env = os.environ.copy()
        env.update(report["commands"]["env"])
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        env.pop("PYTHONPATH", None)
        doctor = json.loads(_run(report["commands"]["doctor_argv"], env=env, timeout=60))
        if not doctor.get("passed"):
            raise BootstrapError("Existing layout doctor rejected runtime: " + "; ".join(doctor.get("errors", [])))
        selected = report["selected"]
        _run([selected["python"], "-I", "-B", "-c", "import sys;sys.path.insert(0,sys.argv[1]);import PIL,numpy,lc_typography;print('ok')",
              str(self.root / "scripts")], env=env, timeout=60)
        _run([selected["node"], "-e", BROWSER_SMOKE, str(Path(selected["modules"]) / "playwright"), selected["chromium"]], env=env, timeout=60)
        return {"doctor_passed": True, "python_modules_passed": True, "browser_launch_passed": True}

    def verified_report(self):
        report = self.inspect()
        if not report["ready"]:
            return report
        try:
            report["verification"] = self.verify(report)
            report.update({"verified": True, "verification_required": False, "next_action": "Use commands.python and commands.env for subsequent pipeline commands"})
        except (BootstrapError, OSError, ValueError) as exc:
            report.update({"ready": False, "verified": False, "needs_confirmation": True, "error": str(exc),
                           "next_action": "Review failed runtime verification with the user; do not begin production or install system packages automatically"})
        return report

    def install(self, authorization="unknown"):
        report = self.inspect()
        if authorization not in AUTHORIZED:
            report.update({"ready": False if report["missing"] else report["ready"], "needs_confirmation": bool(report["missing"]),
                           "installation_performed": False, "installation_attempted": False, "next_action": "Ask the user to confirm installing the listed dependencies; do not infer full access" if report["missing"] else "verify"})
            return report
        if any(not item["installable"] for item in report["missing"]):
            report.update({"needs_confirmation": True, "installation_performed": False, "installation_attempted": False,
                           "next_action": "Ask the user to restore original skill resources or supply supported Python before automatic installation"})
            return report
        installed = []
        attempted = False
        browser_installation = None
        try:
            selected = dict(report["selected"])
            if report["missing"]:
                self._prepare_cache()
                attempted = True
            if not selected["python"]:
                selected["python"] = self._install_python(report["usable_python"])
                installed.extend(item["name"] for item in report["missing"] if item["name"] in {"pillow", "numpy"})
            if not selected["node"]:
                selected["node"] = self._install_node()
                installed.append("node")
            if not selected["modules"]:
                selected["modules"] = self._install_playwright(selected["node"])
                installed.append("playwright")
            if not selected["chromium"]:
                browser_installation = self._install_browser(selected["node"], selected["modules"])
                installed.append("chromium")
            report = self.inspect()
            if not report["ready"]:
                raise BootstrapError("Installed runtime does not match the unchanged lock; no version downgrade is allowed")
            report["verification"] = self.verify(report)
            # Only publish paths after real doctor and browser launch succeed.
            if installed:
                self._prepare_cache()
                with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", prefix="selection-", suffix=".json", dir=self.cache, delete=False) as stream:
                    json.dump(report["selected"], stream, ensure_ascii=False, indent=2)
                    temporary = Path(stream.name)
                os.replace(temporary, self.selection_path)
            report.update({"needs_confirmation": False, "verified": True, "verification_required": False,
                           "next_action": "Use commands.python and commands.env for subsequent pipeline commands",
                           "installation_performed": bool(installed), "installation_attempted": attempted, "installed": installed,
                           "browser_installation": browser_installation})
        except (BootstrapError, OSError, ValueError) as exc:
            report = self.inspect()
            report.update({"ready": False, "verified": False, "needs_confirmation": True, "installation_performed": bool(installed),
                           "installation_attempted": attempted, "partial_cache": str(self.cache) if attempted else None, "installed": installed,
                           "error": str(exc), "next_action": "Stop dependency setup. Review the error and remaining list with the user; do not use sudo, install OS packages, change pinned versions or bypass verification"})
        return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("inspect", "verify", "install"))
    parser.add_argument("--authorization", choices=("unknown", "restricted", "full-access", "user-confirmed"), default="unknown",
                        help="Explicit installer permission supplied by Agent/user; never account authentication")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    try:
        bootstrap = RuntimeBootstrap()
        report = bootstrap.inspect() if args.command == "inspect" else bootstrap.verified_report() if args.command == "verify" else bootstrap.install(args.authorization)
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
