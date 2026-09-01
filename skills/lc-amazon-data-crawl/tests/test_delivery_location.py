from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


SKILL_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = SKILL_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import amazon_category_rank_crawler as category


EXPECTED_LOCATIONS = {
    "amazon.com": ("New York", "10001"),
    "amazon.ca": ("Ottawa", "K1P 1J1"),
    "amazon.com.mx": ("Mexico City", "06000"),
    "amazon.co.uk": ("London", "E16 1ZE"),
    "amazon.de": ("Berlin", "10178"),
    "amazon.fr": ("Paris", "75004"),
    "amazon.it": ("Rome", "00186"),
    "amazon.es": ("Madrid", "28014"),
    "amazon.co.jp": ("Tokyo", "100-0001"),
    "amazon.com.au": ("Canberra", "2600"),
    "amazon.in": ("New Delhi", "110001"),
    "amazon.nl": ("Amsterdam", "1011 PN"),
    "amazon.se": ("Stockholm", "111 52"),
    "amazon.pl": ("Warsaw", "00-950"),
    "amazon.ae": ("Abu Dhabi", "00000"),
    "amazon.sa": ("Riyadh", "12211"),
    "amazon.sg": ("Singapore", "179434"),
    "amazon.com.br": ("Brasilia", "70040-010"),
    "amazon.co.za": ("Pretoria", "0002"),
}


class _Body:
    text = ""


class FakeDriver:
    def __init__(
        self,
        url: str,
        header: str = "Deliver to",
        accepted_postals: set[str] | None = None,
        accepted_cities: set[str] | None = None,
    ) -> None:
        self.current_url = url
        self.title = "Amazon"
        self.header = header
        self.accepted_postals = accepted_postals or set()
        self.accepted_cities = accepted_cities or set()
        self.get_calls: list[str] = []
        self.postal_attempts: list[str] = []
        self.city_attempts: list[str] = []

    def get(self, url: str) -> None:
        self.current_url = url
        self.get_calls.append(url)

    def find_element(self, *_args: object, **_kwargs: object) -> _Body:
        return _Body()

    def execute_script(self, script: str, *args: object) -> object:
        if "lc_delivery_snapshot" in script:
            return self.header
        if "lc_delivery_header_snapshot" in script:
            return self.header.replace("Deliver to", "").strip()
        if "lc_delivery_city_header_snapshot" in script:
            return self.header.replace("Deliver to", "").strip()
        if "lc_delivery_open" in script:
            return True
        if "lc_delivery_postal_submit" in script:
            postal = str(args[0])
            self.postal_attempts.append(postal)
            if postal in self.accepted_postals:
                self.header = f"Deliver to {postal}"
                return True
            return False
        if "lc_delivery_city_submit" in script:
            city = str(args[0])
            self.city_attempts.append(city)
            if city in self.accepted_cities:
                self.header = f"Deliver to {city}"
                return True
            return False
        return False


def runtime_for(locations: dict[str, dict[str, str]]) -> SimpleNamespace:
    return SimpleNamespace(
        delivery_location_enabled=True,
        delivery_locations=locations,
        delivery_location_fingerprint=category.delivery_location_fingerprint(True, locations),
        delivery_location_timeout=1,
        manual_pause_timeout=1,
    )


def fast_delivery_patches() -> tuple[object, object, object]:
    attempt = patch.object(
        category,
        "_attempt_delivery_value",
        side_effect=lambda driver, value, _deadline, submitter: submitter(driver, value),
    )
    confirm = patch.object(
        category,
        "_wait_for_delivery_confirmation",
        side_effect=lambda driver, location, _deadline, **_kwargs: category.delivery_location_is_confirmed(driver, location),
    )
    sleep = patch.object(category.time, "sleep")
    return attempt, confirm, sleep


class DeliveryLocationConfigTests(unittest.TestCase):
    def test_bundled_mapping_contains_all_19_exact_values(self) -> None:
        path = SKILL_ROOT / "assets" / "config" / "amazon_delivery_locations.json"
        locations = category.load_delivery_locations(path)
        self.assertEqual(len(locations), 19)
        self.assertEqual(
            {domain: (row["city"], row["postal_code"]) for domain, row in locations.items()},
            EXPECTED_LOCATIONS,
        )
        self.assertEqual(locations["amazon.ae"]["strategy"], "postal_then_city")
        self.assertTrue(all(row["strategy"] == "postal" for domain, row in locations.items() if domain != "amazon.ae"))

    def test_default_config_falls_back_to_bundled_mapping(self) -> None:
        built = category.build_delivery_location_config({})
        self.assertEqual(
            built["delivery_locations_file"],
            SKILL_ROOT / "assets" / "config" / "amazon_delivery_locations.json",
        )
        self.assertEqual(len(built["delivery_locations"]), 19)
        self.assertTrue(built["delivery_location_enabled"])
        self.assertEqual(built["delivery_location_timeout"], 20)

    def test_all_five_crawler_templates_enable_delivery(self) -> None:
        names = [
            "amazon_front_bsr_category.json",
            "amazon_front_keyword_search.json",
            "amazon_front_storefront.json",
            "amazon_image_competitors.json",
            "category_rank_crawler.json",
        ]
        for name in names:
            raw = json.loads((SKILL_ROOT / "assets" / "config" / name).read_text(encoding="utf-8"))
            self.assertTrue(raw["delivery_location_enabled"], name)
            self.assertEqual(raw["delivery_locations_file"], "config/amazon_delivery_locations.json", name)
            self.assertEqual(raw["delivery_location_timeout"], 20, name)

    def test_image_crawler_has_no_unwrapped_business_navigation(self) -> None:
        source = (
            SKILL_ROOT / "scripts" / "amazon_image_competitor_crawler.py"
        ).read_text(encoding="utf-8")
        self.assertNotIn("driver.get(", source)

    def test_postal_candidates_preserve_original_and_add_compact_retry(self) -> None:
        self.assertEqual(category.delivery_postal_candidates("K1P 1J1"), ["K1P 1J1", "K1P1J1"])
        self.assertEqual(category.delivery_postal_candidates("100-0001"), ["100-0001", "1000001"])
        self.assertEqual(category.delivery_postal_candidates("00186"), ["00186"])

    def test_normalized_delivery_match_rejects_longer_alphanumeric_values(self) -> None:
        self.assertTrue(category.delivery_value_is_present("Deliver to New York 10-001", "10001"))
        self.assertFalse(category.delivery_value_is_present("Deliver to 110001", "10001"))
        self.assertFalse(category.delivery_value_is_present("Deliver to 10002", "0002"))


class DeliveryLocationFlowTests(unittest.TestCase):
    def test_postal_submit_reopens_original_url_and_same_domain_uses_cache(self) -> None:
        location = {"amazon.com": {"city": "New York", "postal_code": "10001", "strategy": "postal"}}
        runtime = runtime_for(location)
        driver = FakeDriver("https://www.amazon.com/s?k=one", accepted_postals={"10001"})
        attempt, confirm, sleep = fast_delivery_patches()
        with attempt, confirm, sleep:
            category.open_amazon_page(driver, "https://www.amazon.com/s?k=one", runtime)
            category.open_amazon_page(driver, "https://www.amazon.com/s?k=two", runtime)
        self.assertEqual(driver.postal_attempts, ["10001"])
        self.assertEqual(driver.get_calls.count("https://www.amazon.com/s?k=one"), 2)
        self.assertEqual(driver.get_calls[-1], "https://www.amazon.com/s?k=two")

    def test_reopened_confirmation_gets_a_fresh_timeout_window(self) -> None:
        locations = {"amazon.com": {"city": "New York", "postal_code": "10001", "strategy": "postal"}}
        runtime = runtime_for(locations)
        driver = FakeDriver("https://www.amazon.com/")
        remaining_windows: list[float] = []

        def confirm(_driver: object, _location: object, deadline: float, **_kwargs: object) -> bool:
            if not remaining_windows:
                category.time.sleep(1.05)
                remaining_windows.append(-1)
                return False
            remaining_windows.append(deadline - category.time.time())
            return True

        with (
            patch.object(category, "_attempt_delivery_value", return_value=True),
            patch.object(category, "_wait_for_delivery_confirmation", side_effect=confirm),
            patch.object(category, "_reopen_amazon_target", return_value=False),
        ):
            category.ensure_amazon_delivery_location(driver, runtime, original_url=driver.current_url)
        self.assertGreater(remaining_windows[-1], 0.8)

    def test_compact_postal_is_tried_after_formatted_value_is_rejected(self) -> None:
        location = {"amazon.ca": {"city": "Ottawa", "postal_code": "K1P 1J1", "strategy": "postal"}}
        runtime = runtime_for(location)
        driver = FakeDriver("https://www.amazon.ca/s?k=one", accepted_postals={"K1P1J1"})
        attempt, confirm, sleep = fast_delivery_patches()
        with attempt, confirm, sleep:
            category.open_amazon_page(driver, driver.current_url, runtime)
        self.assertEqual(driver.postal_attempts, ["K1P 1J1", "K1P1J1"])
        self.assertIn("K1P1J1", driver.header)

    def test_delayed_location_widget_is_retriggered_until_submit_is_ready(self) -> None:
        driver = FakeDriver("https://www.amazon.ca/")
        submit_results = iter((False, True))
        with (
            patch.object(category, "_click_delivery_trigger", return_value=True) as trigger,
            patch.object(category.time, "sleep"),
        ):
            submitted = category._attempt_delivery_value(
                driver,
                "K1P 1J1",
                category.time.time() + 1,
                lambda *_: next(submit_results),
            )
        self.assertTrue(submitted)
        self.assertEqual(trigger.call_count, 2)

    def test_not_applicable_postal_form_stops_retry_chain(self) -> None:
        driver = FakeDriver("https://www.amazon.ae/")
        submitter_calls: list[str] = []
        with patch.object(category, "_click_delivery_trigger", return_value=True):
            submitted = category._attempt_delivery_value(
                driver,
                "00000",
                category.time.time() + 1,
                lambda _driver, value: submitter_calls.append(value) or None,
            )
        self.assertIsNone(submitted)
        self.assertEqual(submitter_calls, ["00000"])

    def test_split_postal_form_uses_visible_javascript_submit(self) -> None:
        class SplitDriver(FakeDriver):
            def execute_script(self, script: str, *args: object) -> object:
                if "lc_delivery_split_postal_fill" in script:
                    self.postal_attempts.append(str(args[0]))
                    return True
                if "lc_delivery_split_postal_submit" in script:
                    return True
                return super().execute_script(script, *args)

        driver = SplitDriver("https://www.amazon.co.jp/")
        self.assertTrue(category._submit_delivery_postal(driver, "100-0001"))
        self.assertEqual(driver.postal_attempts, ["100-0001"])

    def test_split_postal_form_uses_native_typing_before_submit(self) -> None:
        class SplitDriver(FakeDriver):
            def __init__(self) -> None:
                super().__init__("https://www.amazon.co.jp/")
                self.values = {"GLUXZipUpdateInput_0": "", "GLUXZipUpdateInput_1": ""}

            def execute_script(self, script: str, *args: object) -> object:
                if "lc_delivery_split_postal_fields" in script:
                    return [
                        {"id": field_id, "maxLength": length, "value": self.values[field_id]}
                        for field_id, length in (
                            ("GLUXZipUpdateInput_0", 3),
                            ("GLUXZipUpdateInput_1", 4),
                        )
                    ]
                if "lc_delivery_split_postal_submit" in script:
                    return True
                return super().execute_script(script, *args)

            def find_element(self, _by: str, selector: str) -> object:
                field_id = selector.removeprefix("#")
                driver = self

                class SplitInput:
                    def clear(self) -> None:
                        driver.values[field_id] = ""

                    def type_text(self, value: str) -> None:
                        driver.values[field_id] = value

                return SplitInput()

        driver = SplitDriver()
        self.assertFalse(category._submit_delivery_postal(driver, "100-0001"))
        self.assertEqual(driver.values, {"GLUXZipUpdateInput_0": "100", "GLUXZipUpdateInput_1": "0001"})
        self.assertTrue(category._submit_delivery_postal(driver, "100-0001"))

    def test_single_postal_form_uses_native_typing_before_submit(self) -> None:
        class NativeDriver(FakeDriver):
            def __init__(self) -> None:
                super().__init__("https://www.amazon.com/")
                self.typed = ""

            def execute_script(self, script: str, *args: object) -> object:
                if "lc_delivery_city_only_form" in script:
                    return False
                if "lc_delivery_postal_with_city_submit" in script:
                    return "not_applicable"
                if "lc_delivery_split_postal_fields" in script:
                    return []
                if "lc_delivery_split_postal_fill" in script:
                    return False
                return super().execute_script(script, *args)

            def find_element(self, _by: str, selector: str) -> object:
                driver = self

                if selector == "#GLUXZipUpdateInput":
                    class PostalInput:
                        def clear(self) -> None:
                            driver.typed = ""

                        def type_text(self, value: str) -> None:
                            driver.typed = value

                        def send_keys(self, _value: str) -> None:
                            raise AssertionError("CDP should use sequential native typing")

                    return PostalInput()

                if selector == "#GLUXZipUpdate":
                    class SubmitButton:
                        def click(self) -> None:
                            return None

                    return SubmitButton()

                raise AssertionError(f"unexpected selector: {selector}")

        driver = NativeDriver()
        self.assertTrue(category._submit_delivery_postal(driver, "10001", "New York"))
        self.assertEqual(driver.typed, "10001")

    def test_postal_with_city_form_waits_for_city_then_submits(self) -> None:
        class PostalWithCityDriver(FakeDriver):
            statuses = iter(("waiting", "submitted"))

            def execute_script(self, script: str, *args: object) -> object:
                if "lc_delivery_postal_with_city_submit" in script:
                    self.postal_attempts.append(f"{args[0]}:{args[1]}")
                    return next(self.statuses)
                return super().execute_script(script, *args)

        driver = PostalWithCityDriver("https://www.amazon.com.au/")
        self.assertFalse(category._submit_delivery_postal(driver, "2600", "Canberra"))
        self.assertTrue(category._submit_delivery_postal(driver, "2600", "Canberra"))
        self.assertEqual(driver.postal_attempts, ["2600:Canberra", "2600:Canberra"])

    def test_city_with_district_form_types_selects_and_submits(self) -> None:
        class CityDriver(FakeDriver):
            statuses = iter(("needs_typing", "waiting", "submitted"))

            def execute_script(self, script: str, *args: object) -> object:
                if "lc_delivery_city_with_district_submit" in script:
                    return next(self.statuses)
                return super().execute_script(script, *args)

            def find_element(self, *_args: object, **_kwargs: object) -> object:
                driver = self

                class CityInput:
                    def clear(self) -> None:
                        pass

                    def send_keys(self, value: str) -> None:
                        driver.city_attempts.append(value)

                return CityInput()

        driver = CityDriver("https://www.amazon.ae/")
        self.assertFalse(category._submit_delivery_city(driver, "Abu Dhabi"))
        self.assertFalse(category._submit_delivery_city(driver, "Abu Dhabi"))
        self.assertTrue(category._submit_delivery_city(driver, "Abu Dhabi"))
        self.assertEqual(driver.city_attempts, ["Abu Dhabi"])

    def test_applescript_elements_support_delivery_form_operations(self) -> None:
        class ScriptDriver:
            def __init__(self) -> None:
                self.calls: list[tuple[str, tuple[object, ...]]] = []

            def execute_script(self, script: str, *args: object) -> bool:
                self.calls.append((script, args))
                return True

        driver = ScriptDriver()
        element = category.AppleScriptElement("", driver, "#delivery-input")
        element.clear()
        element.type_text("10001")
        element.click()
        self.assertEqual([call[1][0] for call in driver.calls], ["#delivery-input"] * 3)
        self.assertEqual(driver.calls[1][1][1], "10001")

    def test_post_submit_confirmation_accepts_amazon_final_character_privacy_mask(self) -> None:
        driver = FakeDriver("https://www.amazon.ca/", header="Deliver to K1P 1J\u200c")
        location = {"city": "Ottawa", "postal_code": "K1P 1J1", "strategy": "postal"}
        self.assertFalse(category.delivery_location_is_confirmed(driver, location))
        self.assertTrue(category._submitted_delivery_location_is_confirmed(driver, location))

        wrong_prefix = {"city": "Ottawa", "postal_code": "K1P 2J1", "strategy": "postal"}
        self.assertFalse(category._submitted_delivery_location_is_confirmed(driver, wrong_prefix))

        mask_in_wrong_position = FakeDriver("https://www.amazon.ca/", header="\u200cK1P 1J")
        self.assertFalse(category._submitted_delivery_location_is_confirmed(mask_in_wrong_position, location))

    def test_uae_city_fallback_runs_only_after_postal_rejection(self) -> None:
        location = {"amazon.ae": {"city": "Abu Dhabi", "postal_code": "00000", "strategy": "postal_then_city"}}
        runtime = runtime_for(location)
        driver = FakeDriver("https://www.amazon.ae/s?k=one", accepted_cities={"Abu Dhabi"})
        attempt, confirm, sleep = fast_delivery_patches()
        with attempt, confirm, sleep:
            category.open_amazon_page(driver, driver.current_url, runtime)
        self.assertEqual(driver.postal_attempts, ["00000"])
        self.assertEqual(driver.city_attempts, ["Abu Dhabi"])
        self.assertIn("Abu Dhabi", driver.header)

    def test_uae_unapplied_city_input_is_not_confirmed_or_cached(self) -> None:
        class UnappliedCityDriver(FakeDriver):
            def __init__(self) -> None:
                super().__init__("https://www.amazon.ae/", header="Deliver to Dubai")
                self.city_input = "Abu Dhabi"

            def get(self, url: str) -> None:
                super().get(url)
                self.city_input = "Dubai"

            def execute_script(self, script: str, *args: object) -> object:
                if "lc_delivery_city_input_reset" in script:
                    self.city_input = ""
                    return "cleared"
                if "lc_delivery_city_input_snapshot" in script:
                    return self.city_input
                return super().execute_script(script, *args)

        locations = {
            "amazon.ae": {
                "city": "Abu Dhabi",
                "postal_code": "00000",
                "strategy": "postal_then_city",
            }
        }
        runtime = runtime_for(locations)
        driver = UnappliedCityDriver()
        self.assertFalse(category._submitted_delivery_location_is_confirmed(driver, locations["amazon.ae"]))
        with (
            patch.object(category, "_attempt_delivery_value", return_value=False),
            patch.object(category, "wait_for_manual_continue", side_effect=[True, False]),
        ):
            with self.assertRaises(category.DeliveryLocationUnconfirmedError):
                category.ensure_amazon_delivery_location(
                    driver,
                    runtime,
                    original_url=driver.current_url,
                )
        self.assertEqual(driver.get_calls, ["https://www.amazon.ae/"])
        self.assertEqual(category._delivery_cache(runtime, driver), set())

    def test_uae_reloaded_modal_requires_exact_persisted_city(self) -> None:
        class ReloadedCityDriver(FakeDriver):
            def __init__(self, persisted_city: str) -> None:
                super().__init__("https://www.amazon.ae/", header="Deliver to Ab..., Al R...")
                self.persisted_city = persisted_city
                self.city_input = "Abu Shagara"
                self.modal_open = True

            def get(self, url: str) -> None:
                super().get(url)
                self.city_input = self.persisted_city
                self.modal_open = False

            def execute_script(self, script: str, *args: object) -> object:
                if "lc_delivery_city_input_reset" in script:
                    self.city_input = ""
                    return "cleared"
                if "lc_delivery_city_input_snapshot" in script:
                    return self.city_input if self.modal_open else ""
                if "lc_delivery_open" in script:
                    self.modal_open = True
                    return True
                if "lc_delivery_city_dialog_close" in script:
                    self.modal_open = False
                    return True
                return super().execute_script(script, *args)

        location = {"city": "Abu Dhabi", "postal_code": "00000", "strategy": "postal_then_city"}
        runtime = runtime_for({"amazon.ae": location})

        confirmed = ReloadedCityDriver("Abu Dhabi")
        confirmed._lc_delivery_trigger_opened = ("amazon.ae", category.time.time())
        reset_and_reloaded = category._reopen_amazon_target(
            confirmed,
            confirmed.current_url,
            runtime,
            None,
            None,
            clear_transient_city_input=True,
        )
        self.assertTrue(reset_and_reloaded)
        self.assertFalse(hasattr(confirmed, "_lc_delivery_trigger_opened"))
        self.assertTrue(
            category._wait_for_delivery_confirmation(
                confirmed,
                location,
                category.time.time() + 1,
                allow_reloaded_city_input=reset_and_reloaded,
            )
        )

        collision = ReloadedCityDriver("Abu Hail")
        reset_and_reloaded = category._reopen_amazon_target(
            collision,
            collision.current_url,
            runtime,
            None,
            None,
            clear_transient_city_input=True,
        )
        self.assertTrue(reset_and_reloaded)
        collision.modal_open = True
        self.assertFalse(
            category._submitted_delivery_location_is_confirmed(
                collision,
                location,
                allow_reloaded_city_input=reset_and_reloaded,
            )
        )

        unclosable = ReloadedCityDriver("Abu Dhabi")
        unclosable.modal_open = True
        original_execute = unclosable.execute_script

        def fail_close(script: str, *args: object) -> object:
            if "lc_delivery_city_dialog_close" in script:
                return False
            return original_execute(script, *args)

        with patch.object(unclosable, "execute_script", side_effect=fail_close):
            self.assertFalse(
                category._submitted_delivery_location_is_confirmed(
                    unclosable,
                    location,
                    allow_reloaded_city_input=True,
                )
            )

    def test_cache_is_separate_for_domain_and_driver(self) -> None:
        locations = {
            "amazon.com": {"city": "New York", "postal_code": "10001", "strategy": "postal"},
            "amazon.ca": {"city": "Ottawa", "postal_code": "K1P 1J1", "strategy": "postal"},
        }
        runtime = runtime_for(locations)
        first = FakeDriver(
            "https://www.amazon.com/",
            accepted_postals={"10001", "K1P 1J1"},
        )
        second = FakeDriver("https://www.amazon.com/", accepted_postals={"10001"})
        attempt, confirm, sleep = fast_delivery_patches()
        with attempt, confirm, sleep:
            category.open_amazon_page(first, "https://www.amazon.com/", runtime)
            first.header = "Deliver to"
            category.open_amazon_page(first, "https://www.amazon.ca/", runtime)
            category.open_amazon_page(second, "https://www.amazon.com/", runtime)
        self.assertEqual(first.postal_attempts, ["10001", "K1P 1J1"])
        self.assertEqual(second.postal_attempts, ["10001"])

    def test_verification_is_cleared_before_delivery_check(self) -> None:
        runtime = runtime_for(
            {"amazon.com": {"city": "New York", "postal_code": "10001", "strategy": "postal"}}
        )
        driver = FakeDriver("https://www.amazon.com/", header="Deliver to 10001")
        events: list[str] = []
        with (
            patch.object(category, "detect_block", return_value="amazon_robot_check"),
            patch.object(category, "wait_for_manual_clear", side_effect=lambda *_: events.append("clear") or True),
            patch.object(category, "ensure_amazon_delivery_location", side_effect=lambda *_args, **_kwargs: events.append("ensure")),
        ):
            category.open_amazon_page(
                driver,
                driver.current_url,
                runtime,
                on_manual_pause=lambda *_: events.append("pause"),
                on_manual_resume=lambda: events.append("resume"),
            )
        self.assertEqual(events, ["pause", "clear", "resume", "ensure"])

    def test_verification_timeout_stops_before_delivery_check(self) -> None:
        runtime = runtime_for(
            {"amazon.com": {"city": "New York", "postal_code": "10001", "strategy": "postal"}}
        )
        driver = FakeDriver("https://www.amazon.com/")
        with (
            patch.object(category, "detect_block", return_value="amazon_robot_check"),
            patch.object(category, "wait_for_manual_clear", return_value=False),
            patch.object(category, "ensure_amazon_delivery_location") as ensure,
        ):
            with self.assertRaisesRegex(
                category.VerificationUnconfirmedError,
                "amazon_robot_check_unconfirmed",
            ):
                category.open_amazon_page(driver, driver.current_url, runtime)
        ensure.assert_not_called()

    def test_non_us_amazon_sign_in_is_detected_before_delivery(self) -> None:
        driver = FakeDriver("https://www.amazon.de/ap/signin")
        with patch.object(category, "safe_find_text", return_value="Sign in"):
            self.assertEqual(category.detect_block(driver), "amazon_sign_in")

        driver.current_url = "https://www.amazon.de/s?k=test"
        with patch.object(category, "safe_find_text", return_value="Sign in"):
            self.assertIsNone(category.detect_block(driver))

    def test_amazon_sign_in_never_waits_for_buyer_account_login(self) -> None:
        driver = FakeDriver("https://www.amazon.com/ap/signin")
        with (
            patch.object(category, "wait_for_manual_continue") as wait,
            patch("builtins.print") as print_mock,
        ):
            self.assertFalse(category.wait_for_manual_clear(driver, "amazon_sign_in", 900))
        wait.assert_not_called()
        output = "\n".join(str(call.args[0]) for call in print_mock.call_args_list)
        self.assertIn("不使用亚马逊买家账号，也不会要求用户登录", output)
        self.assertNotIn("完成登录", output)

    def test_manual_success_is_required_after_auto_failure(self) -> None:
        location = {"amazon.com": {"city": "New York", "postal_code": "10001", "strategy": "postal"}}
        runtime = runtime_for(location)
        driver = FakeDriver("https://www.amazon.com/")
        events: list[str] = []
        with (
            patch.object(category, "_attempt_delivery_value", return_value=False),
            patch.object(category, "delivery_location_is_confirmed", side_effect=[False, True]),
            patch.object(category, "wait_for_manual_continue", return_value=True),
        ):
            category.ensure_amazon_delivery_location(
                driver,
                runtime,
                original_url=driver.current_url,
                on_manual_pause=lambda reason, _url: events.append(reason),
                on_manual_resume=lambda: events.append("resumed"),
            )
        self.assertEqual(events, ["delivery_location_unconfirmed", "resumed"])

    def test_manual_timeout_fails_closed(self) -> None:
        location = {"amazon.com": {"city": "New York", "postal_code": "10001", "strategy": "postal"}}
        runtime = runtime_for(location)
        driver = FakeDriver("https://www.amazon.com/")
        pauses: list[str] = []
        with (
            patch.object(category, "_attempt_delivery_value", return_value=False),
            patch.object(category, "wait_for_manual_continue", return_value=False),
        ):
            with self.assertRaisesRegex(category.DeliveryLocationUnconfirmedError, "delivery_location_unconfirmed"):
                category.ensure_amazon_delivery_location(
                    driver,
                    runtime,
                    original_url=driver.current_url,
                    on_manual_pause=lambda reason, _url: pauses.append(reason),
                )
        self.assertEqual(pauses, ["delivery_location_unconfirmed"])

    def test_verification_manual_timeout_uses_one_absolute_deadline(self) -> None:
        driver = FakeDriver("https://www.amazon.com/errors/validateCaptcha")
        waits: list[int] = []
        with (
            patch.object(category.time, "time", side_effect=[0, 1, 10]),
            patch.object(
                category,
                "wait_for_manual_continue",
                side_effect=lambda remaining: waits.append(remaining) or True,
            ),
            patch.object(category, "detect_block", return_value="amazon_robot_check"),
        ):
            self.assertFalse(
                category.wait_for_manual_clear(driver, "amazon_robot_check", 10)
            )
        self.assertEqual(waits, [9])

    def test_unsupported_marketplace_uses_terminal_delivery_error(self) -> None:
        runtime = runtime_for(
            {"amazon.com": {"city": "New York", "postal_code": "10001", "strategy": "postal"}}
        )
        driver = FakeDriver("https://www.amazon.be/")
        with self.assertRaisesRegex(category.DeliveryLocationUnconfirmedError, "delivery_location_unsupported"):
            category.ensure_amazon_delivery_location(driver, runtime, original_url=driver.current_url)


class DeliveryFingerprintTests(unittest.TestCase):
    def test_existing_records_without_matching_fingerprint_are_rejected(self) -> None:
        runtime = SimpleNamespace(delivery_location_fingerprint="new")
        with self.assertRaisesRegex(category.UserFacingError, "新的 `job_id`"):
            category.ensure_resume_delivery_fingerprint({"records_count": 1}, runtime)
        with self.assertRaisesRegex(category.UserFacingError, "新的 `job_id`"):
            category.ensure_resume_delivery_fingerprint(
                {"records_count": 0, "completed_pages": ["page"]},
                runtime,
            )
        with tempfile.TemporaryDirectory() as temp_dir:
            records_path = Path(temp_dir) / "records.jsonl"
            records_path.write_text('{"asin":"B000000001"}\n', encoding="utf-8")
            with self.assertRaisesRegex(category.UserFacingError, "新的 `job_id`"):
                category.ensure_resume_delivery_fingerprint(
                    {"records_count": 0, "completed_pages": []},
                    runtime,
                    records_path,
                )

    def test_empty_state_can_adopt_current_fingerprint(self) -> None:
        runtime = SimpleNamespace(delivery_location_fingerprint="new")
        state = {"records_count": 0, "completed_pages": []}
        self.assertTrue(category.ensure_resume_delivery_fingerprint(state, runtime))
        self.assertEqual(state["delivery_location_fingerprint"], "new")
        self.assertFalse(category.ensure_resume_delivery_fingerprint(state, runtime))


if __name__ == "__main__":
    unittest.main()
