"""User template library in V8: intake -> library -> catalog -> one-shot prompt (style plate last)."""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

import lc_template_intake as intake
import studio_catalog
import studio_project as sp
import studio_prompt
from lc_template_library import Library
from studio_test_support import basic_plan, cli, isolated_env, product_photo


def reference_set(folder):
    folder.mkdir(parents=True, exist_ok=True)
    main = Image.new("RGB", (1200, 1200), (255, 255, 255))
    ImageDraw.Draw(main).rounded_rectangle((380, 200, 820, 1000), 40, fill=(60, 40, 30))
    main.save(folder / "01_main.jpg", quality=92)
    scene = Image.new("RGB", (1200, 1200), (243, 237, 228))
    draw = ImageDraw.Draw(scene)
    draw.rounded_rectangle((640, 300, 1080, 1100), 40, fill=(150, 90, 50))
    for x in range(80, 560, 34):
        draw.rectangle((x, 90, x + 22, 150), fill=(43, 43, 43))      # stand-in for the sample headline
    scene.save(folder / "02_scene.jpg", quality=92)
    detail = Image.new("RGB", (1200, 1200), (230, 220, 205))
    draw = ImageDraw.Draw(detail)
    draw.ellipse((300, 300, 900, 900), fill=(120, 70, 40))
    draw.rectangle((90, 1040, 520, 1090), fill=(200, 100, 45))
    detail.save(folder / "03_detail.jpg", quality=92)
    return folder


def fill_packet(packet_path):
    packet = json.loads(Path(packet_path).read_text(encoding="utf-8"))
    roles = {1: ("main", "none"), 2: ("primary_use_case", "photo_overlay"), 3: ("material_or_detail", "detail_callouts")}
    boxes = {1: [0.31, 0.16, 0.38, 0.68], 2: [0.52, 0.24, 0.39, 0.70], 3: [0.24, 0.24, 0.52, 0.52]}
    for entry in packet["images"]:
        role, recipe = roles[entry["index"]]
        entry.update(slot_role=role, recipe=recipe, observation="A sample product on a warm studio set.",
                     product_bbox_norm=boxes[entry["index"]])
        entry["generation"].update(background="warm cream paper sweep", lighting="soft window light from the left",
                                   camera="eye level, 50 mm", shadow="soft contact shadow", mood="calm and warm")
        if entry["index"] == 2:
            entry["generation"].update(props="ceramic bowls, linen napkins", surface="rustic walnut table")
            entry["text_boxes_norm"] = [[0.06, 0.06, 0.42, 0.08]]
            entry["layout"]["text_groups"] = [{"id": "headline", "role": "headline", "box": [0.06, 0.06, 0.42, 0.08],
                                               "align": "left", "font_role": "display", "size": 30, "color_role": "ink",
                                               "case": "uppercase"}]
            entry["layout"]["product_region_norm"] = boxes[2]
        if entry["index"] == 3:
            entry["text_boxes_norm"] = [[0.07, 0.86, 0.36, 0.06]]
    packet["family"].update(name="Warm Oak Kitchen", description="Warm cream studio sets with bold uppercase headlines.",
                            product_profile={"categories": ["kitchen_dining"], "attributes": {"material": ["wood"]}})
    packet["family"]["tokens"]["palette"] = {"background": "#F3EDE4", "ink": "#2B2B2B", "accent": "#C8642D"}
    packet["family"]["tokens"]["palette_names"] = {"accent": "burnt orange"}
    packet["family"]["tokens"]["fonts"] = {"display": {"face": "montserrat", "weight": 700},
                                           "text": {"face": "noto_sans", "weight": 400},
                                           "label": {"face": "noto_sans", "weight": 600}}
    packet["family"]["tokens"]["photography"] = {"look": "warm natural daylight"}
    packet["review"] = {"visual_reviewed": True, "notes": "synthetic test set"}
    Path(packet_path).write_text(json.dumps(packet), encoding="utf-8")
    return packet


class LibraryFixture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="lc-v8-lib-")
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.library = Library(self.base / "library")
        self.project_dir = self.base / "proj"
        self.project = sp.create(self.project_dir, "lib", "US", "en")

    def import_set(self):
        prepared = intake.prepare([reference_set(self.base / "refs")], set_name="Warm Oak", library=self.library)
        self.assertEqual(prepared["images"], 3)
        self.assertTrue(Path(prepared["contact_sheet"]).is_file())
        fill_packet(prepared["packet"])
        return prepared, intake.submit(prepared["packet"], library=self.library, project_dir=self.project_dir)


class TemplateLibraryFlowTests(LibraryFixture):
    def test_intake_imports_family_with_neutralized_plates_and_prefers_it_for_the_project(self):
        prepared, result = self.import_set()
        family_id = result["family"]
        self.assertEqual(len(result["templates"]), 3)
        self.assertTrue(all(metric["edge_energy_ratio"] <= metric["limit"] for plate in result["plates"]
                            for metric in plate["metrics"]))
        document = self.library.load_v2()
        self.assertEqual([family["id"] for family in document["families"]], [family_id])
        for template in document["templates"]:
            for key in ("plate_sha256", "thumb_sha256", "reference_sha256"):
                self.assertTrue(self.library.asset_path(template["assets"][key]).is_file())
        project = sp.load(self.project_dir)
        self.assertEqual(project["preferred_families"], [family_id])
        again = intake.prepare([self.base / "refs"], library=self.library)
        self.assertEqual(sorted(again["duplicates"]), [1, 2, 3])

    def test_rejected_packet_lists_every_problem(self):
        prepared = intake.prepare([reference_set(self.base / "refs")], library=self.library)
        packet = fill_packet(prepared["packet"])
        packet["review"]["visual_reviewed"] = False
        packet["images"][1]["observation"] = "一个产品"
        packet["family"]["tokens"]["palette"]["ink"] = "black"
        Path(prepared["packet"]).write_text(json.dumps(packet), encoding="utf-8")
        with self.assertRaises(intake.IntakeError) as raised:
            intake.submit(prepared["packet"], library=self.library)
        message = str(raised.exception)
        for fragment in ("visual_reviewed", "English", "#RRGGBB"):
            self.assertIn(fragment, message)
        self.assertEqual(self.library.load_v2()["families"], [])

    def test_catalog_lists_the_preferred_user_family_first_with_a_contact_sheet(self):
        _, result = self.import_set()
        catalog = studio_catalog.load(self.library.root)
        compact = studio_catalog.compact(catalog, sp.load(self.project_dir), self.project_dir)
        first = compact["families"][0]
        self.assertEqual((first["id"], first["source"], first["preferred"]), (result["family"], "user", True))
        self.assertEqual(first["palette"]["accent"], "#C8642D")
        self.assertTrue(Path(compact["contact_sheet"]).is_file())
        self.assertTrue(all(row["tile"] for row in first["templates"]))
        self.assertLess(len(json.dumps(compact, ensure_ascii=False)), 20000)
        detail = studio_catalog.family_detail(catalog, result["family"])
        self.assertTrue(all("observation" not in template for template in detail["templates"]))

    def test_user_template_prompt_uses_tokens_and_text_groups_never_the_observation(self):
        _, result = self.import_set()
        catalog = studio_catalog.load(self.library.root)
        template_id = next(t for t in result["templates"] if "primary-use-case" in t)
        source, family, template = studio_catalog.resolve(catalog, template_id)
        self.assertEqual(source, "user")
        slot = sp.slot(self.project, "03_primary_use_case")
        design = studio_prompt.design_from_template(source, family, template, slot)
        plan = {"product": {"name": "Oak board", "look": "Rectangular oak cutting board", "facts": []}, "people": False}
        entry = {"template": template_id, "message": "Cut and serve", "copy": {"headline": "Cut And Serve"}}
        prompt, _ = studio_prompt.compile_secondary(self.project, plan, slot, entry, design, [{"view": "front"}],
                                                    "design/plates/x.jpg")
        self.assertIn("#F3EDE4", prompt)
        self.assertIn("burnt orange", prompt)
        self.assertIn('"Cut And Serve"', prompt)
        self.assertIn("colour #2B2B2B", prompt)
        self.assertNotIn("A sample product on a warm studio set", prompt)
        inputs = [line for line in prompt.splitlines() if line.startswith("Image ")]
        self.assertIn("colour and light reference only", inputs[-1])
        self.assertIn("invent your own setting, objects and people", inputs[-1])
        for scene_word in ("Background:", "Props:", "Surface:", "cream paper sweep"):
            self.assertNotIn(scene_word, prompt)

    def test_one_revision_per_project(self):
        _, result = self.import_set()
        template_id = result["templates"][1]
        revised = intake.revise(self.project_dir, template_id, {"tokens": {"palette": {"background": "#FFFFFF",
                                                                                        "ink": "#111111",
                                                                                        "accent": "#C8642D"}}},
                                library=self.library)
        self.assertEqual(revised["revision"], 2)
        with self.assertRaises(intake.IntakeError):
            intake.revise(self.project_dir, template_id, {"layout": {}}, library=self.library)

    def test_builtin_switch_and_export_import_round_trip(self):
        _, result = self.import_set()
        self.library.set_builtin(False)
        catalog = studio_catalog.load(self.library.root)
        self.assertEqual(catalog["builtin"]["families"], [])
        archive = self.base / "library.zip"
        self.library.export(archive)
        other = Library(self.base / "other")
        other.import_archive(archive)
        self.assertEqual([family["id"] for family in other.load_v2()["families"]], [result["family"]])
        self.library.set_builtin(True)
        self.assertTrue(studio_catalog.load(self.library.root)["builtin"]["families"])


class NoCopyTemplateTests(LibraryFixture):
    """V8.1: a user template lends layout, typography and (opt-in) tone and light - never people or scene."""

    def plan_for(self, template_id, **slot):
        import studio_plan
        with sp.locked(self.project_dir) as project:
            sp.add_photos(project, self.project_dir, [product_photo(self.base / "front.jpg", size=1200)])
        self.project = sp.load(self.project_dir)
        catalog = studio_catalog.load(self.library.root)
        plan = {"version": 1, "product": {"name": "Oak board", "look": "Rectangular oak cutting board", "facts": []},
                "slots": {"01_main": {"route": "auto"}}}
        for record in self.project["slots"][1:]:
            plan["slots"][record["id"]] = {"skip": True}
        plan["slots"]["03_primary_use_case"] = {"template": template_id, "message": "Cut and serve",
                                                "copy": {"headline": "Cut And Serve"}, **slot}
        return studio_plan.validate(plan, self.project, catalog)

    def test_scene_is_required_and_a_copied_scene_is_flagged(self):
        _, result = self.import_set()
        template_id = next(t for t in result["templates"] if "primary-use-case" in t)
        _, errors, _ = self.plan_for(template_id)
        self.assertIn("SCENE_REQUIRED", {error["code"] for error in errors})
        _, errors, warnings = self.plan_for(template_id, scene="cream paper sweep, ceramic bowls and linen napkins on a rustic walnut table")
        self.assertEqual(errors, [])
        self.assertIn("SCENE_LIKE_REFERENCE", {warning["code"] for warning in warnings})
        normalized, errors, warnings = self.plan_for(template_id, scene="a sunlit oak worktop with fresh herbs", tone_ref="template")
        self.assertEqual((errors, warnings), ([], []))
        self.assertEqual(normalized["slots"]["03_primary_use_case"]["tone_ref"]["kind"], "plate")

    def test_people_are_flattened_out_and_never_described_by_appearance(self):
        prepared = intake.prepare([reference_set(self.base / "refs")], library=self.library)
        packet = fill_packet(prepared["packet"])
        self.assertEqual(packet["images"][1]["person_boxes_norm"], [])
        packet["images"][1]["generation"]["mood"] = "a young blonde woman laughing"
        Path(prepared["packet"]).write_text(json.dumps(packet), encoding="utf-8")
        with self.assertRaises(intake.IntakeError) as raised:
            intake.submit(prepared["packet"], library=self.library)
        self.assertIn("never by appearance", str(raised.exception))
        packet["images"][1]["generation"]["mood"] = "adult model, waist-up, holding the product; calm and warm"
        packet["images"][1]["person_boxes_norm"] = [[0.06, 0.2, 0.3, 0.7]]
        Path(prepared["packet"]).write_text(json.dumps(packet), encoding="utf-8")
        result = intake.submit(prepared["packet"], library=self.library)
        person = [metric for plate in result["plates"] for metric in plate["metrics"] if metric["kind"] == "person"]
        self.assertEqual(len(person), 1)
        self.assertLessEqual(person[0]["edge_energy_ratio"], person[0]["limit"])

    def test_without_tone_ref_only_product_photos_are_attached_and_detail_hides_the_scene(self):
        _, result = self.import_set()
        catalog = studio_catalog.load(self.library.root)
        detail = studio_catalog.family_detail(catalog, result["family"])
        for template in detail["templates"]:
            self.assertFalse({"background", "props", "surface"} & set(template["generation"]))
        self.assertTrue(any("background" in (t.get("generation") or {}) for t in catalog["user"]["templates"]))  # catalog untouched


class StylePlateTests(unittest.TestCase):
    def test_plate_flattens_product_and_text_but_keeps_the_scene_colour(self):
        from lc_style_plate import make_plate
        image = Image.new("RGB", (900, 900), (240, 230, 215))
        draw = ImageDraw.Draw(image)
        draw.rectangle((450, 200, 800, 800), fill=(20, 20, 20))
        for x in range(60, 400, 26):
            draw.rectangle((x, 60, x + 14, 110), fill=(10, 10, 10))
        plate, metrics = make_plate(image, [0.5, 0.22, 0.39, 0.67], [[0.06, 0.06, 0.4, 0.07]])
        self.assertTrue(all(metric["edge_energy_ratio"] <= metric["limit"] for metric in metrics))
        array = np.asarray(plate, dtype=np.float32)
        self.assertLess(np.abs(array[500, 620] - [240, 230, 215]).max(), 40)
        self.assertLess(np.abs(array[85, 200] - [240, 230, 215]).max(), 40)


class CliIntegrationTests(unittest.TestCase):
    def test_plan_attaches_only_a_tone_board_last_for_a_user_template(self):
        with tempfile.TemporaryDirectory(prefix="lc-v8-libcli-") as temp:
            base = Path(temp)
            env = isolated_env(base)
            library = Library(Path(env["LC_TEMPLATE_LIBRARY_DIR"]))
            proj = base / "proj"
            code, init = cli(env, "init", "--project-dir", proj, "--project-id", "lib", "--marketplace", "US",
                             "--language", "en", "--photos", product_photo(base / "front.jpg"), "--no-catalog")
            self.assertEqual(code, 0, init)
            prepared = intake.prepare([reference_set(base / "refs")], library=library)
            fill_packet(prepared["packet"])
            result = intake.submit(prepared["packet"], library=library, project_dir=proj)
            code, catalog = cli(env, "templates", "--project", proj)
            self.assertEqual(code, 0, catalog)
            self.assertEqual(catalog["families"][0]["id"], result["family"])
            template_id = next(t for t in result["templates"] if "primary-use-case" in t)
            slots = sp.load(proj)["slots"]
            plan = basic_plan(catalog, slots, skip={s["id"] for s in slots if s["id"] not in {"01_main", "03_primary_use_case"}})
            plan["family"] = result["family"]
            plan["slots"]["03_primary_use_case"].update(template=template_id, scene="a sunlit oak worktop with fresh herbs",
                                                        tone_ref="template")
            (proj / "plan.json").write_text(json.dumps(plan), encoding="utf-8")
            code, planned = cli(env, "plan", "--project", proj)
            self.assertEqual(code, 0, planned)
            reservation = next(r for r in planned["reservations"] if r["job"] == "03_primary_use_case")
            import lc_style_plate
            self.assertTrue(reservation["references"][-1].endswith(f"-t{lc_style_plate.TONE_VERSION}.jpg"))
            self.assertIn("Main colours of that reference", reservation["prompt"])
            self.assertIn("tones", reservation["references"][-1])
            self.assertTrue(os.path.isabs(reservation["references"][-1]))
            self.assertIn("colour and light reference only", reservation["prompt"])
            self.assertFalse(list((proj / "design").rglob("plates/*")))


if __name__ == "__main__":
    unittest.main()
