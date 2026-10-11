"""Compare old projects against an untouched installation, without credentials.

LC_COMPOSITION_BASELINE must point to a pre-change skill copy (not scripts/).
Never update expectations from the new implementation.
"""
import copy
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import lc_image_pipeline as p
from test_lc_composition import fixture

PROBE = '''
import json,sys
from pathlib import Path
import lc_image_pipeline as p
from lc_review_rules import rule_hashes
m=p.read_json(Path(sys.argv[1])); b=Path(sys.argv[1]).parent; j=m['jobs'][0]
print(json.dumps({'prompt':p.compile_job_prompt(m,j,b)[0],
 'fingerprints':p.current_fingerprints(m,j,b),
 'typography':p.typography_dispatch_fingerprint(m,j,b),
 **{s:rule_hashes(s,m,j) for s in ('qa','review','product')}},sort_keys=True))
'''


@unittest.skipUnless(os.environ.get("LC_COMPOSITION_BASELINE"), "Set LC_COMPOSITION_BASELINE to the pre-change installation")
class CompatibilityTests(unittest.TestCase):
    def test_five_legacy_variants_and_frozen_files(self):
        old = Path(os.environ["LC_COMPOSITION_BASELINE"]).resolve()
        new = p.SCRIPT_DIR.parent
        for name in ("lc_layout.py", "render_layout.mjs", "lc_layout_v3.py", "lc_project_contracts.py",
                     "lc_typography.py", "lc_title_effects.py", "lc_layout_style.py", "render_layout_style.mjs",
                     "lc_assets.py", "lc_quality.py", "lc_design.py", "lc_review_rules.py"):
            self.assertEqual((old/"scripts"/name).read_bytes(),(new/"scripts"/name).read_bytes(),name)
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            with patch.dict(os.environ, {"LC_SKIP_AUTH_PASS_FOR_TESTS":"1", "LC_TEMPLATE_LIBRARY_DIR":str(base/"library")}):
                original = fixture(base,policy=False)
                for variant in ("compact", "full", "main", "portrait", "style_v1"):
                    with self.subTest(variant=variant):
                        m = copy.deepcopy(original); j=m["jobs"][0]
                        if variant == "full": j.pop("prompt_format",None)
                        if variant == "main":
                            j.update(kind="main",layout={})
                        if variant == "portrait": j["canvas"]=[1600,2080]
                        if variant == "style_v1": j["layout"]["renderer"]="style_v1"
                        path=base/"project_manifest.json";p.write_json(path,m)
                        results=[]
                        for root in (old,new):
                            env={**os.environ,"PYTHONPATH":str(root/"scripts")}
                            run=subprocess.run([sys.executable,"-B","-c",PROBE,str(path)],cwd=base,env=env,
                                               text=True,capture_output=True,check=True)
                            results.append(json.loads(run.stdout))
                        for key in results[0]:
                            self.assertEqual(results[0][key],results[1][key],f"{variant}: {key}")


if __name__ == "__main__":
    unittest.main()
