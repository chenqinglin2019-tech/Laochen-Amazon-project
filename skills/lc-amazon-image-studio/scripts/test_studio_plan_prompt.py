"""V8 plan validation (copy rules replace the old review) and the one-shot prompt compiler."""
from __future__ import annotations

import copy
import tempfile
import unittest
from pathlib import Path

import studio_catalog
import studio_plan
import studio_project as sp
import studio_prompt
from studio_test_support import product_photo


class PlanFixture(unittest.TestCase):
    def setUp(self):
        import os
        self.temp = tempfile.TemporaryDirectory(prefix="lc-v8-plan-")
        self.addCleanup(self.temp.cleanup)
        base = Path(self.temp.name)
        os.environ["LC_TEMPLATE_LIBRARY_DIR"] = str(base / "library")
        self.dir = base / "proj"
        self.project = sp.create(self.dir, "p1", "US", "en", a_plus_modules="header,feature:1464x600")
        sp.add_photos(self.project, self.dir, [product_photo(base / "front.jpg")])
        self.catalog = studio_catalog.load()
        family = self.catalog["builtin"]["families"][0]
        self.template = next(t["id"] for t in self.catalog["builtin"]["templates"] if t["family_id"] == family["id"])
        self.plan = {"version": 1, "family": family["id"],
                     "product": {"name": "Blue organizer", "look": "Rounded blue box", "facts": ["30 x 20 cm", "3 compartments"]},
                     "slots": {"01_main": {"route": "auto"}}}
        for slot in self.project["slots"][1:]:
            self.plan["slots"][slot["id"]] = {"template": self.template, "message": "Keeps the desk tidy",
                                              "copy": {"headline": "A Tidy Desk"}}

    def check(self, plan):
        return studio_plan.validate(plan, self.project, self.catalog)


class PlanTests(PlanFixture):
    def test_valid_plan_passes(self):
        normalized, errors, _ = self.check(self.plan)
        self.assertEqual(errors, [])
        self.assertEqual(normalized["slots"]["02_size_or_components"]["photos"], ["front"])

    def test_all_problems_are_reported_together(self):
        plan = copy.deepcopy(self.plan)
        plan["slots"]["02_size_or_components"]["copy"] = {"headline": "The Best Seller Desk Organizer Ever Made Now",
                                                          "subline": "Only $19.99, 50 cm wide"}
        plan["slots"]["03_primary_use_case"]["copy"] = {"headline": "Waterproof And FDA Approved"}
        plan["slots"]["01_main"]["copy"] = {"headline": "No"}
        del plan["slots"]["04_compatibility_or_installation"]
        _, errors, _ = self.check(plan)
        codes = {error["code"] for error in errors}
        self.assertTrue({"TOO_LONG", "FORBIDDEN_WORDING", "NUMBER_UNBACKED", "CLAIM_UNBACKED", "MAIN_HAS_COPY",
                         "SLOT_MISSING"} <= codes, codes)

    def test_numbers_backed_by_facts_and_claims_backed_by_facts_pass(self):
        plan = copy.deepcopy(self.plan)
        plan["product"]["facts"].append("Waterproof (IPX7)")
        plan["slots"]["02_size_or_components"]["copy"] = {"headline": "30 x 20 cm", "callouts": ["Waterproof", "3 compartments"]}
        _, errors, _ = self.check(plan)
        self.assertEqual(errors, [])

    def test_wide_a_plus_has_a_tighter_budget_and_script_must_match_language(self):
        plan = copy.deepcopy(self.plan)
        plan["slots"]["09_a_plus_feature"]["copy"] = {"headline": "A Calm And Tidy Desk Today",
                                                      "callouts": ["One", "Two", "Three", "Four"]}
        plan["slots"]["03_primary_use_case"]["copy"] = {"headline": "整洁的桌面"}
        _, errors, _ = self.check(plan)
        where = {(error["path"], error["code"]) for error in errors}
        self.assertIn(("$.slots.09_a_plus_feature.copy.headline", "TOO_LONG"), where)
        self.assertIn(("$.slots.09_a_plus_feature.copy.callouts", "TOO_MANY"), where)
        self.assertIn(("$.slots.03_primary_use_case.copy.headline", "WRONG_SCRIPT"), where)
        self.assertEqual(studio_plan.tier_for([970, 600]), "standard")
        self.assertEqual(studio_plan.tier_for([1464, 600]), "wide")

    def test_unknown_template_and_custom_without_layout(self):
        plan = copy.deepcopy(self.plan)
        plan["slots"]["02_size_or_components"]["template"] = "nope"
        plan["slots"]["03_primary_use_case"] = {"template": "custom", "message": "x", "design": {"style": "warm"}}
        _, errors, _ = self.check(plan)
        codes = {(error["path"].split(".")[2], error["code"]) for error in errors}
        self.assertIn(("02_size_or_components", "TEMPLATE_UNKNOWN"), codes)
        self.assertIn(("03_primary_use_case", "REQUIRED"), codes)


class PromptTests(PlanFixture):
    def test_builtin_template_prompt_is_one_shot_and_quotes_copy(self):
        plan, errors, _ = self.check(self.plan)
        self.assertEqual(errors, [])
        slot = sp.slot(self.project, "03_primary_use_case")
        source, family, template = studio_catalog.resolve(self.catalog, self.template)
        design = studio_prompt.design_from_template(source, family, template, slot)
        prompt, frame = studio_prompt.compile_secondary(self.project, plan, slot, plan["slots"][slot["id"]], design,
                                                       self.project["photos"])
        self.assertIn('1. Headline: "A Tidy Desk"', prompt)
        self.assertIn("render exactly these words", prompt)
        self.assertIn("People: none", prompt)
        for banned in ("base photograph", "no marketing text", "container", "text_mode"):
            self.assertNotIn(banned, prompt)
        self.assertLess(len(prompt), 3600)

    def test_wide_band_words_and_custom_design(self):
        plan, _, _ = self.check(self.plan)
        slot = sp.slot(self.project, "09_a_plus_feature")
        entry = {"template": "custom", "message": "Features", "copy": {"headline": "Built To Last"},
                 "design": {"style": "dark studio", "layout": "product right, text left", "typography": "bold sans"}}
        prompt, frame = studio_prompt.compile_secondary(self.project, plan, slot, entry,
                                                       studio_prompt.design_custom(entry, None), self.project["photos"])
        self.assertIn("from 19% to 81% of the height", prompt)
        self.assertIn("Layout: product right, text left", prompt)
        self.assertEqual(frame["frame"], "3:2")

    def test_every_builtin_template_compiles_without_v7_vocabulary(self):
        """Built-in texts were written for 'base photo now, text later'; none of that may reach a one-shot prompt."""
        import re
        v7 = re.compile(r"\b(approved|evidenc\w*|containers?|protected|local|later|traceable|verified|registered|preview|"
                        r"text_mode|sources?|samples?|current (project|product|evidence|scale)|annotation|documented|"
                        r"base photo\w*|no marketing text|mask\w*)\b", re.I)
        plan, _, _ = self.check(self.plan)
        portrait = sp.create(self.dir.parent / "portrait", "p2", "US", "en", listing_aspect="1:1.3")
        slots = [sp.slot(self.project, "03_primary_use_case"), sp.slot(self.project, "08_a_plus_header"),
                 sp.slot(self.project, "09_a_plus_feature"), sp.slot(portrait, "03_primary_use_case")]
        compiled = 0
        for template in self.catalog["builtin"]["templates"]:
            source, family, record = studio_catalog.resolve(self.catalog, template["id"])
            for slot in slots:
                design = studio_prompt.design_from_template(source, family, record, slot)
                entry = {"template": record["id"], "message": "Keeps the desk tidy", "copy": {"headline": "A Tidy Desk"}}
                prompt, _ = studio_prompt.compile_secondary(self.project, plan, slot, entry, design, self.project["photos"])
                body = "\n".join(line for line in prompt.splitlines()
                                 if not line.startswith(("Image ", "Show the product exactly")))
                self.assertIsNone(v7.search(body), (record["id"], slot["id"], v7.search(body) and v7.search(body).group(0)))
                self.assertIn('"A Tidy Desk"', prompt)
                self.assertNotIn(record["id"], prompt)
                self.assertLess(len(prompt), 3600)
                compiled += 1
        self.assertEqual(compiled, 4 * len(self.catalog["builtin"]["templates"]))

    def test_main_prompt_backdrop_variants(self):
        plan, _, _ = self.check(self.plan)
        slot = sp.slot(self.project, "01_main")
        white, _ = studio_prompt.compile_main(self.project, plan, slot, self.project["photos"], backdrop_hex="#FFFFFF",
                                              backdrop_name="white")
        grey, _ = studio_prompt.compile_main(self.project, plan, slot, self.project["photos"], backdrop_hex="#8C8C8C",
                                             backdrop_name="mid_grey", corrections=["there was a shadow"])
        self.assertIn("#FFFFFF", white)
        self.assertIn("no contact shadow", white)
        self.assertIn("no text", white)
        self.assertIn("#8C8C8C", grey)
        self.assertIn("replaced with pure white afterwards", grey)
        self.assertIn("Correction - the previous attempt had this problem: there was a shadow", grey)


if __name__ == "__main__":
    unittest.main()
