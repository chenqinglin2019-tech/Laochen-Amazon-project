"""V8.1 no-copy rules: tone boards, hidden photo areas, newly cast model, same person across the set."""
from __future__ import annotations

import copy
import io
import json
import os
import tempfile
import unittest
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

import lc_style_plate
import studio_catalog
import studio_plan
import studio_project as sp
import studio_prompt
from studio_test_support import basic_plan, cli, fake_model_image, isolated_env, product_photo


def png_bytes(image):
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


class ToneBoardTests(unittest.TestCase):
    def setUp(self):
        self.base = Image.new("RGB", (1536, 1024), (180, 170, 160))

    def test_detail_with_the_same_average_colour_disappears(self):
        detailed = self.base.copy()
        draw = ImageDraw.Draw(detailed)
        for x in range(600, 760, 8):            # a "face"-sized patch of fine structure
            for y in range(300, 460, 8):
                draw.rectangle((x, y, x + 3, y + 3), fill=(40, 30, 20))
        mean = np.asarray(detailed.crop((600, 300, 760, 460))).reshape(-1, 3).mean(0)
        flat = self.base.copy()
        ImageDraw.Draw(flat).rectangle((600, 300, 760, 460), fill=tuple(int(v) for v in mean))
        a = np.asarray(lc_style_plate.make_tone_board(detailed), float)
        b = np.asarray(lc_style_plate.make_tone_board(flat), float)
        self.assertLessEqual(np.abs(a - b).max(), 2.0)
        self.assertEqual(max(lc_style_plate.make_tone_board(detailed).size), lc_style_plate.TONE_LONG_EDGE)

    def test_palette_and_light_direction_survive_and_the_board_is_smooth(self):
        gradient = np.tile(np.linspace(230, 60, 1536)[None, :, None], (1024, 1, 3)).astype(np.uint8)
        board = np.asarray(lc_style_plate.make_tone_board(Image.fromarray(gradient)), float)
        self.assertGreater(board[:, :40].mean() - board[:, -40:].mean(), 0.5 * 170)
        self.assertLess(abs(board.mean() - gradient.mean()), 8)
        checker = Image.new("RGB", (1536, 1024))
        draw = ImageDraw.Draw(checker)
        for i in range(4):
            for j in range(3):
                draw.rectangle((i * 384, j * 341, i * 384 + 383, j * 341 + 340),
                               fill=(240, 240, 240) if (i + j) % 2 else (20, 20, 20))
        smooth = np.asarray(lc_style_plate.make_tone_board(checker), float)
        self.assertLessEqual(max(np.abs(np.diff(smooth, axis=0)).max(), np.abs(np.diff(smooth, axis=1)).max()), 4)

    def test_a_person_in_the_reference_leaves_no_blob(self):
        wall = Image.new("RGB", (1200, 1200), (236, 226, 210))
        ImageDraw.Draw(wall).rectangle((0, 820, 1200, 1200), fill=(170, 130, 95))
        person = wall.copy()
        draw = ImageDraw.Draw(person)
        draw.ellipse((330, 250, 470, 410), fill=(225, 180, 150))
        draw.pieslice((310, 220, 490, 420), 180, 360, fill=(240, 205, 120))
        draw.polygon([(320, 420), (480, 420), (520, 820), (280, 820)], fill=(200, 60, 70))
        with_person = np.asarray(lc_style_plate.make_tone_board(person), float)
        without = np.asarray(lc_style_plate.make_tone_board(wall), float)
        self.assertLess(np.abs(with_person - without).mean(), 4)
        # no local red patch where the dress was: its region looks like the board around it
        board = with_person
        region = board[int(0.35 * board.shape[0]):int(0.65 * board.shape[0]), int(0.25 * board.shape[1]):int(0.42 * board.shape[1])]
        around = board[int(0.35 * board.shape[0]):int(0.65 * board.shape[0]), int(0.6 * board.shape[1]):int(0.8 * board.shape[1])]
        self.assertLess(abs((region[..., 0] - region[..., 1]).mean() - (around[..., 0] - around[..., 1]).mean()), 6)
        self.assertIn("#C54349", lc_style_plate.main_colours(person))      # the colour survives only as a word

    def test_deterministic(self):
        self.assertEqual(png_bytes(lc_style_plate.make_tone_board(self.base)), png_bytes(lc_style_plate.make_tone_board(self.base)))


class NeutralizeTests(unittest.TestCase):
    def scene(self):
        image = Image.new("RGB", (900, 900), (235, 225, 210))
        draw = ImageDraw.Draw(image)
        draw.ellipse((120, 150, 300, 330), fill=(200, 150, 120))      # a head
        draw.rectangle((140, 330, 280, 800), fill=(30, 60, 160))       # a body
        draw.rectangle((500, 300, 800, 800), fill=(20, 20, 20))        # the product
        return image

    def test_person_boxes_are_flattened_out_of_the_plate(self):
        plate, metrics = lc_style_plate.make_plate(self.scene(), [0.54, 0.32, 0.36, 0.58], person_boxes=[[0.12, 0.15, 0.22, 0.75]])
        person = next(metric for metric in metrics if metric["kind"] == "person")
        self.assertLessEqual(person["edge_energy_ratio"], person["limit"])
        self.assertLess(np.abs(np.asarray(plate, float)[400, 210] - [235, 225, 210]).max(), 40)   # body gone
        same, _ = lc_style_plate.make_plate(self.scene(), [0.54, 0.32, 0.36, 0.58])
        again, _ = lc_style_plate.make_plate(self.scene(), [0.54, 0.32, 0.36, 0.58], person_boxes=())
        self.assertEqual(png_bytes(same), png_bytes(again))

    def test_hide_regions_changes_only_pixels_inside_its_boxes(self):
        image = self.scene()
        hidden, metrics = lc_style_plate.hide_regions(image, [[0.12, 0.15, 0.22, 0.75]], expand=0.0)
        changed = (np.asarray(hidden, int) != np.asarray(image, int)).any(axis=2)
        ys, xs = np.nonzero(changed)
        self.assertGreaterEqual(xs.min(), int(0.12 * 900) - 1)
        self.assertLessEqual(xs.max(), int(0.34 * 900) + 1)
        self.assertLess(metrics[0]["edge_energy_ratio"], 0.2)


class Fixture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="lc-v81-")
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        os.environ["LC_TEMPLATE_LIBRARY_DIR"] = str(self.base / "library")
        self.dir = self.base / "proj"
        self.project = sp.create(self.dir, "nc", "US", "en")
        sp.add_photos(self.project, self.dir, [product_photo(self.base / "front.jpg", size=1200)])
        self.catalog = studio_catalog.load()
        family = self.catalog["builtin"]["families"][0]
        self.template = next(t["id"] for t in self.catalog["builtin"]["templates"] if t["family_id"] == family["id"])
        self.plan = {"version": 1, "family": family["id"],
                     "product": {"name": "Tote bag", "look": "Natural canvas tote with leather handles", "facts": []},
                     "slots": {"01_main": {"route": "auto"}}}
        for slot in self.project["slots"][1:]:
            self.plan["slots"][slot["id"]] = {"template": self.template, "message": "Carries the day", "copy": {"headline": "Carry More"}}

    def codes(self, plan):
        _, errors, warnings = studio_plan.validate(plan, self.project, self.catalog)
        return {(error["path"], error["code"]) for error in errors}, {(item["path"], item["code"]) for item in warnings}


class PlanValidationTests(Fixture):
    def test_cast_is_required_for_a_person_but_not_for_hands(self):
        plan = copy.deepcopy(self.plan)
        plan["slots"]["03_primary_use_case"]["people"] = "person"
        errors, _ = self.codes(plan)
        self.assertIn(("$.cast", "CAST_REQUIRED"), errors)
        plan["slots"]["03_primary_use_case"]["people"] = "hands"
        errors, _ = self.codes(plan)
        self.assertNotIn(("$.cast", "CAST_REQUIRED"), errors)
        plan["cast"] = "Woman in her 30s, short curly black hair, warm brown skin, linen shirt"
        errors, warnings = self.codes(plan)
        self.assertEqual(errors, set())
        self.assertIn(("$.cast", "CAST_UNUSED"), warnings)

    def test_copy_wording_real_people_english_and_anchor(self):
        plan = copy.deepcopy(self.plan)
        plan["slots"]["03_primary_use_case"].update(people="person", scene="the same kitchen as the reference image",
                                                    direction="like the template")
        plan["cast"] = "looks like a famous actress"
        plan["cast_anchor"] = "04_compatibility_or_installation"
        plan["style"] = "copy the competitor look"
        errors, _ = self.codes(plan)
        for path in ("$.slots.03_primary_use_case.scene", "$.slots.03_primary_use_case.direction", "$.cast", "$.style"):
            self.assertIn((path, "COPY_WORDING"), errors)
        self.assertIn(("$.cast_anchor", "CAST_ANCHOR_INVALID"), errors)
        plan["cast"] = "三十岁的女性"
        errors, _ = self.codes(plan)
        self.assertIn(("$.cast", "ENGLISH_REQUIRED"), errors)
        harmless = copy.deepcopy(self.plan)
        harmless["slots"]["03_primary_use_case"]["scene"] = "dinner plates on an oak table, a coin for scale reference"
        self.assertEqual(self.codes(harmless)[0], set())

    def test_tone_ref_rules(self):
        plan = copy.deepcopy(self.plan)
        plan["slots"]["03_primary_use_case"]["tone_ref"] = "template"           # built-in template: nothing to borrow
        plan["slots"]["04_compatibility_or_installation"]["tone_ref"] = "ref9"
        plan["slots"]["05_material_or_detail"]["tone_ref"] = 3
        plan["slots"]["01_main"]["tone_ref"] = "ref1"
        errors, _ = self.codes(plan)
        self.assertIn(("$.slots.03_primary_use_case.tone_ref", "TONE_REF_UNAVAILABLE"), errors)
        self.assertIn(("$.slots.04_compatibility_or_installation.tone_ref", "TONE_REF_UNKNOWN"), errors)
        self.assertIn(("$.slots.05_material_or_detail.tone_ref", "TYPE"), errors)
        self.assertIn(("$.slots.01_main.tone_ref", "UNKNOWN_KEY"), errors)

    def test_hide_rules(self):
        plan = copy.deepcopy(self.plan)
        plan["hide"] = {"nope": [[0, 0, 0.1, 0.1]], "front": [[0.1, 0.1, 2, 0.1]] + [[0.1, 0.1, 0.1, 0.1]] * 9}
        errors, _ = self.codes(plan)
        self.assertIn(("$.hide.nope", "PHOTO_UNKNOWN"), errors)
        self.assertIn(("$.hide.front", "TOO_MANY"), errors)
        self.assertIn(("$.hide.front[0]", "BOX_INVALID"), errors)
        plan["hide"] = {"front": [[0, 0, 0.9, 0.9]]}
        errors, warnings = self.codes(plan)
        self.assertEqual(errors, set())
        self.assertIn(("$.hide.front", "PHOTO_MOSTLY_HIDDEN"), warnings)


class PromptTests(Fixture):
    def test_people_lines(self):
        cast = "Man in his 40s, short grey hair, light skin, navy overshirt"
        line = studio_prompt.people_line("person", cast, True)
        self.assertIn(cast, line)
        self.assertIn("never a person from the product photos or the colour reference", line)
        self.assertIn("nor any real or famous person", line)
        self.assertIn("consistent with this set's model", studio_prompt.people_line("hands", cast))
        self.assertTrue(studio_prompt.people_line(False, cast).startswith("People: none"))

    def test_secondary_prompt_product_only_hidden_tone_and_identity(self):
        plan, _, _ = studio_plan.validate(self.plan, self.project, self.catalog)
        plan["cast"] = "Woman in her 30s, short curly black hair"
        slot = sp.slot(self.project, "03_primary_use_case")
        source, family, template = studio_catalog.resolve(self.catalog, self.template)
        design = studio_prompt.design_from_template(source, family, template, slot)
        entry = dict(plan["slots"][slot["id"]], people="person")
        photo = dict(self.project["photos"][0], hidden=True)
        prompt, _ = studio_prompt.compile_secondary(self.project, plan, slot, entry, design, [photo], "design/tones/x-t1.jpg")
        self.assertIn(studio_prompt.PRODUCT_ONLY, prompt)
        self.assertIn("Blurred patches in it hide a person", prompt)
        self.assertIn("Image 2 - colour and light reference only", prompt)
        self.assertIn("Avoid: brands, text, claims, people or settings from the product photos or the colour reference", prompt)
        self.assertNotIn("mask", prompt.lower())
        with_model = studio_prompt.with_identity(prompt, 3)
        self.assertEqual(with_model.count("Image 3 - this set's model"), 1)
        lines = with_model.splitlines()
        self.assertEqual(lines.index(studio_prompt.PRODUCT_ONLY) - 1,
                         next(i for i, line in enumerate(lines) if line.startswith("Image 3")))
        self.assertEqual(studio_prompt.with_identity(with_model, 3), with_model)

    def test_the_agents_scene_replaces_the_templates_background(self):
        plan, _, _ = studio_plan.validate(self.plan, self.project, self.catalog)
        slot = sp.slot(self.project, "03_primary_use_case")
        source, family, template = studio_catalog.resolve(self.catalog, self.template)
        design = studio_prompt.design_from_template(source, family, template, slot)
        background = design["background"]
        self.assertTrue(background)
        with_scene, _ = studio_prompt.compile_secondary(self.project, plan, slot, dict(plan["slots"][slot["id"]], scene="a hallway"),
                                                        design, self.project["photos"])
        without, _ = studio_prompt.compile_secondary(self.project, plan, slot, plan["slots"][slot["id"]], design, self.project["photos"])
        self.assertNotIn(background.rstrip("."), with_scene)
        self.assertIn("Scene: a hallway", with_scene)
        self.assertIn(background.rstrip("."), without)

    def test_main_prompt_ignores_people_in_photos(self):
        plan, _, _ = studio_plan.validate(self.plan, self.project, self.catalog)
        photo = dict(self.project["photos"][0], hidden=True)
        main, _ = studio_prompt.compile_main(self.project, plan, sp.slot(self.project, "01_main"), [photo],
                                             backdrop_hex="#FFFFFF", backdrop_name="white")
        self.assertIn(studio_prompt.PRODUCT_ONLY, main)
        self.assertIn("Blurred patches in it hide a person", main)

    def test_user_template_look_keeps_only_tone_and_light(self):
        family = {"id": "u", "tokens": {"palette": {"background": "#F3EDE4"}, "photography": {"look": "a smiling woman, warm daylight"}}}
        template = {"id": "u-x", "observed_shape": "square", "recipe": "photo_overlay", "layout": {},
                    "generation": {"background": "white marble kitchen", "props": "ceramic mug", "surface": "marble",
                                   "lighting": "soft window light, a mother serves breakfast", "mood": "calm and warm"}}
        design = studio_prompt.design_from_template("user", family, template, sp.slot(self.project, "03_primary_use_case"))
        look = " ".join(design["look"])
        for word in ("marble", "mug", "mother", "woman"):
            self.assertNotIn(word, look)
        for word in ("#F3EDE4", "soft window light", "calm and warm", "warm daylight"):
            self.assertIn(word, look)
        self.assertEqual(design["scene"], "")


class ModelIdentityTests(unittest.TestCase):
    """State machine with hand-made jobs (no images needed except the identity raw file)."""
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="lc-v81-state-")
        self.addCleanup(self.temp.cleanup)
        self.dir = Path(self.temp.name) / "p"
        self.project = sp.create(self.dir, "s", "US", "en")
        for slot_id in ("02_size_or_components", "03_primary_use_case", "04_compatibility_or_installation", "06_storage_or_package"):
            prompt = self.dir / "prompts" / f"{slot_id}.txt"
            prompt.write_text("Create.\nInput images (in order):\nImage 1 - product photo\n" + studio_prompt.PRODUCT_ONLY + "\nRest\n",
                              encoding="utf-8")
            self.project["jobs"][slot_id] = {"status": "pending", "route": "generate", "attempts": [], "redos": 0,
                                             "prompt_file": f"prompts/{slot_id}.txt", "references": ["source/front.jpg"],
                                             "size": "1024x1024", "aspect": "1:1"}
        sp.update_cast(self.project, "Woman in her 30s", ["03_primary_use_case", "06_storage_or_package"])

    def finish(self, slot_id, attempt_id, pixels=7):
        item = self.project["jobs"][slot_id]
        attempt = next(entry for entry in item["attempts"] if entry["id"] == attempt_id)
        raw = self.dir / "raw" / f"{slot_id}-{attempt_id}.png"
        Image.new("RGB", (64, 64), (pixels, pixels, pixels)).save(raw)
        digest = sp.sha256_file(raw)
        defined = sp.note_identity(self.project, slot_id, item, attempt, sp.rel(raw, self.dir), digest)
        sp.finish_ok(self.project, item, attempt, raw_rel=sp.rel(raw, self.dir), digest=digest, final_rel="final/x.jpg",
                     final_sha="0" * 64, checks={}, warnings=[])
        return defined

    def wave(self, **kwargs):
        return sp.reserve(self.project, self.dir, **kwargs)

    def test_members_wait_for_the_anchor_then_get_the_identity_image(self):
        wave = self.wave()
        jobs = {r["job"]: r for r in wave["reservations"]}
        self.assertEqual(wave["reservations"][0]["job"], "03_primary_use_case")
        self.assertEqual(jobs["03_primary_use_case"]["cast"], "anchor")
        self.assertNotIn("06_storage_or_package", jobs)
        self.assertEqual(wave["waiting_for_model"], ["06_storage_or_package"])
        self.assertTrue(self.finish("03_primary_use_case", jobs["03_primary_use_case"]["attempt_id"]))
        nxt = {r["job"]: r for r in self.wave()["reservations"]}
        member = nxt["06_storage_or_package"]
        self.assertEqual(member["cast"], "same_model")
        self.assertTrue(member["references"][-1].endswith("raw/03_primary_use_case-" + jobs["03_primary_use_case"]["attempt_id"] + ".png"))
        self.assertIn("Image 2 - this set's model", member["prompt"])

    def test_anchor_goes_first_even_with_one_slot(self):
        sp.update_cast(self.project, "Woman in her 30s", ["03_primary_use_case", "06_storage_or_package"], "06_storage_or_package")
        wave = self.wave(max_count=1)
        self.assertEqual([r["job"] for r in wave["reservations"]], ["06_storage_or_package"])

    def test_failover_when_the_anchor_fails_is_persisted(self):
        self.wave()
        sp.reject(self.project, "03_primary_use_case", "unusable")
        wave = self.wave()
        self.assertEqual({r["job"]: r.get("cast") for r in wave["reservations"]}.get("06_storage_or_package"), "anchor")
        self.assertEqual(self.project["cast"]["anchor"], "06_storage_or_package")

    def test_redo_keeps_the_model_and_recast_starts_over(self):
        first = {r["job"]: r for r in self.wave()["reservations"]}
        self.finish("03_primary_use_case", first["03_primary_use_case"]["attempt_id"])
        member = {r["job"]: r for r in self.wave()["reservations"]}["06_storage_or_package"]
        self.finish("06_storage_or_package", member["attempt_id"], pixels=9)
        with self.assertRaises(sp.StudioError) as raised:
            sp.recast(self.project, "06_storage_or_package", "x")
        self.assertIn("RECAST_NOT_ALLOWED", str(raised.exception))
        sp.request_redo(self.project, "03_primary_use_case", "headline misspelled")
        redo = {r["job"]: r for r in self.wave()["reservations"]}["03_primary_use_case"]
        self.assertEqual(redo["cast"], "same_model")                       # same person redrawn
        self.finish("03_primary_use_case", redo["attempt_id"], pixels=11)
        result = sp.recast(self.project, "03_primary_use_case", "too close to someone", user_confirmed=True)
        self.assertEqual(result["made_with_previous_model"], ["06_storage_or_package"])
        self.assertIsNone(self.project["cast"]["identity"])
        again = {r["job"]: r for r in self.wave()["reservations"]}["03_primary_use_case"]
        self.assertEqual(again["cast"], "anchor")
        self.assertNotIn("this set's model", again["prompt"])
        self.assertEqual(sp.model_mismatch(self.project), [])             # no model defined yet in the new epoch
        self.finish("03_primary_use_case", again["attempt_id"], pixels=13)
        self.assertEqual(sp.model_mismatch(self.project), ["06_storage_or_package"])

    def test_a_stale_epoch_result_cannot_define_the_model(self):
        first = {r["job"]: r for r in self.wave()["reservations"]}
        self.project["cast"]["epoch"] += 1                                  # e.g. the cast changed meanwhile
        self.assertFalse(self.finish("03_primary_use_case", first["03_primary_use_case"]["attempt_id"]))
        self.assertIsNone(self.project["cast"]["identity"])

    def test_missing_identity_file_reanchors(self):
        first = {r["job"]: r for r in self.wave()["reservations"]}
        self.finish("03_primary_use_case", first["03_primary_use_case"]["attempt_id"])
        (self.dir / self.project["cast"]["identity"]["path"]).unlink()
        wave = self.wave()
        self.assertIsNone(self.project["cast"]["identity"])
        self.assertEqual({r["job"]: r.get("cast") for r in wave["reservations"]}.get("06_storage_or_package"), "anchor")

    def test_old_style_plate_reference_needs_a_new_plan(self):
        self.project["jobs"]["02_size_or_components"]["references"].append("design/plates/abc.jpg")
        wave = self.wave()
        self.assertTrue(any(r["job"] == "02_size_or_components" and r["reason"].startswith("PLAN_OUTDATED") for r in wave["refusals"]))

    def test_changed_cast_text_clears_the_model(self):
        first = {r["job"]: r for r in self.wave()["reservations"]}
        self.finish("03_primary_use_case", first["03_primary_use_case"]["attempt_id"])
        epoch = self.project["cast"]["epoch"]
        sp.update_cast(self.project, "Man in his 50s", ["03_primary_use_case", "06_storage_or_package"])
        self.assertIsNone(self.project["cast"]["identity"])
        self.assertEqual(self.project["cast"]["epoch"], epoch + 1)


class CliTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="lc-v81-cli-")
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.env = isolated_env(self.base)
        self.proj = self.base / "proj"

    def run_waves(self, result, recast_after=None):
        seen = []
        guard = 0
        while result.get("reservations"):
            guard += 1
            self.assertLess(guard, 10)
            items = []
            for reservation in result["reservations"]:
                seen.append(reservation)
                width, height = map(int, reservation["size"].split("x"))
                path = fake_model_image(self.base / f"{reservation['job']}-{reservation['attempt_id']}.png", (width, height))
                items += ["--item", reservation["job"], reservation["attempt_id"], path]
            code, result = cli(self.env, "ingest-batch", "--project", self.proj, *items)
            self.assertEqual(code, 0, result)
        return seen, result

    def test_one_new_model_for_the_whole_set(self):
        code, init = cli(self.env, "init", "--project-dir", self.proj, "--project-id", "cast", "--marketplace", "US",
                         "--language", "en", "--photos", product_photo(self.base / "front.jpg"))
        plan = basic_plan(init["catalog"], init["slots"], skip={"05_material_or_detail", "07_problem_solution"})
        plan["slots"]["03_primary_use_case"]["people"] = "person"
        plan["slots"]["06_storage_or_package"]["people"] = "person"
        plan["cast"] = "Woman in her 30s, short curly black hair, warm brown skin, linen shirt"
        (self.proj / "plan.json").write_text(json.dumps(plan), encoding="utf-8")
        code, planned = cli(self.env, "plan", "--project", self.proj)
        self.assertEqual(code, 0, planned)
        jobs = [r["job"] for r in planned["reservations"]]
        self.assertEqual(jobs[0], "03_primary_use_case")
        self.assertNotIn("06_storage_or_package", jobs)
        self.assertEqual(planned["waiting_for_model"], ["06_storage_or_package"])
        self.assertIn("Woman in her 30s, short curly black hair", planned["reservations"][0]["prompt"])
        seen, last = self.run_waves(planned)
        member = next(r for r in seen if r["job"] == "06_storage_or_package")
        anchor = next(r for r in seen if r["job"] == "03_primary_use_case")
        self.assertEqual(member["cast"], "same_model")
        self.assertTrue(member["references"][-1].endswith(f"03_primary_use_case-{anchor['attempt_id']}.png"))
        self.assertIn("this set's model", member["prompt"])
        code, delivered = cli(self.env, "deliver", "--project", self.proj)
        self.assertEqual(code, 0, delivered)
        self.assertNotIn("model_mismatch", delivered)
        code, again = cli(self.env, "ingest-batch", "--project", self.proj, "--recast", "03_primary_use_case",
                          "looks like a person we must not copy", "--user-confirmed")
        self.assertEqual(code, 0, again)
        recast = next(r for r in again["results"] if r.get("recast"))
        self.assertEqual(recast["made_with_previous_model"], ["06_storage_or_package"])
        self.assertEqual([r["job"] for r in again["reservations"]], ["03_primary_use_case"])
        self.assertNotIn("this set's model", again["reservations"][0]["prompt"])

    def test_refs_only_ever_reach_the_model_as_a_tone_board(self):
        ref = self.base / "competitor.jpg"
        image = Image.new("RGB", (1200, 1200), (60, 90, 120))
        ImageDraw.Draw(image).ellipse((400, 200, 700, 500), fill=(220, 180, 150))
        image.save(ref, quality=92)
        front = product_photo(self.base / "front.jpg")
        code, init = cli(self.env, "init", "--project-dir", self.proj, "--project-id", "refs", "--marketplace", "US",
                         "--language", "en", "--photos", front, "--refs", ref)
        self.assertEqual(code, 0, init)
        self.assertEqual([item["id"] for item in init["refs"]["added"]], ["ref1"])
        self.assertTrue(Path(init["refs"]["refs_sheet"]).is_file())
        code, bad = cli(self.env, "add-photos", "--project", self.proj, "--photos", ref)
        self.assertIn("PHOTO_IS_REFERENCE", bad["error"])
        code, bad = cli(self.env, "add-refs", "--project", self.proj, "--refs", front)
        self.assertIn("REF_IS_PRODUCT_PHOTO", bad["error"])
        plan = basic_plan(init["catalog"], init["slots"], skip={s["id"] for s in init["slots"] if s["id"] not in {"01_main", "03_primary_use_case"}})
        plan["slots"]["03_primary_use_case"] = {"template": "custom", "message": "Everyday carry", "scene": "a bright hallway",
                                                "design": {"layout": "product centre, headline top"}, "tone_ref": "ref1",
                                                "copy": {"headline": "Carry More"}}
        (self.proj / "plan.json").write_text(json.dumps(plan), encoding="utf-8")
        code, planned = cli(self.env, "plan", "--project", self.proj)
        self.assertEqual(code, 0, planned)
        reservation = next(r for r in planned["reservations"] if r["job"] == "03_primary_use_case")
        self.assertIn(os.sep + "tones" + os.sep, reservation["references"][-1])
        self.assertTrue(all("refs" + os.sep not in path for r in planned["reservations"] for path in r["references"]))
        board = np.asarray(Image.open(reservation["references"][-1]).convert("L"), float)
        self.assertLess(max(np.abs(np.diff(board, axis=0)).max(), np.abs(np.diff(board, axis=1)).max()), 6)

    def test_hidden_person_in_a_product_photo(self):
        front = self.base / "worn.jpg"
        image = Image.new("RGB", (2400, 2400), (250, 250, 250))
        draw = ImageDraw.Draw(image)
        draw.ellipse((300, 200, 700, 600), fill=(200, 150, 120))                  # a face
        draw.rounded_rectangle((900, 700, 1700, 1900), 60, fill=(40, 90, 160))   # the product
        image.save(front, quality=92)
        code, init = cli(self.env, "init", "--project-dir", self.proj, "--project-id", "hide", "--marketplace", "US",
                         "--language", "en", "--photos", front)
        plan = basic_plan(init["catalog"], init["slots"], skip={s["id"] for s in init["slots"] if s["id"] not in {"01_main", "03_primary_use_case"}})
        plan["hide"] = {"worn": [[0.1, 0.06, 0.2, 0.2]]}
        plan["slots"]["01_main"] = {"route": "photo", "photo": "worn"}
        (self.proj / "plan.json").write_text(json.dumps(plan), encoding="utf-8")
        code, refused = cli(self.env, "plan", "--project", self.proj)
        self.assertEqual(code, 2)
        self.assertIn("MAIN_PHOTO_HIDDEN", json.dumps(refused))
        plan["slots"]["01_main"] = {"route": "auto"}
        (self.proj / "plan.json").write_text(json.dumps(plan), encoding="utf-8")
        code, planned = cli(self.env, "plan", "--project", self.proj)
        self.assertEqual(code, 0, planned)
        self.assertEqual(planned["main"]["route"], "generate")                     # hidden photo never becomes the main
        for reservation in planned["reservations"]:
            self.assertTrue(all("source" + os.sep + "worn" not in path for path in reservation["references"]))
            self.assertIn(os.sep + "hidden" + os.sep, reservation["references"][0])
            self.assertIn("Blurred patches in it hide a person", reservation["prompt"])
        hidden = np.asarray(Image.open(planned["reservations"][0]["references"][0]).convert("L"), float)
        face = hidden[int(0.1 * hidden.shape[0]):int(0.22 * hidden.shape[0]), int(0.14 * hidden.shape[1]):int(0.26 * hidden.shape[1])]
        self.assertLess(face.std(), 12)


if __name__ == "__main__":
    unittest.main()
