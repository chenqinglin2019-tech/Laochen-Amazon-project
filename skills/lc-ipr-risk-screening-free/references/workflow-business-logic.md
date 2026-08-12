# Runtime business logic

## 1. Task shell

`create_task.py` receives an Amazon URL containing an ASIN, optional jurisdictions, and optional output directory. It parses only the Amazon host, marketplace, URL ASIN, and requested jurisdictions. It creates `task.json`, `evidence.json`, `assessment.json`, `raw/`, `images/`, and `screenshots/` under `/Users/laochen/Documents/产品专利等知识产权排查/runs-free/<ASIN>_<UTC date-time>/` unless an explicit directory is supplied.

No product conclusion is made here. The URL ASIN is a request identity, not confirmed product identity. The task starts at `pending` and lists mandatory providers derived from target jurisdiction.

## 2. Credential preflight

`preflight.py --phase credentials` performs the following in order:

1. Run the bundled cloud-auth binary with local config. A failure stops before Amazon product data is read.
2. Resolve credentials from environment variables first, then `config.local.json`; never serialize secret values.
3. Probe each provider with the smallest read-only request available.
4. Classify HTTP 401/403 as `AUTH_FAILED` unless the response explicitly identifies plan access; classify 402 or a paid-plan response as `PAID_PLAN_REQUIRED`; classify 429 with exhausted quota as `FREE_QUOTA_EXHAUSTED`.
5. Record response headers or account fields that describe remaining quota without recording credentials.
6. When Signa is required for a non-US task, probe `/v1/offices`, select target offices, verify production availability (`live` or legacy `production`), sync date, record count, and a known-mark sample. A target office that fails any coverage test is `COVERAGE_UNVERIFIED` or `SOURCE_DATA_STALE`.
7. For EU targets, require active subscriptions for both EUIPO Trademark Search and Design Search. For US targets, probe EPO OPS as a non-blocking low-risk gate and require visible Chrome CDP capability for Amazon, USPTO TM Search, TSDR, and Patent Public Search. WIPO remains an operator-confirmed manual checkpoint. Signa and RapidAPI are optional US cross-recall sources. The TSDR API is deliberately disabled. For other jurisdictions, require a manual official-registry checkpoint.
8. Persist provider results to `evidence.json`. Any mandatory failure sets `incomplete`; no automatic paid request or silent replacement is allowed.

Successful credential preflight changes the task to `awaiting_browser`. CDP capability is confirmed later with `cdp-cli.mjs doctor` and `preflight.py --phase evidence --cdp-capability-confirmed`. The disabled TSDR API route is recorded as `not_applicable` and cannot satisfy candidate verification. An unavailable US EPO OPS account does not block credential preflight, but its planned queries remain a low-risk clearance gate.

## 3. Amazon CDP collection

After credential preflight, `tools/cdp/cdp-cli.mjs capture-amazon` opens the supplied URL in visible dedicated Chrome and records requested/final URL, requested/actual ASIN, current variant, title, brand, manufacturer, category, bullets, specifications, and visible patent/copyright/license claims. It saves:

- one screenshot of the product core area;
- one screenshot of product details;
- exactly one current-variant main image;
- the original HTTPS image URL;
- a capture JSON.

`record_browser_product.py` requires `capture_transport=cdp` plus sanitized browser/protocol/session provenance and rejects a robot-check capture, final-ASIN mismatch, unknown current variant, non-HTTPS main image URL, multiple main images, missing files, mismatched SHA-256, or serialized CDP connection details. A robot check sets `needs_user_action`; identity or image gaps set `incomplete`.

## 4. Evidence preflight

`preflight.py --phase evidence --cdp-capability-confirmed` verifies the accepted Amazon capture, screenshot files, image format/hash/dimensions, explicit jurisdictions, jurisdiction/source routing, recent credential-preflight records, required Signa coverage, and visible Chrome CDP capability. It records WIPO as manual and USPTO as CDP. Success moves the task to `collecting`. Legacy `2.1-free` tasks retain the old capability flags.

## 5. Search plan

`generate_search_plan.py` derives queries from browser evidence. Each term is an object with `value`, `kind`, and `derived_from`. Sources include title, brand, manufacturer, bullets, specifications, structure, OCR, and agent-supplied visual features. The plan groups:

- generic category terms;
- structural/functional terms;
- ornamental-design terms;
- brand/model/series/slogan text;
- owner/assignee clues;
- IPC/CPC/Locarno/Nice candidates;
- per-provider requests and limits.

Query caps come from `config.json`. A plan may narrow or combine terms but may not invent undocumented product features.

## 6. Patent collection

For US, the fixed patent chain is `operator-performed WIPO PATENTSCOPE recall -> EPO OPS -> SerpApi Google Patents / Serper Patents supplement -> USPTO Patent Public Search CDP recall and candidate verification`. For non-US, the fixed discovery order remains EPO OPS, SerpApi Google Patents, Serper Patents, then Serper Web.

- WIPO PATENTSCOPE queries are submitted and read by the operator. Each planned low-frequency query produces a rendered URL, screenshot, checked time, `capture_transport=manual`, `operator_confirmed=true`, and candidate/zero-result capture through `record_patent_browser_recall.py`. CDP may save the screenshot only; it must not submit the query or extract the result DOM.
- Espacenet browser automation is disabled for new tasks. Existing `2.1-free` captures remain readable.
- EPO OPS obtains OAuth, searches published data, and stores XML. It initially requests bibliographic search results. Family, full text, images, and legal events are fetched only for relevant candidates, bounded by `epo_candidate_detail_limit`. In US work an unfinished planned OPS query prohibits a final low-risk conclusion but never represents absence of patent risk.
- SerpApi sends at most six searches per task with `country`, `status`, `type`, `assignee`, `inventor`, and optional date filters. It accepts only `search_metadata.status=Success` with an array-shaped `organic_results`.
- Serper Patents provides a separate index. Serper Web searches assignees, enforcement, litigation, and public patent claims. Neither is official verification.

All clients save the raw response before normalization. Quota/access/schema errors become source runs and coverage gaps, never zero-result conclusions.

## 7. Trademark collection

For a non-US task where Signa is required, it begins with office coverage validation. Search executes four strategies: `exact`, `phonetic`, `fuzzy`, and `prefix`, with target office, Nice class, live/current status, goods/services, and owner clues where known.

For US:

`USPTO TM Search visible Chrome CDP recall -> merge -> TSDR visible Chrome CDP verify`

Execute every planned `exact`, `phrase`, and `prefix` query in `https://tmsearch.uspto.gov/` through visible Chrome CDP. Record the rendered query, strategy, final URL, distinct screenshot path, and result with `record_uspto_tmsearch_browser_result.py`; use optional Signa/RapidAPI for phonetic/fuzzy cross-recall. A zero result is valid only when the official rendered page confirms it; CAPTCHA or incomplete rendering is a mandatory gap. TSDR receives serial numbers from TM Search candidates and verifies each material candidate.

If every required TM Search query validly returns zero candidates, TSDR is `not_applicable`. If a candidate exists, at least one `candidate_verification` run must exist and every material candidate must carry `official_verification.status=verified`. CAPTCHA or an inaccessible official page creates a mandatory gap and produces `incomplete`. Signa and RapidAPI may be run as optional US cross-recall, but their absence or failure cannot replace or block the required TM Search route.

## 7a. US patent and design official verification

For US patent recall, execute every planned WIPO query manually, every EPO OPS query through its API, and every Patent Public Search query through visible Chrome CDP. Each source is a low-risk clearance gate: a missing, CAPTCHA-blocked, quota-blocked, or otherwise incomplete source does not erase detected higher risk, but prohibits a final `极低` or `低` conclusion. For every material US patent or design candidate, use visible Chrome CDP to open `https://ppubs.uspto.gov/basic/` and search the record number. Prefer Basic Search because it is the supported low-friction entry; do not use the `external.html` Advanced SPA as the default route. Capture the matching rendered record number, title, owner/assignee, legal status, final official URL, checked time, screenshot, and relevant design views. Ingest it with `record_uspto_patent_chrome_verification.py`; each capture must declare CDP provenance. A material candidate with no validated capture blocks final grading.

For EU trademarks:

`Signa EUIPO recall -> EUIPO Trademark Search -> detail/image`

For EU designs:

`EPO/SerpApi/Serper discovery -> Locarno/text search -> EUIPO Design detail/all views -> agent visual comparison`

## 8. Copyright, character, and trade dress

The agent uses the single Amazon main image, Serper Images/Web, runtime-probed optional Lens, official trademark/design images, OCR, and the local high-risk IP list. A registry zero result does not negate copyright. Unknown provenance for a central pattern is at least medium risk. One-image coverage caps copyright, figurative-mark, and trade-dress confidence at medium.

## 9. Candidate normalization

`merge_candidates.py` reads normalized collection entries and creates `normalized-candidates.json`.

Patent keys prefer DOCDB publication number, then application/grant number plus jurisdiction and kind code; family IDs form a second grouping key. Trademark keys prefer office plus application/serial/registration number, falling back to normalized text and figurative identifier.

Every merged candidate retains source IDs, queries, collection times, raw paths, relevance, freshness, and official-verification objects. Merging never deletes conflicting source claims.

## 10. Assessment and report

The first reviewer reads evidence, normalized candidates, methodology, and risk rules. The second reviewer, when triggered, receives the same inputs but not the first review. `finalize_assessment.py` validates all seven modules, evidence references, source completeness, and material-candidate official verification.

Mandatory failure or unverified material rights yields `incomplete` with no overall grade. High/extreme risk or any uncertainty trigger yields `needs_review`. Two completed reviews that differ by two or more levels require human review; otherwise the more conservative review prevails.

`build_report.py` renders the fixed `IPR Evidence Dossier v1.0` into Markdown and responsive/printable HTML, plus `report-manifest.json`. It includes the Amazon main image and clearly named or explicitly recorded official drawings, figures, details, TSDR pages, and search screenshots. `validate_run.py` recomputes provider/query coverage and checks report input digests, path containment/hashes, task/assessment state agreement, fixed report schema, and secret absence.
