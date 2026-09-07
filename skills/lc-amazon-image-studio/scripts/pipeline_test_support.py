"""Synthetic, explicitly marked fixtures for the Studio V3 pipeline regression suite.

These helpers never call an image model. The drawings stand in for known source
photos and generated output in tests; automated fixture verdicts MUST NOT be used
as production visual evidence. Review helpers require the test_fixture marker.
"""
from __future__ import annotations
from copy import deepcopy
from pathlib import Path
from PIL import Image, ImageDraw
import lc_image_pipeline as pipeline
import lc_quality as quality

MAIN_ID = "01_main"
SECONDARY_ID = "02_secondary"
P0_ID = "usb_c_port"
P2_ID = "finish_rib"
SOURCE_ID = "product_front"
SOURCE_BOX = [.2, .1, .6, .8]
PORT_BOX = [.70, .70, .15, .045]
RIB_BOX = [.10, .28, .22, .035]
NOTE = "Known synthetic regression fixture; not a real product photograph or production approval."


def _ensure_fixture(manifest: dict) -> None:
    if manifest.get("test_fixture") is not True:
        raise ValueError("Automatic fixture reviews are forbidden for non-test projects")


def fixture_job(job_id: str, kind: str, mode: str, *, canvas: tuple[int, int] = (1600, 1600)) -> dict:
    secondary = job_id != MAIN_ID
    return {
        "id": job_id, "required": True, "kind": kind,
        "view": "front_oblique" if secondary else "front", "target_view": "front_oblique" if secondary else "front",
        "selling_job": "Show the known test body's port and surface rib", "render_mode": mode,
        "requires_fine_detail": False, "canvas": list(canvas), "source_reference_ids": [SOURCE_ID],
        "target_product_bbox_norm": [.25,.15,.56,.72] if secondary else SOURCE_BOX.copy(),
        "raw_product_bbox_norm": None, "output_product_bbox_norm": None, "detail_output_bbox_norms": {},
        "scene": "neutral test surface" if secondary else "pure white background",
        "composition": "supported front face with camera roll" if secondary else "front centered with all parts visible",
        "lighting": "neutral soft fixture light", "padding_color": "#ffffff",
        "raw_output": f"raw/{job_id}.png", "final_output": f"final/{job_id}.png",
        "layout": {}, "product_layers": [], "text_overlays": [], "status": "pending", "attempts": 0,
        "quality_repairs": 0, "semantic_qa_results": {}, "policy_qa_results": {}, "detail_qa_results": {},
        "ai_disclosure": {"human_source": "unknown", "notes": NOTE}, "export": {},
        "source_assessment": {"scene_fit": "new_view" if secondary else "matched", "degradation": "none",
                              "evidence": "sufficient", "matched_reference_ids": [] if secondary else [SOURCE_ID], "reason": NOTE},
    }


def _detail(detail_id: str, name: str, priority: str, box: list[float]) -> dict:
    return {"id": detail_id, "name": name, "priority": priority, "status": "unknown",
            "evidence_level": "visual_confirmed", "visual_confirmation": "confirmed",
            "component": "front face", "description": "A deliberately drawn, readable feature of the fixture",
            "shape": "horizontal rounded rectangle", "orientation": "horizontal", "color": "dark grey",
            "locations": [{"reference_id": SOURCE_ID, "view": "front", "bbox_in_product_norm": box.copy(),
                           "visual_confirmation": "confirmed", "position_description": "known fixture coordinates"}],
            "visibility": {MAIN_ID: "required", SECONDARY_ID: "required"}}


def create_v3_fixture(base: Path, *, canvas: tuple[int, int] = (1600,1600)) -> dict:
    """Write known source raster/mask and return an unprepared V3 manifest."""
    base=Path(base).resolve()
    for directory in ("source","raw","final"):(base/directory).mkdir(parents=True,exist_ok=True)
    image=Image.new("RGB",(1600,1600),"white");draw=ImageDraw.Draw(image)
    mask=Image.new("L",image.size,0);md=ImageDraw.Draw(mask)
    bounds=pipeline.normalized_to_pixels(SOURCE_BOX,*image.size)
    draw.rounded_rectangle(bounds,radius=65,fill="#ecefeb",outline="#64736a",width=10)
    md.rounded_rectangle(bounds,radius=65,fill=255)
    for box,color in [(PORT_BOX,"#111915"),(RIB_BOX,"#74897c")]:
        region=pipeline.detail_bbox_in_image(SOURCE_BOX,box)
        draw.rounded_rectangle(pipeline.normalized_to_pixels(region,*image.size),radius=8,fill=color)
    image.save(base/"source/product_front.png");mask.save(base/"source/product_mask.png")
    main=fixture_job(MAIN_ID,"main","pixel_composite",canvas=canvas)
    main["pixel_source_reference_id"]=SOURCE_ID
    main["product_layers"]=[{"reference_id":SOURCE_ID,"asset_path":"source/product_front.png",
                              "mask_path":"source/product_mask.png","crop_bbox_norm":SOURCE_BOX.copy(),
                              "asset_origin":"original","source_reference_ids":[SOURCE_ID]}]
    secondary=fixture_job(SECONDARY_ID,"listing","reference_generate",canvas=canvas)
    manifest={"schema_version":3,"project_id":"fixture-studio-v3","test_fixture":True,"fixture_note":NOTE,
              "marketplace":"US","language":"en","run_mode":"risk_gated_auto","generation_backend":"built_in_image_gen",
              "concurrency":2,"critical_detail_census_completed":True,"max_transient_retries":2,"max_quality_repairs":1,
              "product_truth":{"product":"Synthetic fixture body with exactly one port and one finish rib",
                               "source_quality":"sufficient","master_asset_mode":"original_pixels","master_confirmed":False,
                               "safe_upscale_ratio":1.25,"max_marginal_upscale_ratio":1.75,
                               "geometry_lock":{"locked_structure":["one body, one recessed port, one rib"],"confirmed_dimensions":"15 x 20 cm fixture"},
                               "material_lock":{"materials":["matte opaque grey test material"],"color":"light grey"},
                               "scene_scale_lock":{"physical_dimensions":"15 x 20 cm fixture","support_surface":"flat test surface"}},
              "facts":[{"id":"port_count","text":"Exactly one fixture port","evidence":[SOURCE_ID]}],
              "references":[{"id":SOURCE_ID,"path":"source/product_front.png","role":"whole_product_reference","view":"front",
                             "visual_quality":"sufficient","product_bbox_norm":SOURCE_BOX.copy(),
                             "provenance":{"kind":"real_photo","notes":"Test-only stand-in for an input source photo; "+NOTE},"quality_review":{}}],
              "critical_details":[_detail(P0_ID,"USB-C fixture opening","P0",PORT_BOX),_detail(P2_ID,"Surface fixture rib","P2",RIB_BOX)],
              "jobs":[main,secondary]}
    pipeline.write_json(base/"project_manifest.json",manifest)
    return manifest


def bind_source_reviews(manifest: dict, base: Path) -> None:
    """Refresh actual raster, region, mask and task review bindings for fixture inputs."""
    _ensure_fixture(manifest);base=Path(base).resolve()
    # prepare() also aligns template placement before assessing source context.
    from lc_layout import layout_geometry
    for job in manifest["jobs"]:
        if job.get("layout") and job.get("placement_mode","template")=="template":
            job["target_product_bbox_norm"]=layout_geometry(job)["product_region_norm"]
    quality.assess_sources(manifest,base)
    for ref in manifest["references"]:
        ref["quality_review"]={"clarity":"clear","evidence":"sufficient","defects":[],"notes":NOTE,
                               "reviewed_sha256":ref["sha256"],"reviewed_region_fingerprint":quality.source_region_fingerprint(ref)}
    refs={r["id"]:r for r in manifest["references"]}
    for job in manifest["jobs"]:
        for index,layer in enumerate(job.get("product_layers",[])):
            record=job["layer_asset_hashes"][index]
            source_ids=set([layer["reference_id"]]+layer.get("source_reference_ids",[]))
            layer["source_binding"]={"reviewed":True,"reviewed_asset_sha256":record["asset_sha256"],
                                      "reviewed_mask_sha256":record.get("mask_sha256"),
                                      "source_reference_hashes":{rid:refs[rid]["sha256"] for rid in source_ids}}
        decision=quality.decide_job(manifest,job)
        review=job["source_assessment"]
        review["reviewed_reference_hashes"]=decision["required_reference_hashes"]
        review["reviewed_context_fingerprint"]=decision["assessment_context_fingerprint"]
    quality.assess_sources(manifest,base)


def prepare_fixture(manifest: dict, base: Path) -> None:
    bind_source_reviews(manifest,base)
    pipeline.prepare(manifest,Path(base).resolve())
    problems={job["id"]:job.get("blocked_reason") for job in manifest["jobs"] if job["status"]=="blocked"}
    if problems:raise AssertionError(f"Fixture preparation blocked: {problems}")


def simulate_secondary_output(manifest: dict, base: Path, job_id: str = SECONDARY_ID) -> None:
    """Enter the real generation transition and save a deterministic model stand-in."""
    _ensure_fixture(manifest);base=Path(base).resolve();job=pipeline.find_by_id(manifest["jobs"],job_id)
    if job is None:raise KeyError(job_id)
    pipeline.transition_job(manifest,job_id,"generating","Synthetic regression output; no model called",base)
    width,height=job["canvas"]
    image=Image.new("RGB",(width,height),"#f5f6f2");draw=ImageDraw.Draw(image)
    target=job["target_product_bbox_norm"]
    tx,ty,tw,th=target
    points=[(tx+x*tw,ty+y*th) for x,y in [(3/28,0),(1,1/12),(25/28,1),(0,11/12)]]
    draw.polygon([(round(x*width),round(y*height)) for x,y in points],fill="#ecefeb",outline="#64736a",width=8)
    output_details={P0_ID:pipeline.detail_bbox_in_image(target,[41/56,17/24,9/56,.05]),
                    P2_ID:pipeline.detail_bbox_in_image(target,[19/112,23/72,.25,7/180])}
    for detail_id,color in [(P0_ID,"#111915"),(P2_ID,"#74897c")]:
        draw.rounded_rectangle(pipeline.normalized_to_pixels(output_details[detail_id],width,height),radius=8,fill=color)
    raw=base/job["raw_output"];raw.parent.mkdir(parents=True,exist_ok=True);image.save(raw)
    job["raw_product_bbox_norm"]=target.copy()
    job["fixture_output_detail_boxes"]=output_details
    pipeline.transition_job(manifest,job_id,"generated","Bound synthetic test output",base)


def bind_ai_disclosure(manifest: dict) -> None:
    _ensure_fixture(manifest)
    for job in manifest["jobs"]:
        if not job.get("image_sha256"):raise AssertionError("Run postprocess before binding AI disclosure")
        job["ai_disclosure"]={"human_source":"none","notes":NOTE,"reviewed_image_sha256":job["image_sha256"],
                              "reviewed_visual_fingerprint":job.get("disclosure_visual_fingerprint")}


def bind_output_reviews(manifest: dict, base: Path) -> None:
    """Known fixture-only verdicts; reject production manifests and missing outputs."""
    _ensure_fixture(manifest);base=Path(base).resolve()
    for job in manifest["jobs"]:
        if not (base/job["final_output"]).is_file():raise AssertionError(f"Missing fixture final: {job['id']}")
        job["semantic_qa_results"]={key:{"verdict":"pass","notes":NOTE} for key in ("geometry","material","components","scene_scale","clarity","visual_integrity")}
        job["policy_qa_results"]={key:{"verdict":"pass","notes":NOTE} for key in ("main_product_only","claims","competitor_copy","text_readability","mobile_readability")}
        job["detail_qa_results"]={d["id"]:{"verdict":"pass","notes":NOTE} for d in manifest["critical_details"] if d["visibility"].get(job["id"])=="required"}
        if job.get("new_view"):
            job["detail_output_bbox_norms"]=deepcopy(job.get("fixture_output_detail_boxes",{}))


def finish_fixture(manifest: dict, base: Path, *, delivery: bool=True) -> dict:
    """Create/reuse local stages, bind fixture-only reviews, QA, and optional delivery."""
    _ensure_fixture(manifest);base=Path(base).resolve()
    pipeline.aspect_safe_postprocess(manifest,base)
    bind_ai_disclosure(manifest)
    pipeline.aspect_safe_postprocess(manifest,base)
    bind_output_reviews(manifest,base)
    report=pipeline.quality_assurance(manifest,base)
    if report["summary"]["passed"]!=len(manifest["jobs"]):
        raise AssertionError(f"Fixture did not pass QA: {report}")
    if delivery:
        pipeline.create_final_contact_sheet(manifest,base)
        pipeline.delivery_check(manifest,base)
    pipeline.write_json(base/"project_manifest.json",manifest)
    return report


def ready_fixture(base: Path, *, delivery: bool=True, canvas: tuple[int,int]=(1600,1600)) -> dict:
    """Return a complete QA-passed two-job fixture, with one simulated model attempt."""
    base=Path(base).resolve()
    manifest=create_v3_fixture(base,canvas=canvas)
    prepare_fixture(manifest,base)
    simulate_secondary_output(manifest,base)
    finish_fixture(manifest,base,delivery=delivery)
    return manifest
