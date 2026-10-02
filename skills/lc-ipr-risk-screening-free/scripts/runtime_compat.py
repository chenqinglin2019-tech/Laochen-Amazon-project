"""Use existing pure-Python PDF/TOML packages with a Python 3.9 entry point.

Only these two package names can use the existing dependency runtime. No
foreign site-packages directory or compiled extension is added to sys.path.
"""
from __future__ import annotations

import importlib.abc
import importlib.metadata
import importlib.util
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
PACKAGE_NAMES = frozenset({"pypdf", "tomllib"})


def dependency_roots():
    explicit = os.environ.get("LC_IPR_DEPENDENCY_ROOT")
    if explicit:
        return [Path(explicit).expanduser().resolve()]
    # Both are existing installation locations; no package is downloaded or
    # copied. An explicit root does not fall back to a different installation.
    return [ROOT / ".venv", Path.home() / ".cache/codex-runtimes/codex-primary-runtime/dependencies/python"]


def _package_path(name, roots):
    for root in roots:
        parents = [root / "Lib", *sorted((root / "lib").glob("python3.*"))]
        for parent in parents:
            path = parent / ("site-packages" if name == "pypdf" else "") / name
            if not (path / "__init__.py").is_file():
                continue
            if name == "pypdf":
                distributions = list(path.parent.glob("pypdf-*.dist-info"))
                if len(distributions) != 1 or importlib.metadata.PathDistribution(
                        distributions[0]).version != "6.10.0":
                    continue
            return path.resolve()
    return None


class ExistingPackageFinder(importlib.abc.MetaPathFinder):
    _lc_ipr_existing_packages = True

    def __init__(self, packages):
        self.packages = dict(packages)

    def find_spec(self, fullname, path=None, target=None):
        package = self.packages.get(fullname)
        if package is None:
            return None
        return importlib.util.spec_from_file_location(fullname, package / "__init__.py",
                                                     submodule_search_locations=[str(package)])


def install_existing_dependencies():
    if any(getattr(finder, "_lc_ipr_existing_packages", False) for finder in sys.meta_path):
        return
    roots = dependency_roots()
    packages = {name: path for name in PACKAGE_NAMES
                if importlib.util.find_spec(name) is None
                for path in [_package_path(name, roots)] if path is not None}
    if packages:
        sys.meta_path.append(ExistingPackageFinder(packages))


def dependency_info(name):
    if name not in PACKAGE_NAMES:
        raise ValueError("COMPAT_PACKAGE_NOT_ALLOWLISTED")
    spec = importlib.util.find_spec(name)
    if spec is None:
        return {"available": False, "origin": None, "version": None, "existing_runtime": False}
    package = Path(spec.origin).resolve().parent
    fallback = any(getattr(finder, "_lc_ipr_existing_packages", False) and
                   finder.packages.get(name) == package for finder in sys.meta_path)
    version = None
    if name == "pypdf":
        distributions = list(package.parent.glob("pypdf-*.dist-info"))
        if len(distributions) == 1:
            version = importlib.metadata.PathDistribution(distributions[0]).version
    return {"available": True, "origin": spec.origin, "version": version, "existing_runtime": fallback}
