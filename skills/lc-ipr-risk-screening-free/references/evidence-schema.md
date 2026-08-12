# Task and evidence contract

## Files

- `task.json`: identity request, routing, state, checkpoints, gaps, errors, and outputs.
- `evidence.json`: normalized source runs and evidence collections.
- `assessment.json`: deterministic finalization result.
- `search-plan.json`: traceable queries.
- `normalized-candidates.json`: deduplicated patent and trademark candidates.
- `first-review.json` and optional `second-review.json`: independent AI reviews.

## Task identity

`product.requested_asin` is parsed from the submitted URL. `product.actual_asin` is populated only by accepted browser evidence. A mismatch is a blocking error. `images` contains exactly one accepted main-image record with absolute path, HTTPS source URL, MIME type, dimensions, SHA-256, and collection time.

## Source runs

Every run contains `run_id`/`attempt_id`, stable `query_id`, provider, operation, display query, sanitized request parameters, jurisdiction, timestamps, allowed status, evidence type, raw paths, payload digest, error code, retry count, quota summary, data date, and optional coverage object.

Use only statuses `success`, `no_result`, `not_applicable`, `needs_user_action`, `access_limited`, and `failed`. `query_id` represents one complete logical request, including all non-secret filters. `attempt_id` represents one execution. Raw paths contain query identity and payload digest, so grant/application/design variants cannot overwrite one another. A successful attempt clears only the same query's gap.

## Collections

`evidence.json.collections` contains `product`, `patents`, `trademarks`, `copyright_assets`, `enforcement`, `official_verifications`, `browser`, and `blacklist` arrays.

Each material patent, design, or trademark candidate includes:

```json
{
  "evidence_id": "EV-...",
  "material": true,
  "official_verification": {
    "status": "verified",
    "source": "USPTO",
    "url": "https://...",
    "checked_at": "..."
  }
}
```

Official statuses are `verified`, `no_result`, `access_limited`, and `not_checked`. Material `access_limited` or `not_checked` blocks a final grade.

## Browser capture provenance

Schema `2.2-free` keeps `browser=chrome_desktop` and adds transport provenance:

- Amazon and USPTO: `capture_transport=cdp`, non-empty `browser_version`, `protocol_version`, and a sanitized `cdp_session_id`.
- WIPO PATENTSCOPE: `capture_transport=manual` and `operator_confirmed=true`. The operator submits and reads the query; CDP must not automate or extract the result DOM.
- Never serialize CDP endpoints, WebSocket URLs, ports, profile paths, cookies, local storage, or passwords.

USPTO API routes are not used. For TSDR, pass a CDP JSON object to `record_tsdr_browser_verification.py`; a successful capture contains matching eight-digit `serial_number` and `page_case_number`, an official HTTPS `final_url` containing that serial, `case_status`, non-empty `owners`, non-empty `goods_services`, `checked_at`, and an existing `screenshot_path`. `registration_number`, `mark_text`, and `mark_image_path` are optional. The recorder calculates screenshot and mark-image hashes, retains `capture_transport=cdp`, and emits `official_verification.method=chrome_desktop`.

For mandatory US candidate recall, pass one rendered USPTO TM Search CDP result to `record_uspto_tmsearch_browser_result.py`. It requires strategy `exact`, `phrase`, or `prefix`, non-empty `query` and `rendered_query`, an official HTTPS `final_url` on `tmsearch.uspto.gov`, recent `checked_at`, and a screenshot inside the task. A screenshot path cannot be reused for another strategy/query. Phonetic/fuzzy discovery belongs to optional Signa/RapidAPI cross-recall.

For every planned WIPO or Patent Public Search recall, pass one rendered result to `record_patent_browser_recall.py` using `--provider wipo_patentscope_browser` or `uspto_patent_browser`. A successful capture has one or more candidates, each with a non-empty title and at least one publication, application, grant, or record number. A `no_result` capture has an empty `candidates` array and a non-empty `result_message`. Espacenet browser captures are accepted only for legacy `2.1-free` tasks; new tasks use EPO OPS. Manual WIPO, EPO OPS, and USPTO recall are low-risk clearance gates.

A Patent Public Search CDP capture is ingested with `record_uspto_patent_chrome_verification.py`. It has matching non-empty `record_number` and `page_record_number`, an allowed official HTTPS final URL containing the record number, recent checked time, and a screenshot inside the task. A successful capture additionally contains title, legal status, and non-empty owners. Add official drawings/figure pages through `evidence_images`, each with `path`, `label`, and `role`; the recorder calculates their hashes and the report displays them as key evidence. A confirmed `no_result` requires a non-empty `result_message`.

`browser-candidate-journal.json` records every patent detail opened through the CDP verifier before deep parsing completes. Each entry binds provider, normalized record number, opened time, sanitized official URL, processing status, and—when available—capture/screenshot paths. `pending`, `needs_user_action`, `access_limited`, or `failed` entries prohibit a completed assessment and must remain visible in the report. A `success` entry must resolve to an officially verified normalized candidate. USPTO `requestToken` and similar query credentials are never persisted.

## Coverage gaps

Each gap records provider, `query_id`, jurisdiction, status, error code, affected modules, detail, and timestamp. Every required planned query must reach `success`, `no_result`, or an explicitly valid `not_applicable` status. An attempted optional source with no valid terminal result caps confidence and prohibits an `极低` conclusion.
