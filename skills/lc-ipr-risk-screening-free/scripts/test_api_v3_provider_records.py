"""Offline contracts for API-first-v3 public provider records and bounded readers."""
import copy
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image
from provider_utils import ProviderError
import serpapi_lens_client as lens
import serpapi_patents_client as patents
import serpapi_patent_details_client as details
import serper_client as serper
import signa_client as signa
import epo_ops_client as epo
import euipo_client as euipo
import inpi_client as inpi
import jpo_api_client as jpo


V3 = "api-first-v3"


def api_task(revision=V3):
    return {"schema_version": "2.4-free", "retrieval_workflow_revision": revision,
            "decision_workflow_revision": "scenario-triage-v1", "workflow_correction_revision": "workflow-correction-v1",
            "retrieval_policy": {"dynamic_evidence_max_age_hours": 48}}


def mark_record(**changes):
    row = {"object": "trademark", "id": "tm_fixture", "office_code": "US", "jurisdiction_code": "US",
           "mark_text": "FIXTURE", "mark_feature_type": "combined", "application_number": "12345678",
           "registration_number": "1234567", "status": {"primary": "active", "stage": "registered", "basis": "office"},
           "owners": [{"name": "Example owner"}], "classifications": [{"nice_class": 20, "goods_services_text": "Furniture", "goods_services_text_truncated": False}],
           "design_codes": [{"system": "us_design_search", "code": "030101"}],
           "has_media": True, "primary_image_url": "https://api.signa.so/v1/trademarks/tm_fixture/media/med_fixture"}
    row.update(changes)
    return row


def signa_item(operation="candidate_detail", **changes):
    row = {"query_id": "Q-signa", "q": "tm_fixture", "operation": operation,
           "candidate_id": "C-fixture", "provider_record_id": "tm_fixture", "right_type": "trademark_figurative",
           "jurisdiction": "US", "missing_facts": ["goods_services"]}
    row.update(changes)
    return row


class PatentRecordTests(unittest.TestCase):
    def setUp(self):
        self.item = {"q": "US1234567B2", "patent_id": "patent/US1234567B2/en", "candidate_id": "C", "right_type": "patent", "jurisdiction": "US"}
        self.payload = {"publication_number": "US1234567B2", "claims": ["1. A device having a hinge."], "images": [{"url": "https://example.test/image.png"}],
                        "application_number": "US12/345,678", "assignees": ["Original assignee"], "publication_date": "2020-01-01",
                        "legal_events": [{"title": "Patent granted", "date": "2020-01-01"}],
                        "worldwide_applications": {"2020": [{"this_app": True, "document_id": "patent/US1234567B2/en", "country_code": "US", "legal_status": "Expired", "legal_status_cat": "expired"}]}}

    def normalize(self):
        return details._normalize(self.payload, self.item, retrieval_workflow_revision=V3)

    def test_target_record_fields_and_status_are_retained(self):
        value = self.normalize()
        self.assertEqual(value["legal_status"], "Expired")
        self.assertEqual(value["assignees"], ["Original assignee"])
        self.assertNotIn("owners", value)
        self.assertEqual(value["status_detail"]["record_scope"], "target_document")
        self.assertEqual(value["application_number"], "US12/345,678")
        self.assertIsNone(value["source_updated_at"])
        self.assertIn("legal_status", value["satisfied_facts"])

    def test_other_family_member_status_never_becomes_target_status(self):
        self.payload["worldwide_applications"]["2020"][0]["document_id"] = "patent/US9999999B2/en"
        self.assertNotIn("legal_status", self.normalize())

    def test_wrong_country_status_never_becomes_target_status(self):
        self.payload["worldwide_applications"]["2020"][0]["country_code"] = "GB"
        self.assertNotIn("legal_status", self.normalize())

    def test_historical_grant_event_is_not_current_status(self):
        del self.payload["worldwide_applications"]
        result = self.normalize()
        self.assertNotIn("legal_status", result)
        self.assertEqual(result["legal_events"], self.payload["legal_events"])

    def test_conflicting_target_statuses_remain_unresolved(self):
        self.payload["worldwide_applications"]["2020"].append({**self.payload["worldwide_applications"]["2020"][0], "legal_status": "Active"})
        value = self.normalize()
        self.assertNotIn("legal_status", value)
        self.assertEqual(value["source_status_conflict"], ["Active", "Expired"])

    def test_planned_country_and_document_are_checked(self):
        for change in ({"jurisdiction": "GB"}, {"patent_id": "patent/US9999999B2/en"}):
            with self.subTest(change=change), self.assertRaises(ProviderError):
                details._normalize(self.payload, {**self.item, **change}, retrieval_workflow_revision=V3)

    def test_truncated_claims_do_not_satisfy_protection_content(self):
        self.payload["claims_truncated"] = True
        self.assertNotIn("protection_content", self.normalize()["satisfied_facts"])

    def test_old_normalization_does_not_acquire_v3_status(self):
        value = details._normalize(self.payload, self.item, retrieval_workflow_revision="api-first-v2")
        self.assertEqual(value["source_role"], "published_document_content_only")
        self.assertNotIn("legal_status", value)

    def test_details_share_search_and_lens_request_budget(self):
        runs = [{"provider": provider, "operation": operation, "quota": {"network_request_attempted": True}}
                for provider, operation in [("serpapi_google_patents", "search"), ("serpapi_google_lens", "image_search"), ("serpapi_google_patents", "candidate_detail")]]
        self.assertEqual(patents.consumed_queries({"source_runs": runs}), 3)


class VisualRecordTests(unittest.TestCase):
    def test_v3_retained_lens_replays_same_revision_and_scope(self):
        from common import sha256_file
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            raw = {"search_metadata": {"status": "Success"}, "visual_matches": [{"link": "https://example.test/a", "image": "https://example.test/a.png"}]}
            path = root / "raw.json"
            path.write_text(json.dumps(raw))
            run = {"provider": lens.PROVIDER, "operation": lens.OPERATION, "status": "success", "run_id": "R", "query_id": "Q", "plan_entry_sha256": "p", "raw_paths": [str(path)], "payload_digest": sha256_file(path), "right_type": "trade_dress"}
            entry = {"provider": lens.PROVIDER, "operation": lens.OPERATION, "source_run_id": "R", "query_id": "Q", "plan_entry_sha256": "p", "right_type": "trade_dress", "payload": lens.normalize(raw, retrieval_workflow_revision=V3, investigation_right_type="trade_dress")}
            evidence = {"collections": {"copyright_assets": [entry]}}
            before = copy.deepcopy(evidence)
            result = lens.retained_source_records(evidence, run, root)
            self.assertEqual(result[0]["investigation_right_type"], "trade_dress")
            self.assertEqual(result[0]["right_type"], "unknown")
            self.assertEqual(evidence, before)
            entry["payload"]["candidates"][0].pop("source_record_hash_stage")
            with self.assertRaises(ValueError):
                lens.retained_source_records(evidence, run, root)

    def test_lens_does_not_assert_copyright_for_other_investigations(self):
        payload = {"search_metadata": {"status": "Success"}, "visual_matches": [{"title": "A package", "link": "https://example.test/package", "thumbnail": "https://example.test/thumb.png"}]}
        value = lens.normalize(payload, retrieval_workflow_revision=V3, investigation_right_type="trade_dress")["candidates"][0]
        self.assertEqual(value["right_type"], "unknown")
        self.assertEqual(value["investigation_right_type"], "trade_dress")
        self.assertEqual(value["image_kind"], "thumbnail")
        self.assertEqual(lens.normalize(payload)["candidates"][0]["right_type"], "copyright")

    def test_serper_web_result_is_not_an_established_right(self):
        value = serper.normalize("serper_web", "search", {"organic": [{"title": "Example", "link": "https://example.test/a", "snippet": "Claimed package design"}]}, retrieval_workflow_revision=V3)[0]
        self.assertEqual(value["candidate_nature"], "web_result")
        self.assertEqual(value["right_type"], "unknown")


class SignaRecordTests(unittest.TestCase):
    def test_fact_metadata_is_retained_locally_and_not_sent_in_search_body(self):
        task = api_task()
        task["product_delivery_revision"] = "image-fact-v1"
        row = {"q": "FIXTURE", "strategies": list(signa.SEARCH_STRATEGIES), "limit": 25,
               "filters": {"offices": ["US"]}, "options": {"include_total": False},
               "product_delivery_revision": "image-fact-v1",
               "product_fact_refs": [{"fact_id": "shape", "version": 1,
                                      "nature": "direct_observation", "verification": "verified"}]}
        original = copy.deepcopy(row)
        body = signa._request_from_plan(row, 25, task=task)
        self.assertEqual(row, original)
        self.assertEqual(set(body), {"query", "strategies", "limit", "filters", "options"})
        for revision in (None, "unsupported-revision"):
            historical = api_task()
            if revision is not None:
                historical["product_delivery_revision"] = revision
            with self.subTest(revision=revision), self.assertRaises(ProviderError):
                signa._request_from_plan(row, 25, task=historical)
        with self.assertRaises(ProviderError):
            signa._request_from_plan({**row, "unexpected_field": True}, 25, task=task)

    def test_detail_and_media_authorization_accept_only_enabled_fact_metadata(self):
        import common
        task = {**api_task(), "product_delivery_revision": "image-fact-v1",
                "target_jurisdictions": ["US"]}
        for operation in common.SIGNA_RECORD_OPERATIONS:
            row = signa_item(operation, required=False, authoritative_for_final_rating=False,
                role=common.SIGNA_FREE_ROLE, required_for=common.SIGNA_FREE_ROLE,
                execute_by_default=True, product_delivery_revision="image-fact-v1", product_fact_refs=[])
            if operation == common.SIGNA_MEDIA_OPERATION:
                row["media_id"] = "med_fixture"
            row["query_id"] = common._signa_expected_query_id(row)
            with self.subTest(operation=operation):
                common._authorize_signa_record_operation(task, row, row["query_id"])
                historical = dict(task)
                historical.pop("product_delivery_revision")
                with self.assertRaisesRegex(ValueError, "SIGNA_PLAN_PARAMETERS_INVALID"):
                    common._authorize_signa_record_operation(historical, row, row["query_id"])
                with self.assertRaisesRegex(ValueError, "SIGNA_PLAN_PARAMETERS_INVALID"):
                    common._authorize_signa_record_operation(task, {**row, "unexpected_field": True}, row["query_id"])

    def test_v3_public_filters_and_projection(self):
        row = {"q": "FIXTURE", "strategies": list(signa.SEARCH_STRATEGIES), "limit": 25,
               "filters": {"offices": ["US"], "mark_feature_type": "combined", "has_media": True, "nice_classes": [20]},
               "options": {"include_total": False}, "include": ["full_goods_services"]}
        value = signa._request_from_plan(row, 25, task=api_task())
        self.assertEqual(value["filters"], row["filters"])
        with self.assertRaises(ProviderError):
            signa._request_from_plan(row, 25, task=api_task("api-first-v2"))
        for filters in ({"mark_feature_type": []}, {"has_media": 1}, {"image_similarity": "url"}, {"nice_classes": [True]}):
            with self.subTest(filters=filters), self.assertRaises(ProviderError):
                signa._request_from_plan({**row, "filters": {"offices": ["US"], **filters}}, 25, task=api_task())

    def test_detail_retains_status_owner_classes_and_source_provenance(self):
        record = mark_record(provenance={"source_data_date": "2026-09-01", "office_updated_at": "2026-09-01T10:00:00Z"}, expiry_date=None, derived={"expiry_date": "2030-01-01"})
        value = signa.normalize_detail(record, signa_item())
        self.assertEqual(value["right_type"], "trademark_figurative")
        self.assertEqual(value["owners"], ["Example owner"])
        self.assertIn("goods_services", value["satisfied_facts"])
        self.assertIsNone(value["expiry_date"])
        self.assertEqual(value["source_updated_at"], "2026-09-01T10:00:00Z")

    def test_word_and_figurative_classification_preserve_source(self):
        for kind in ("word", "figurative", "combined", "three_dimensional"):
            value = signa.normalize_detail(mark_record(mark_feature_type=kind), signa_item())
            self.assertEqual(value["right_type"], "trademark_word" if kind == "word" else "trademark_figurative")
        envelope = {"object": "list", "data": [mark_record()], "has_more": False, "pagination": {"cursor": None}}
        self.assertEqual(signa.normalize(envelope, ["US"])[0][0]["right_type"], "trademark_word")

    def test_wrong_identity_and_country_rejected(self):
        for record in (mark_record(id="tm_other"), mark_record(jurisdiction_code="GB"), mark_record(office_code="GB")):
            with self.subTest(record=record), self.assertRaises(ProviderError):
                signa.normalize_detail(record, signa_item())

    def test_missing_fields_never_become_complete(self):
        value = signa.normalize_detail(mark_record(status=None, owners=None, classifications=None), signa_item())
        self.assertEqual(value["satisfied_facts"], ["record_identity"])
        for truncated in (True, None):
            record = mark_record(classifications=[{"nice_class": 20, "goods_services_text": "Furniture", "goods_services_text_truncated": truncated}])
            self.assertNotIn("goods_services", signa.normalize_detail(record, signa_item())["satisfied_facts"])
        record = mark_record(classifications=[{"nice_class": 20, "goods_services_text": "Furniture", "goods_services_text_truncated": False, "scope": "as_filed"}])
        self.assertNotIn("goods_services", signa.normalize_detail(record, signa_item())["satisfied_facts"])

    def test_known_record_requires_missing_fact_and_bounded_identifiers(self):
        task = {"retrieval_workflow_revision": V3}
        for changes in ({"missing_facts": []}, {"provider_record_id": "tm_a/../b"}, {"candidate_id": ""}, {"operation": "trademark_media", "media_id": "../image"}):
            with self.subTest(changes=changes), self.assertRaises(ProviderError):
                signa._known_record_params(signa_item(**changes), task)
        with self.assertRaises(ProviderError):
            signa._known_record_params(signa_item(), {"retrieval_workflow_revision": "api-first-v2"})

    def test_media_identity_and_real_image_bytes(self):
        buffer = io.BytesIO()
        Image.new("RGB", (2, 3)).save(buffer, format="PNG")
        item = signa_item("trademark_media", media_id="med_fixture")
        value, suffix = signa._media_result(buffer.getvalue(), {"Content-Type": "image/png"}, item, signa.OFFICIAL_BASE_URL)
        self.assertEqual(suffix, "png")
        self.assertEqual(value["media"][0]["width"], 2)
        self.assertEqual(value["provider_record_id"], "tm_fixture")
        for body, mime in ((b"<html>login</html>", "text/html"), (b"\x89PNG\r\n\x1a\n", "image/png")):
            with self.subTest(mime=mime), self.assertRaises(ProviderError):
                signa._media_result(body, {"Content-Type": mime}, item, signa.OFFICIAL_BASE_URL)

    def test_known_record_requests_share_signa_budget(self):
        runs = [{"provider": "signa", "operation": operation, "query_id": "Q" + str(index), "quota": {"search_request_attempted": True}}
                for index, operation in enumerate(("trademark_search", "candidate_detail", "trademark_media"))]
        self.assertEqual(signa.consumed_queries({"source_runs": runs}), 3)
        self.assertTrue(signa.query_was_attempted({"source_runs": runs}, "Q1"))

    def test_detail_execute_preserves_operation_and_shared_reservation(self):
        task = {"retrieval_workflow_revision": V3}
        item = signa_item()
        pre = {"usage": {"remaining": 10, "used": 0, "limit": 10}, "plan": "free"}
        post = {"usage": {"used": 1, "limit": 10}, "billing_safe": True}
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp)
            (path / "evidence.json").write_text(json.dumps({"source_runs": []}))
            with patch.object(signa, "settings", return_value=({"http": {"timeout_seconds": 3}}, signa.OFFICIAL_BASE_URL, "fixture-key")), patch.object(signa, "_precheck", return_value=copy.deepcopy(pre)), patch.object(signa, "_postcheck", return_value=post), patch.object(signa, "reserve_search", return_value={"reservation": "fake"}) as reserve, patch.object(signa, "http_json", return_value=(mark_record(), {}, b"{}")) as request, patch.object(signa, "record_result", side_effect=lambda _, **kwargs: kwargs):
                result = signa._execute_known_record(path, item["query_id"], task, item)
            self.assertEqual(result["operation"], "candidate_detail")
            self.assertEqual(result["status"], "success")
            self.assertEqual(request.call_args.args[0], signa.OFFICIAL_BASE_URL + "/v1/trademarks/tm_fixture")
            self.assertEqual(reserve.call_args.kwargs["max_queries_per_task"], 3)


class PatentFigureTests(unittest.TestCase):
    def test_download_requires_gap_and_reuses_verified_local_content(self):
        url = "https://patentimages.storage.googleapis.com/aa/bb/US1234567-D00001.png"
        payload = {"publication_number": "US1234567B2", "images": [url], "satisfied_facts": []}
        buffer = io.BytesIO()
        Image.new("RGB", (2, 3)).save(buffer, format="PNG")
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            with patch.object(details, "http_request", return_value=(200, {"Content-Type": "image/png"}, buffer.getvalue())) as request:
                details.retain_figures(root, copy.deepcopy(payload), {}, {}, {})
                request.assert_not_called()
                result = details.retain_figures(root, copy.deepcopy(payload), {"missing_facts": ["representative_figures"]}, {}, {})
                self.assertEqual(request.call_count, 1)
                self.assertTrue(result["media_acquisition"]["complete"])
                self.assertTrue(Path(result["media"][0]["path"]).is_file())
                from trusted_api import _media
                self.assertEqual(len(_media(result)), 1)
                evidence = {"collections": {"patents": [{"payload": result}]}}
                again = details.retain_figures(root, copy.deepcopy(payload), {"missing_facts": ["representative_figures"]}, evidence, {})
                self.assertEqual(request.call_count, 1)
                self.assertTrue(again["media"][0]["reused"])

    def test_unsupported_or_failed_images_are_explicit_gaps(self):
        payload = {"publication_number": "US1234567B2", "satisfied_facts": [], "images": ["http://127.0.0.1/image.png", "https://patentimages.storage.googleapis.com/a.png"]}
        with tempfile.TemporaryDirectory() as temp, patch.object(details, "http_request", side_effect=ProviderError("PROVIDER_NETWORK_ERROR", "failed", "fixture failure")) as request:
            result = details.retain_figures(Path(temp), payload, {"missing_facts": ["representative_figures"]}, {}, {})
        self.assertEqual(request.call_count, 1)
        self.assertEqual(result["media"], [])
        self.assertFalse(result["media_acquisition"]["complete"])
        self.assertEqual([row["error_code"] for row in result["media_acquisition"]["gaps"]], ["PATENT_FIGURE_URL_UNSUPPORTED", "PROVIDER_NETWORK_ERROR"])


class NationalRecordSemanticsTests(unittest.TestCase):
    @patch.object(euipo, "source_profile", return_value=("production", True))
    def test_euipo_applicants_and_owners_stay_distinct(self, _):
        raw = {"applicationNumber": "012345", "status": "Registered", "applicants": [{"name": "Applicant"}], "owners": [{"name": "Current owner"}], "niceClasses": [20]}
        value = euipo.verified_detail("trademark", "012345", raw, [], "trademark_word", retrieval_workflow_revision=V3)
        self.assertEqual(value["owners"], ["Current owner"])
        self.assertEqual(value["applicants"], ["Applicant"])
        del raw["owners"]
        value = euipo.verified_detail("trademark", "012345", raw, [], "trademark_word", retrieval_workflow_revision=V3)
        self.assertEqual(value["owners"], [])
        self.assertIn("owner", value["missing_facts"])
        legacy = euipo.verified_detail("trademark", "012345", raw, [], "trademark_word")
        self.assertEqual(legacy["owners"], ["Applicant"])

    def test_inpi_applicant_tags_are_not_holder_tags(self):
        body = b'<notice><PUBN>FR1234567B1</PUBN><DENM>Applicant</DENM><TINM>Current holder</TINM><PatentCurrentStatusCode>EXPIRED</PatentCurrentStatusCode></notice>'
        item = {"identifier": "FR1234567B1", "jurisdiction": "FR", "right_type": "patent"}
        value = inpi.normalize_notice(body, item, retrieval_workflow_revision=V3)
        self.assertEqual(value["owners"], ["Current holder"])
        self.assertEqual(value["applicants"], ["Applicant"])
        self.assertEqual(value["legal_status"], "EXPIRED")
        self.assertEqual(inpi.normalize_notice(body, item)["owners"], ["Applicant", "Current holder"])

    def test_inpi_partial_valid_record_is_success_with_gaps(self):
        item = {"query_id": "Q", "operation": "candidate_verification", "q": "FR1234567", "identifier": "FR1234567", "jurisdiction": "FR", "right_type": "patent"}
        body = b'<notice><PUBN>FR1234567B1</PUBN><DENM>Applicant</DENM></notice>'
        with tempfile.TemporaryDirectory() as temp, patch.object(inpi, "load_action", return_value=(api_task(), item, {})), patch.object(inpi, "enforce_task_limit"), patch.object(inpi, "load_skill_config", return_value={}), patch.object(inpi, "assert_test_endpoint"), patch.object(inpi, "credential", return_value="fixture-key"), patch.object(inpi, "InpiSession") as session, patch.object(inpi, "record_result", side_effect=lambda _, **kwargs: kwargs), patch.dict("os.environ", {"LC_IPR_TEST_MODE": "0"}):
            session.return_value.call.return_value = body
            value = inpi.execute(Path(temp), "Q")
        self.assertEqual(value["status"], "success")
        self.assertEqual(value["error_code"], "")
        self.assertIn("owner", value["normalized"]["missing_facts"])

    def test_jpo_registration_event_and_applicant_do_not_become_current_facts(self):
        progress = {"applicationNumber": "2020123456", "inventionTitle": "Device", "applicantAttorney": [{"applicantAttorneyClass": "1", "name": "Applicant"}]}
        registration = {"applicationNumber": "2020123456", "registrationNumber": "1234567"}
        value, _, _ = jpo.normalize_verification("patent", "2020123456", progress, registration, {}, retrieval_workflow_revision=V3)
        self.assertEqual(value["owners"], [])
        self.assertEqual(value["applicants"], ["Applicant"])
        self.assertEqual(value["legal_status"], "")
        self.assertEqual(value["registration_event"]["number"], "1234567")
        self.assertNotIn("jplatpat_fixed_url", value["missing_facts"])
        with self.assertRaises(ProviderError):
            jpo.normalize_verification("patent", "2020123456", progress, {**registration, "applicationNumber": "2020123457"}, {}, retrieval_workflow_revision=V3)

    def test_jpo_v3_skips_api_call_used_only_to_get_browser_url(self):
        client = object.__new__(jpo.JpoApiClient)
        def response(right, endpoint, number):
            data = {"applicationNumber": number, "inventionTitle": "Device"}
            if endpoint == "registration_info":
                data["rightPersonInformation"] = [{"rightPersonName": "Current holder"}]
            return data, {}, json.dumps(data).encode()
        with patch.object(client, "_get", side_effect=response) as request:
            value, _, _, _, _ = client.verify("patent", "2020123456", retrieval_workflow_revision=V3)
        self.assertEqual([call.args[1] for call in request.call_args_list], ["app_progress", "registration_info"])
        self.assertEqual(value["owners"], ["Current holder"])

    def test_epo_v3_preserves_applicants_without_claiming_ownership(self):
        body = b'<world><biblio-search total-result-count="1"><search-result><exchange-document country="EP" doc-number="1234567" kind="B1"><applicant-name><name>Applicant</name></applicant-name></exchange-document></search-result></biblio-search></world>'
        value = epo.normalize_search(body, include_biblio=True, retrieval_workflow_revision=V3)[0]
        self.assertEqual(value["applicants"], ["Applicant"])
        self.assertNotIn("owners", value)
        self.assertEqual(epo.normalize_search(body, include_biblio=True)[0]["owners"], ["Applicant"])

    def test_epo_content_requires_real_document_identity(self):
        body = b'<fulltext-document country="EP" doc-number="1234567" kind="B1"><claims><claim>A hinge.</claim></claims></fulltext-document>'
        result = epo.normalize_detail("fulltext", "EP1234567B1", body, retrieval_workflow_revision=V3)
        self.assertEqual(result["candidates"][0]["claims"], ["A hinge."])
        with self.assertRaises(ProviderError):
            epo.normalize_detail("biblio", "EP1234567B1", b'<root><invention-title>Unbound title</invention-title></root>', retrieval_workflow_revision=V3)


if __name__ == "__main__":
    unittest.main()
