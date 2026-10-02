"""Existing-package bridge preserves Python 3.9 PDF/TOML semantics."""
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from common import now_iso
from runtime_compat import ExistingPackageFinder, _package_path, dependency_info, dependency_roots


class RuntimeCompatTests(unittest.TestCase):
    def test_pdf_round_trip_runs_inside_the_current_interpreter(self):
        from pypdf import PdfReader, PdfWriter
        buffer = io.BytesIO()
        writer = PdfWriter()
        writer.add_blank_page(width=144, height=72)
        writer.add_metadata({"/Title": "compatibility fixture"})
        writer.write(buffer)
        reader = PdfReader(buffer)
        self.assertEqual(len(reader.pages), 1)
        self.assertEqual(reader.pages[0].mediabox.width, 144)
        self.assertEqual(reader.metadata.title, "compatibility fixture")
        self.assertEqual(dependency_info("pypdf")["version"], "6.10.0")

    def test_existing_toml_parser_retains_all_types_and_invalid_input_errors(self):
        import tomllib
        from datetime import date
        value = tomllib.loads('title="fixture"\nwhen=2026-09-27\namount=1.25\nitems=[1,2]\n'
                             '[features]\nhooks=false\n[\"quoted.key\"]\nvalue="""many\nlines"""\n')
        self.assertEqual(value["when"], date(2026, 9, 27))
        self.assertEqual(value["amount"], 1.25)
        self.assertEqual(value["items"], [1, 2])
        self.assertIs(value["features"]["hooks"], False)
        self.assertEqual(value["quoted.key"]["value"], "many\nlines")
        self.assertEqual(tomllib.load(io.BytesIO(b"[features]\nhooks=true\n")), {"features": {"hooks": True}})
        with self.assertRaises(tomllib.TOMLDecodeError):
            tomllib.loads("key=1\nkey=2\n")
        with self.assertRaises(tomllib.TOMLDecodeError):
            tomllib.loads("invalid = [")

    def test_explicit_missing_root_does_not_fall_back_or_install(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(
                "os.environ", {"LC_IPR_DEPENDENCY_ROOT": directory}):
            self.assertEqual(dependency_roots(), [Path(directory).resolve()])
            self.assertIsNone(_package_path("pypdf", dependency_roots()))
            self.assertIsNone(_package_path("tomllib", dependency_roots()))

    def test_finder_never_exports_other_packages_or_foreign_compiled_extensions(self):
        finder = ExistingPackageFinder({"pypdf": Path("/existing/pypdf")})
        self.assertIsNone(finder.find_spec("cryptography"))
        self.assertIsNone(finder.find_spec("pypdf._crypt_providers._cryptography"))
        with self.assertRaisesRegex(ValueError, "NOT_ALLOWLISTED"):
            dependency_info("cryptography")

    def test_wrong_pdf_version_is_not_selected_as_pinned_dependency(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            package = root / "lib/python3.12/site-packages/pypdf"
            package.mkdir(parents=True)
            (package / "__init__.py").write_text("__version__='6.9.0'\n")
            metadata = package.parent / "pypdf-6.9.0.dist-info"
            metadata.mkdir()
            (metadata / "METADATA").write_text("Metadata-Version: 2.1\nName: pypdf\nVersion: 6.9.0\n")
            self.assertIsNone(_package_path("pypdf", [root]))
