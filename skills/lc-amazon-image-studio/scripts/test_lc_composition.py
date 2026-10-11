"""Isolated synthetic regression tests. No accounts, credentials or model calls."""
import copy
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image, ImageDraw

import lc_image_pipeline as p
import lc_composition as c
import lc_quality as q
import lc_scheduler
import lc_workflow as workflow

NOTE = "Synthetic test observation; never production evidence or a real product review."


def fixture(base, *, policy=True, canvas=(1600, 1600), siblings=False):
    m = p.read_json(p.SCRIPT_DIR.parent / "assets/project_manifest.template.json")
    m.update(project_id="composition-fixture", test_fixture=True, marketplace="US", language="en",
             critical_detail_census_completed=True, review_rule_profile="scoped_v1", review_dependency_version=2,
             scheduler_policy=lc_scheduler.default_policy())
    m["listing_profile"] = {"aspect": "1:1.3" if canvas[1] == canvas[0]*1.3 else "1:1", "short_edge": canvas[0]}
    if policy:
        m.update(composition_policy=copy.deepcopy(c.POLICY), anchor_policy={"version": 1, "mode": "full_review_first"})
    m["product_truth"].update(product="Synthetic rectangular fixture with no accessories")
    m["product_truth"]["geometry_lock"].update(locked_structure=["one rectangle"], normalized_ratio="rectangle")
    m["product_truth"]["material_lock"].update(color="red", finish="matte")
    m["product_truth"]["scene_scale_lock"].update(support_surface="plain wall")
    for folder in ("source", "raw", "final"):
        (base/folder).mkdir(parents=True, exist_ok=True)
    im = Image.new("RGB", (1600, 1600), "white")
    ImageDraw.Draw(im).rectangle((800, 160, 1440, 1440), fill="#d62828")
    im.save(base/"source/product_front.png")
    m["references"][0].update(product_bbox_norm=[.5,.1,.4,.8], provenance={"kind":"real_photo", "notes":NOTE})
    job = copy.deepcopy(m["jobs"][2])
    job.update(canvas=list(canvas), render_mode="reference_edit", prompt_profile="images_2_5_v1", prompt_format="compact_v2",
               scene="Plain wall without people", composition="Full silhouette on the right", lighting="Soft even light")
    if canvas[0] > canvas[1]:
        job.update(kind="a_plus", a_plus_module="header")
    job["layout"] = {"version":3, "recipe":"photo_overlay", "product_region_norm":[.52,.08,.43,.84],
                     "text_groups":[{"id":"message", "headline":"A quiet home", "body":"Simple everyday style.",
                                     "box":[.05,.12,.38,.7], "text_color":"#111111",
                                     "mobile_sizes":{"headline":22,"body":12,"label":12}}], "items":[]}
    job["composition_intent"] = {"negative_space":"Uninterrupted pale wall on the left", "subject_scale":"Prominent full-height object on the right", "layout_reason":"Scene photograph with short left-aligned copy"}
    job["design_brief"] = {"version":1,"generation":{"background":"Plain pale wall; a synthetic test scene"},"layout":{}}
    job["source_assessment"].update(scene_fit="matched", evidence="sufficient", degradation="none", reason=NOTE, matched_reference_ids=["product_front"])
    job["target_product_bbox_norm"] = job["layout"]["product_region_norm"].copy()
    m["jobs"] = [job]
    if siblings:
        other = copy.deepcopy(job)
        other.update(id="04_detail", raw_output="raw/04_detail.png", final_output="final/04_detail.png")
        m["jobs"].append(other)
    bind_sources(m, base)
    return m


def bind_sources(m, base):
    q.assess_sources(m, base)
    for ref in m["references"]:
        ref["quality_review"] = {"clarity":"clear", "evidence":"sufficient", "defects":[], "notes":NOTE,
                                 "reviewed_sha256":ref["sha256"], "reviewed_region_fingerprint":q.source_region_fingerprint(ref)}
    for job in m["jobs"]:
        decision = q.decide_job(m, job)
        job["source_assessment"].update(reviewed_reference_hashes=decision["required_reference_hashes"],
                                         reviewed_context_fingerprint=decision["assessment_context_fingerprint"])
    q.assess_sources(m, base)


def base_output(m, base, job=None, *, box=(.56,.12,.34,.76)):
    job = job or m["jobs"][0]
    c.freeze(m, job)
    job["generation_geometry_lock"] = c.contract(job)["geometry"]
    image = Image.new("RGB", tuple(job["canvas"]), "#ffffff")
    ImageDraw.Draw(image).rectangle(p.normalized_to_pixels(list(box), *image.size), fill="#d62828")
    image.save(base/job["raw_output"])
    job.update(bound_raw_sha256=p.sha256_file(base/job["raw_output"]), generated_prompt_hash=p.generation_fingerprint(m, job, base), status="generated")
    return job


def base_packet(m, base, job=None, box=(.56,.12,.34,.76)):
    job = job or m["jobs"][0]
    return {"schema_version":1,"stage":"composition","job":job["id"],"context":c.context(m,job,base),
            "observed_product_bbox_norm":list(box),"observed_protected_regions":[],
            "checks":{k:{"verdict":"pass","notes":NOTE+" "+k} for k in c.BASE_CHECKS}}


def design():
    return {"verdict":"pass", "notes":NOTE, "checks":{k:{"verdict":"pass","notes":NOTE+" "+k} for k in c.FINAL_CHECKS}}


class CompositionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.env = patch.dict(os.environ, {"LC_SKIP_AUTH_PASS_FOR_TESTS":"1", "LC_TEMPLATE_LIBRARY_DIR":str(self.base/"library")})
        self.env.start()
        c.install()
        self.m = fixture(self.base)

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def test_new_project_defaults_and_main_only(self):
        path = p.init_project(self.base/"new", "new-fixture", marketplace="US", language="en")
        m = p.read_json(path)
        self.assertTrue(c.enabled(m))
        self.assertEqual(m["anchor_policy"]["mode"], "full_review_first")
        m["jobs"] = [m["jobs"][0]]
        self.assertIsNone(c.sample_id(m))

    def test_missing_review_blocks_render(self):
        base_output(self.m, self.base)
        with self.assertRaisesRegex(p.PipelineError, "COMPOSITION_REVIEW_REQUIRED"):
            p.aspect_safe_postprocess(self.m, self.base)
        self.assertFalse((self.base/"review/layouts").exists())

    def test_observed_overlap_routes_to_generation_repair_and_budget_stops(self):
        job = base_output(self.m, self.base, box=(.18,.02,.65,.95))
        packet = base_packet(self.m, self.base, box=(.18,.02,.65,.95))
        result = workflow.review_submit(self.m, self.base, packet)
        self.assertEqual(result["status"], "generation_repair_needed")
        self.assertIn("composition:observed_text_overlap", result["failures"])
        self.assertTrue(c.prepare_repair(self.m, job, self.base))
        self.assertIn("composition:observed_text_overlap", job["prompt_edit"]["failures"])
        job["quality_repairs"] = 1
        # Re-use the same failed raw with a current review context, never restore a budget.
        job["generated_prompt_hash"] = p.generation_fingerprint(self.m, job, self.base)
        result = workflow.review_submit(self.m, self.base, base_packet(self.m,self.base,box=(.18,.02,.65,.95)))
        self.assertEqual(result["status"], "blocked")
        self.assertTrue(job["blocked_reason"].startswith("QUALITY_REPAIR_LIMIT_REACHED"))

    def test_proof_binding_idempotency_and_changed_raw(self):
        job = base_output(self.m,self.base)
        packet = base_packet(self.m,self.base)
        self.assertTrue(workflow.review_submit(self.m,self.base,packet)["passed"])
        self.assertTrue(c.proof_valid(self.m,job,self.base))
        self.assertTrue(workflow.review_submit(self.m,self.base,packet)["idempotent"])
        Image.new("RGB", (1600,1600), "black").save(self.base/job["raw_output"])
        self.assertFalse(c.proof_valid(self.m,job,self.base))

    def test_lock_rejects_footer_crop_and_canvas_change(self):
        original = base_output(self.m,self.base)
        for change in ("footer", "crop", "canvas"):
            job = copy.deepcopy(original)
            if change == "footer": job["layout"]["text_groups"][0]["box"] = [.05,.8,.9,.15]
            if change == "crop": job["layout"]["panels"] = [{"image":"raw/x.png","box":[.4,0,.6,1],"source_crop":[.1,0,.8,1],"evidence_refs":["product_front"]}]
            if change == "canvas": job["canvas"] = [1600,2080]
            with self.assertRaisesRegex(p.PipelineError,"COMPOSITION_"):
                c.check_plan(self.m,job)

    def test_explicit_final_checks_cannot_be_omitted(self):
        with self.assertRaises(p.PipelineError): c.validate_final({"verdict":"pass","notes":NOTE})
        c.validate_final(design(),require_passed=True)
        bad = design(); bad["checks"]["subject_scale"]["verdict"] = "fail"
        with self.assertRaises(p.PipelineError): c.validate_final(bad)

    def test_line_break_adjustments_preserve_composition_but_not_copy_edits(self):
        job=base_output(self.m,self.base)
        workflow.review_submit(self.m,self.base,base_packet(self.m,self.base))
        job["layout"]["text_groups"][0]["headline"]="A quiet\nhome"
        self.assertTrue(c.proof_valid(self.m,job,self.base))
        job["layout"]["text_groups"][0]["headline"]="A new home"
        with self.assertRaisesRegex(p.PipelineError,"COMPOSITION_LOCK_CHANGED"):
            c.check_plan(self.m,job)

    def test_sample_quick_approval_does_not_release_siblings(self):
        self.m = fixture(self.base,siblings=True)
        self.m["generation_gate"] = {"status":"open"}
        self.m["jobs"][0]["anchor_product_proof"] = {"path":"unused"}
        plan = p.execution_plan(self.m,self.base)
        self.assertEqual(plan["anchor"],"03_primary_use_case")
        self.assertEqual([item["id"] for item in plan["dispatch"]],["03_primary_use_case"])
        self.m["jobs"][0]["status"] = "generated"
        self.assertEqual(p.execution_plan(self.m,self.base)["dispatch"],[])

    def test_prompt_regions_and_reframing(self):
        for canvas in ((1600,1600),(1600,2080),(1464,600)):
            m = fixture(self.base,canvas=canvas)
            job = m["jobs"][0]
            prompt = p.compile_job_prompt(m,job,self.base)[0]
            self.assertIn("layout_first/1",prompt)
            self.assertIn(json.dumps(p.generation_geometry(job),ensure_ascii=False,sort_keys=True),prompt)
            self.assertNotIn("preserve already-correct product details, framing and typography",prompt)

    def test_autofit_does_not_silently_replace_new_design(self):
        from lc_layout_autofit import autofit
        job = self.m["jobs"][0]
        job.update(status="blocked",blocked_reason="DESIGN_COPY:TYPOGRAPHY_PREFLIGHT",layout_alternatives=["photo_sidebar:fit"])
        old = copy.deepcopy(job["layout"])
        self.assertEqual(autofit(self.m,self.base,{job["id"]},lambda changed: self.fail("unexpected replan")),[])
        self.assertEqual(job["layout"],old)

    def test_hold_and_pending_siblings_do_not_block_ready_image(self):
        from lc_runtime_env import apply_selected_runtime
        apply_selected_runtime()
        self.m = fixture(self.base,siblings=True)
        held = self.m["jobs"][1]
        held["hold"] = True
        held.pop("composition_intent")  # HOLD is not required to have a production plan.
        p.prepare(self.m,self.base)
        base_output(self.m,self.base)
        workflow.review_submit(self.m,self.base,base_packet(self.m,self.base))
        p.aspect_safe_postprocess(self.m,self.base)
        self.assertTrue((self.base/"review/layouts/03_primary_use_case.png").is_file())
        self.assertFalse((self.base/"review/layouts/04_detail.png").exists())
        p.aspect_safe_postprocess(self.m,self.base,job_ids=[held["id"]])
        self.assertEqual(p.quality_assurance(self.m,self.base,[held["id"]])["jobs"],[])
        held["hold"] = False
        held["composition_intent"] = copy.deepcopy(self.m["jobs"][0]["composition_intent"])
        held["status"] = "pending"
        p.aspect_safe_postprocess(self.m,self.base)
        self.assertFalse((self.base/"review/layouts/04_detail.png").exists())

    def test_local_composite_review_and_bounded_repair(self):
        from lc_runtime_env import apply_selected_runtime
        apply_selected_runtime()
        self.m["style_contract"] = p.default_style_contract()
        job = self.m["jobs"][0]
        job.update(render_mode="pixel_composite", product_layers=[{"reference_id":"product_front", "opaque_rectangle":True,
                    "crop_bbox_norm":[.5,.1,.4,.8],"bbox_norm":[.54,.1,.39,.78]}])
        bind_sources(self.m,self.base)
        prepared = c.prepare_review(self.m,self.base)
        self.assertEqual(prepared["errors"],[])
        self.assertTrue(job["typography_dispatch_binding"]["passed"])
        packet = base_packet(self.m,self.base,box=job["raw_product_bbox_norm"])
        packet["checks"]["subject_scale"]["verdict"] = "fail"
        self.assertEqual(workflow.review_submit(self.m,self.base,packet)["status"],"blocked")
        job["product_layers"][0]["bbox_norm"] = [.56,.12,.36,.72]
        bind_sources(self.m,self.base)
        prepared = c.prepare_review(self.m,self.base,repair=True)
        self.assertEqual(prepared["errors"],[])
        self.assertEqual(job["quality_repairs"],1)
        self.assertEqual(len(job["composition_repair_history"]),1)
        workflow.review_submit(self.m,self.base,base_packet(self.m,self.base,box=job["raw_product_bbox_norm"]))
        self.assertTrue(c.proof_valid(self.m,job,self.base))
        packet = base_packet(self.m,self.base,box=job["raw_product_bbox_norm"])
        packet["checks"]["natural_space"]["verdict"] = "fail"
        workflow.review_submit(self.m,self.base,packet)
        self.assertTrue(job["blocked_reason"].startswith("QUALITY_REPAIR_LIMIT_REACHED"))
        self.assertIn("LOCAL_COMPOSITION_REPAIR_UNAVAILABLE",c.prepare_review(self.m,self.base,repair=True)["errors"][0]["error"])

    def test_panel_asset_and_preview_changes_expire_review(self):
        job = self.m["jobs"][0]
        job["layout"]["panels"] = [{"id":"product","box":[.52,.08,.43,.84],"image":"source/product_front.png",
                                    "fit":"contain","evidence_refs":["product_front"]}]
        base_output(self.m,self.base)
        result = c.prepare_review(self.m,self.base)
        self.assertEqual(result["errors"],[])
        self.assertNotEqual(result["packets"][0]["look_at"],str(self.base/job["raw_output"]))
        workflow.review_submit(self.m,self.base,base_packet(self.m,self.base))
        self.assertTrue(c.proof_valid(self.m,job,self.base))
        Image.new("RGB",(1600,1600),"black").save(self.base/job["composition_preview"]["path"])
        self.assertFalse(c.proof_valid(self.m,job,self.base))

    def test_inset_contain_circle_and_shape_lock(self):
        job = self.m["jobs"][0]
        job["layout"]["product_region_norm"] = [.52,.08,.43,.74]
        Image.new("RGB",(1600,800),"red").save(self.base/"source/inset.png")
        job["layout"]["items"] = [{"text":"Detail","image":"source/inset.png","evidence_refs":["product_front"],
            "image_shape":"rect","box":[.5,.3,.4,.6],"image_box":[.5,.3,.25,.5],"text_box":[.5,.85,.4,.1]}]
        # Inspect photographic pixels only; frozen renderer still checks labels.
        base_output(self.m,self.base)
        path = self.base/c.review_image(job,self.base)
        with Image.open(path) as im:
            self.assertEqual(im.getpixel((820,490)),(255,255,255))
            self.assertEqual(im.getpixel((900,850)),(255,0,0))
        changed = copy.deepcopy(job)
        changed["layout"]["items"][0]["image_shape"] = "circle"
        with self.assertRaisesRegex(p.PipelineError,"COMPOSITION_LOCK_CHANGED"):
            c.check_plan(self.m,changed)
        changed.pop("composition_contract")
        path=self.base/c.review_image(changed,self.base)
        with Image.open(path) as im:
            self.assertEqual(im.getpixel((802,482)),(255,255,255))
            self.assertEqual(im.getpixel((1000,600)),(255,0,0))

    def test_composition_cli_transaction_and_stale_proof(self):
        job=base_output(self.m,self.base)
        manifest=self.base/"project_manifest.json"
        p.write_json(manifest,self.m)
        def cli(*args):
            run=subprocess.run([sys.executable,"-B",str(p.SCRIPT_DIR/"lc_image_pipeline.py"),*args,
                                "--manifest",str(manifest),"--json"],capture_output=True,text=True)
            self.assertEqual(run.returncode,0,run.stdout+run.stderr)
            return json.loads(run.stdout)
        result=cli("review-prepare","--stage","composition","--job",job["id"])
        self.assertEqual(result["errors"],[])
        self.m=p.read_json(manifest)
        packet=self.base/"review/packets/filled.json"
        p.write_json(packet,base_packet(self.m,self.base))
        cli("review-submit","--packet",str(packet))
        self.m=p.read_json(manifest);job=self.m["jobs"][0]
        self.assertTrue(c.proof_valid(self.m,job,self.base))
        job["layout"]["text_groups"][0]["box"]=[.05,.08,.4,.4]
        self.assertFalse(c.proof_valid(self.m,job,self.base))

    @unittest.skipUnless(os.environ.get("LC_COMPOSITION_DOORBELL"),"Set LC_COMPOSITION_DOORBELL to replay the original failed base")
    def test_original_doorbell_overlap_is_blocked_before_text(self):
        source=Path(os.environ["LC_COMPOSITION_DOORBELL"])
        job=self.m["jobs"][0]
        # Observed from the actual original image, including the complete hanger.
        with Image.open(source) as im:
            job["canvas"]=list(im.size)
            im.save(self.base/job["raw_output"])
        c.freeze(self.m,job)
        job.update(status="generated",bound_raw_sha256=p.sha256_file(self.base/job["raw_output"]),
                   generated_prompt_hash=p.generation_fingerprint(self.m,job,self.base))
        result=workflow.review_submit(self.m,self.base,base_packet(self.m,self.base,box=(.19,.03,.62,.94)))
        self.assertIn("composition:observed_text_overlap",result["failures"])
        self.assertEqual(result["status"],"generation_repair_needed")
        p.aspect_safe_postprocess(self.m,self.base)
        self.assertFalse((self.base/"review/layouts").exists())

    def test_real_font_overflow_prevents_dispatch(self):
        from lc_runtime_env import apply_selected_runtime
        from lc_dispatch import reserve
        apply_selected_runtime()
        self.m["style_contract"] = p.default_style_contract()
        job = self.m["jobs"][0]
        job["layout"]["text_groups"][0].update(headline="Extremely long approved title "*5,
                                               body="Approved descriptive copy that cannot be dropped. "*9,
                                               box=[.05,.12,.12,.15])
        before = copy.deepcopy(job["layout"])
        p.prepare(self.m,self.base)
        self.assertEqual(reserve(self.m,self.base)["reservations"],[])
        self.assertFalse(job.get("generation_attempts"))
        self.assertFalse(job["typography_dispatch_binding"]["passed"])
        self.assertEqual(job["layout"],before)

    def test_final_base_failure_is_not_a_layout_repair(self):
        from lc_runtime_env import apply_selected_runtime
        from lc_review_sheets import expand_todos
        apply_selected_runtime()
        p.prepare(self.m,self.base)
        job = base_output(self.m,self.base)
        workflow.review_submit(self.m,self.base,base_packet(self.m,self.base))
        workflow.review_prepare(self.m,self.base,job["id"])
        answer = p.read_json(self.base/"review/packets/answers.template.json")
        item = answer["answers"][job["id"]]
        item.update(observation=NOTE,people="none")
        failed = design()
        failed.update(verdict="fail",failure_stage="base")
        failed["checks"]["subject_scale"]["verdict"] = "fail"
        item["explicit"]["visual_design"] = failed
        result = workflow.review_submit(self.m,self.base,expand_todos(self.base,answer)[0])
        self.assertEqual(result["status"],"generation_repair_needed")
        self.assertFalse(job.get("composition_review"))
        self.assertTrue((self.base/job["composition_failure"]["record"]).is_file())

    def test_full_chain_and_images_only_delivery(self):
        from lc_runtime_env import apply_selected_runtime
        from lc_dispatch import reserve, ingest_batch
        from lc_review_sheets import expand_todos
        from lc_delivery import prepare_delivery_directory
        apply_selected_runtime()
        self.m = fixture(self.base,siblings=True)
        self.m["style_contract"] = p.default_style_contract()
        p.prepare(self.m,self.base)
        first = reserve(self.m,self.base)["reservations"]
        self.assertEqual(len(first),1)
        for index in range(2):
            reservation = first[0] if index == 0 else reserve(self.m,self.base)["reservations"][0]
            job_id = reservation["job"]
            job = p.find_by_id(self.m["jobs"],job_id)
            image = Image.new("RGB",(1600,1600),"white")
            ImageDraw.Draw(image).rectangle((896,192,1440,1408),fill="#d62828")
            image.save(self.base/"synthetic.png")
            ingested = ingest_batch(self.m,self.base,[{"job":job_id,"attempt_id":reservation["attempt_id"],"artifact":str(self.base/"synthetic.png")}],reserve_next=False)
            self.assertIn(job_id,ingested["composition_review_required"])
            if index == 0: self.assertEqual(reserve(self.m,self.base)["reservations"],[])
            prepared = c.prepare_review(self.m,self.base,[job_id])
            self.assertEqual(prepared["errors"],[])
            job = p.find_by_id(self.m["jobs"],job_id)
            workflow.review_submit(self.m,self.base,base_packet(self.m,self.base,job))
            workflow.review_prepare(self.m,self.base,job_id)
            answer = p.read_json(self.base/"review/packets/answers.template.json")
            item = answer["answers"][job_id]
            item.update(observation=NOTE+job_id,people="none")
            # Exception-only review must not auto-pass the four design judgments.
            with self.assertRaises(ValueError): expand_todos(self.base,answer)
            item["explicit"]["visual_design"] = design()
            if index == 0:
                typo = copy.deepcopy(answer)
                failed = typo["answers"][job_id]["explicit"]["visual_design"]
                failed.update(verdict="fail",failure_stage="typography")
                failed["checks"]["text_relationship"]["verdict"] = "fail"
                result = workflow.review_submit(self.m,self.base,expand_todos(self.base,typo)[0])
                self.assertEqual(result["status"],"layout_repair_needed")
                job = p.find_by_id(self.m["jobs"],job_id)
                self.assertTrue(c.proof_valid(self.m,job,self.base))
                self.assertEqual(job.get("quality_repairs",0),0)
                self.assertFalse(lc_scheduler.anchor_passed(self.m,self.base))
                job["layout"]["text_groups"][0]["text_color"] = "#151515"
                p.prepare(self.m,self.base,[job_id])
                workflow.review_prepare(self.m,self.base,job_id)
                answer = p.read_json(self.base/"review/packets/answers.template.json")
                answer["answers"][job_id].update(observation=NOTE+job_id,people="none")
                answer["answers"][job_id]["explicit"]["visual_design"] = design()
            packet = expand_todos(self.base,answer)[0]
            result = workflow.review_submit(self.m,self.base,packet)
            self.assertEqual(result["status"],"qa_passed")
            if index == 0:
                self.assertTrue(lc_scheduler.anchor_passed(self.m,self.base))
                self.assertEqual([d["id"] for d in result["dispatch"]],["04_detail"])
        self.assertFalse((self.base/"review/contact_sheet.png").exists())
        self.assertFalse((self.base/"review/micro_detail_contact_sheet.png").exists())
        gate = p.delivery_check(self.m,self.base)
        self.assertTrue(gate["ready"])
        delivered = prepare_delivery_directory(self.m,self.base,delivery_result=gate,manifest_path=self.base/"project_manifest.json")
        self.assertEqual(delivered["image_count"],2)
        self.assertTrue(all(Path(x["path"]).is_file() for x in delivered["images"]))
        self.assertTrue(all(x.suffix in {".jpg",".png"} for x in Path(delivered["output_dir"]).iterdir()))
        self.assertFalse(list(self.base.rglob("*.zip")))
        again = prepare_delivery_directory(self.m,self.base,delivery_result=gate,manifest_path=self.base/"project_manifest.json")
        self.assertEqual(again["images"],delivered["images"])
        manifest=self.base/"project_manifest.json"
        p.write_json(manifest,self.m)
        for _ in range(2):
            result=subprocess.run([sys.executable,"-B",str(p.SCRIPT_DIR/"lc_image_pipeline.py"),
                                   "deliver","--manifest",str(manifest),"--json"],capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            self.assertEqual(json.loads(result.stdout)["image_count"],2)
        self.assertFalse((self.base/"review/contact_sheet.png").exists())
        self.assertFalse((self.base/"review/micro_detail_contact_sheet.png").exists())
        self.assertFalse(list(self.base.rglob("*.zip")))
        # Per-image evidence remains mandatory even though project overviews are gone.
        mobile = self.base/"review/layouts/03_primary_use_case-360.png"
        mobile.unlink()
        with self.assertRaisesRegex(p.PipelineError,"mobile preview"):
            p.delivery_check(self.m,self.base)


if __name__ == "__main__":
    unittest.main()
