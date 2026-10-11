"""The recipient-facing auth chain is frozen: files, binaries and the documented auth sections.

Hashes are V7.2's (identical to the original release except lc_auth_pass.py, whose
machine-id fingerprint + temp fallback was approved in V7.1). Never prints config.json.
"""
from __future__ import annotations

import hashlib
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PINNED = {
    "scripts/auth_gate.py": "d17db72a82d7b60369ac1dea8d2eaf92820703e3b2b0fe78e727255c2d4772e6",
    "scripts/lc_auth_pass.py": "94901efef50611fcf8c08d71bc3a4bef265a7a6b1e89efb4c1f578d7699be216",
    "scripts/lc_paths.py": "23bc1fffe86611fec2fc16555762df797dfac593b2c14db62d001a1bc894735a",
    "scripts/configure_credentials.py": "8466f82b8a6e7db5dfe265b19a6d954495d23f05cdbb3be46300ddcd514f85ab",
    "scripts/diagnose_auth.py": "998c09c36abd9a8c07f7a3d8e2c7a503c9d4801b08a5f714d13fbd77594925bc",
    "references/auth-binaries.json": "58e0f040bf0369e962d33167a20e524f0b2efbd18d475f6e48f7d1c322480e00",
    "tools/bin/lc-auth-check-darwin-amd64": "9d218f624ad547725062ba381aa523f46b9b0b1ab830ead6eaae2644656dfa73",
    "tools/bin/lc-auth-check-darwin-arm64": "0c50813cd3a482aea81b94141a5109256487d20351c4b31272de60b7aac1b559",
    "tools/bin/lc-auth-check-linux-amd64": "9dde60a8ad7908473df3fdd65f8695e407a9f8b0263c4f56625f2b841ff1a9f1",
    "tools/bin/lc-auth-check-windows-amd64.exe": "e1e639a282595744f80c2f3fec2bc814b116c357252b611068c2dd1c18cd5783",
}
# (line count, sha256) of blocks that must appear verbatim (V7.2 text).
SKILL_BLOCKS = {
    "token_bullet": (1, "70c0ecd3b20629f2f967f6d9d2d80eaf3e8ba652cff7b3205de9f5fcba14c8e5"),
    "python_note": (3, "5da4903b379e5471bc27170f41406912b82d51331548d64c491f67baacdabdd2"),
    "boundary_production": (5, "a4b689bf0970dd44751bcc03a7721e97ada7ff338fabc3bcc84aa09b3fad939b"),
    "network_section": (8, "32ea42de791a035e616c88ab3a8bf67ef2c6d065b3888b3897a6136ebb418022"),
    "credentials_section": (7, "0156b1a4b109b7741b7e1d42be9b5d00a5ccd71c3f93cedd65748b769e56a0fa"),
}
MAINTENANCE_BLOCK = (6, "b99afedd12ee64de23bdea0c25bcede3328206cd192ecf72fa6a82b65bca2d38")


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def _has_block(text, count, digest):
    lines = text.split("\n")
    return any(_sha("\n".join(lines[start:start + count]).encode("utf-8")) == digest
               for start in range(len(lines) - count + 1))


class AuthInvariantTests(unittest.TestCase):
    def test_auth_files_and_binaries_are_byte_identical(self):
        for relative, digest in PINNED.items():
            with self.subTest(file=relative):
                self.assertEqual(_sha((ROOT / relative).read_bytes()), digest)

    def test_binary_manifest_matches_the_shipped_binaries(self):
        manifest = json.loads((ROOT / "references/auth-binaries.json").read_text(encoding="utf-8"))["sha256"]
        for name, digest in manifest.items():
            self.assertEqual(_sha((ROOT / "tools/bin" / name).read_bytes()), digest, name)

    def test_working_copy_token_is_empty(self):
        path = ROOT / "config.json"
        if not path.is_file():
            self.skipTest("no config.json in this copy (release builds generate a blank one)")
        token = json.loads(path.read_text(encoding="utf-8")).get("backend_token")
        self.assertTrue(token == "", "config.json backend_token must stay empty in the skill copy")

    def test_skill_md_keeps_the_auth_sections_verbatim(self):
        text = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        for name, (count, digest) in SKILL_BLOCKS.items():
            with self.subTest(block=name):
                self.assertTrue(_has_block(text, count, digest), f"SKILL.md block changed: {name}")
        self.assertIn("references/maintenance.md#接收者鉴权故障排查", text)
        self.assertIn("`plan`/`deliver` 会校验它", text)

    def test_maintenance_keeps_the_recipient_troubleshooting_section(self):
        text = (ROOT / "references/maintenance.md").read_text(encoding="utf-8")
        self.assertTrue(_has_block(text, *MAINTENANCE_BLOCK))

    def test_plan_and_deliver_are_still_gated_before_reading_the_project(self):
        source = (ROOT / "scripts/studio.py").read_text(encoding="utf-8")
        self.assertIn('if command in {"plan", "deliver"}:', source)
        self.assertIn("check_pass(SCRIPT_DIR.parent)", source)


if __name__ == "__main__":
    unittest.main()
