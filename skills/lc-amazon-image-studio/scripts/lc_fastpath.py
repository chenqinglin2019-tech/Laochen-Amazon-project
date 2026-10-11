"""Process-local speed and platform hooks for the CLI (V7.1). LC_FASTPATH=0 disables them.

Installed once by `lc_image_pipeline.main()`. They change how fast or how robustly
results are produced, never the results: the tripwire test runs with and without
them and requires identical prompts and fingerprints.

- Windows: os.replace/os.unlink retry brief sharing violations (antivirus, indexer,
  sync clients) through lc_fsretry. This reaches writes inside modules whose source
  is part of review-rule hashes and therefore must not be edited.
- Review-rule source slices (an AST walk over four large modules, ~0.2 s per
  process) are cached across processes, keyed by Python version and the exact
  source text of both the sliced module and lc_review_rules.
- During a render, the runtime doctor (which spawns `chromium --version` and
  `node --version` and re-hashes fonts) is answered from a still-valid verify stamp
  for the same selected runtime; a failed render invalidates the stamp.
"""
from __future__ import annotations

import contextlib
import hashlib
import json
import os
import sys
import tempfile
from pathlib import Path

_ORIGINALS: dict = {}


def enabled() -> bool:
    return os.environ.get("LC_FASTPATH", "1") != "0"


# ---- Windows file retries ------------------------------------------------------------------
def _install_windows_io():
    if os.name != "nt" or "os.replace" in _ORIGINALS:
        return
    import lc_fsretry  # captures the originals first
    _ORIGINALS["os.replace"], _ORIGINALS["os.unlink"] = os.replace, os.unlink

    def replace(src, dst, *, src_dir_fd=None, dst_dir_fd=None):
        if src_dir_fd is not None or dst_dir_fd is not None:
            return _ORIGINALS["os.replace"](src, dst, src_dir_fd=src_dir_fd, dst_dir_fd=dst_dir_fd)
        return lc_fsretry.replace(src, dst)

    def unlink(path, *, dir_fd=None):
        if dir_fd is not None:
            return _ORIGINALS["os.unlink"](path, dir_fd=dir_fd)
        return lc_fsretry.unlink(path, missing_ok=False)

    os.replace, os.unlink = replace, unlink


# ---- review-rule slice cache --------------------------------------------------------------
def _slice_cache_path():
    from lc_paths import cache_home
    return cache_home() / "rule-slices-v1.json"


def _install_rule_cache():
    if "slice" in _ORIGINALS:
        return
    import lc_review_rules
    original = lc_review_rules._slice_source
    _ORIGINALS["slice"] = original
    rules_source = Path(lc_review_rules.__file__).read_bytes()
    version = f"{sys.version_info.major}.{sys.version_info.minor}"
    path = _slice_cache_path()
    try:
        store = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(store, dict):
            store = {}
    except (OSError, ValueError):
        store = {}
    state = {"dirty": False}

    def cached(name, source):
        key = hashlib.sha256(b"\0".join([version.encode(), name.encode(), hashlib.sha256(rules_source).digest(),
                                         source.encode("utf-8")])).hexdigest()
        value = store.get(key)
        if isinstance(value, str) and len(value) == 64:
            return value
        value = original(name, source)
        store[key] = value
        state["dirty"] = True
        _save()
        return value

    def _save():
        if not state["dirty"]:
            return
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            keep = dict(list(store.items())[-64:])  # bounded
            with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, prefix=".rule-slices-", delete=False) as handle:
                json.dump(keep, handle)
            os.replace(handle.name, path) if os.name != "nt" else _replace_any(handle.name, path)
            state["dirty"] = False
        except OSError:
            pass  # a read-only cache only costs the original computation

    lc_review_rules._slice_source = cached


def _replace_any(src, dst):
    import lc_fsretry
    lc_fsretry.replace(src, dst)


# ---- doctor answered from the verify stamp during renders ----------------------------------
def _cached_doctor():
    """The doctor() result reconstructed from a still-valid verify stamp, or None."""
    try:
        from runtime_bootstrap import RuntimeBootstrap
        bootstrap = RuntimeBootstrap()
        cached = bootstrap.cached_report()
        if not cached:
            return None
        selected = cached["selected"]
        for env, key in (("LC_LAYOUT_NODE", "node"), ("LC_LAYOUT_NODE_MODULES", "modules"), ("LC_LAYOUT_CHROMIUM", "chromium")):
            value = os.environ.get(env)
            if value and Path(value).resolve() != Path(selected[key]).resolve():
                return None  # an explicit different runtime: use the real doctor
        return {"passed": True, "errors": [], "node": selected["node"], "modules": selected["modules"],
                "chromium": selected["chromium"], "versions": bootstrap.lock, "source": "verified_stamp"}
    except Exception:  # noqa: BLE001 - any doubt means the real doctor runs
        return None


def _install_doctor_cache():
    if "render_batch" in _ORIGINALS:
        return
    import lc_layout
    import lc_layout_style  # noqa: F401  routing wrapper must be in place first
    original_render, original_doctor = lc_layout.render_batch, lc_layout.doctor
    _ORIGINALS["render_batch"], _ORIGINALS["doctor"] = original_render, original_doctor

    def render_batch(manifest, base, jobs, *, measure_only=False):
        report = _cached_doctor()
        if report is None:
            return original_render(manifest, base, jobs, measure_only=measure_only)
        lc_layout.doctor = lambda: dict(report)
        try:
            results = original_render(manifest, base, jobs, measure_only=measure_only)
        finally:
            lc_layout.doctor = original_doctor
        if any(any(check.get("check") == "runtime" and not check.get("passed") for check in item.get("checks", []))
               for item in results.values()):
            try:
                from runtime_bootstrap import RuntimeBootstrap
                RuntimeBootstrap().invalidate()  # the stamp was wrong: verify again next time
            except Exception:  # noqa: BLE001
                pass
        return results

    lc_layout.render_batch = render_batch


def install():
    if not enabled():
        return
    _install_windows_io()
    _install_rule_cache()
    _install_doctor_cache()


def uninstall():
    if "os.replace" in _ORIGINALS:
        os.replace, os.unlink = _ORIGINALS.pop("os.replace"), _ORIGINALS.pop("os.unlink")
    if "slice" in _ORIGINALS:
        import lc_review_rules
        lc_review_rules._slice_source = _ORIGINALS.pop("slice")
    if "render_batch" in _ORIGINALS:
        import lc_layout
        lc_layout.render_batch = _ORIGINALS.pop("render_batch")
        lc_layout.doctor = _ORIGINALS.pop("doctor")


@contextlib.contextmanager
def installed():
    install()
    try:
        yield
    finally:
        uninstall()
