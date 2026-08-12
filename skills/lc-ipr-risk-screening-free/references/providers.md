# Provider contracts

## Routing

- All tasks: visible Chrome CDP Amazon capture, SerpApi Google Patents, and Serper Patents/Search/Images. EPO OPS is required primary discovery for non-US and a US low-risk gate.
- US: operator-performed WIPO PATENTSCOPE recall, EPO OPS, SerpApi/Serper supplementation, USPTO Patent Public Search CDP recall and candidate verification, plus USPTO TM Search and TSDR CDP for trademarks. Signa and RapidAPI USPTO Trademark are optional cross-recall only.
- EU: EUIPO Trademark Search and Design Search.
- Other jurisdictions: the relevant official database through an operator-confirmed manual checkpoint, with URL and screenshots.

## EPO OPS

Use REST/XML and OAuth client credentials. Treat EPO OPS as global discovery/master data, not conclusive national legal status. Search published data first; fetch bibliographic, family, full text, images, and legal events only for relevant candidates. The runtime quota signal overrides the documented free allowance. For US tasks, probe it without blocking credential preflight; an unfinished planned OPS query prohibits a final `极低` or `低` conclusion but does not erase detected higher risk.

## WIPO PATENTSCOPE and Espacenet

At `https://patentscope.wipo.int/`, the operator must manually submit and read every planned low-frequency query. Preserve the rendered final URL and screenshot, set `capture_transport=manual` and `operator_confirmed=true`, and ingest one capture per query with `record_patent_browser_recall.py`. CDP must not submit the query or extract the result DOM. Do not automate `https://worldwide.espacenet.com/`; use EPO OPS instead. `espacenet_browser` remains legacy-only for existing `2.1-free` artifacts.

## USPTO Patent Public Search

Use visible Chrome CDP at `https://ppubs.uspto.gov/basic/`. Execute every planned query through `record_patent_browser_recall.py`, then use `record_uspto_patent_chrome_verification.py` for each material candidate. If manual WIPO, EPO OPS, or this recall route cannot finish, do not issue a US `极低` or `低` conclusion. A material candidate without verified USPTO evidence still blocks every final grade.

## SerpApi Google Patents

Use `engine=google_patents`, allow cache, and enforce six searches per task. Validate `search_metadata.status` and `organic_results`. The account endpoint is the free-plan/quota preflight source. Account-wide quota, not a patent-only quota, controls availability.

## Serper

Use `patents`, `search`, and `images`. Probe `lens` at runtime and keep it optional because availability can vary. Never expose the `X-API-KEY` header. Serper results are discovery evidence only.

## Signa

Authenticate with Bearer token. It is mandatory for non-US trademark recall and optional for US cross-recall. Before a required task, inspect `/v1/offices` and verify target office code, production state (`live` in the current API; accept legacy `production`), sync date, record count, known-mark result, record `source_data_date`, and figurative-image availability where relevant. Marketing coverage claims never override runtime evidence.

## RapidAPI USPTO Trademark

Use `/v1/databaseStatus` for an optional availability probe and `/v1/trademarkSearch/{keyword}/{searchType}` for an optional US cross-recall source. `keyword` and `searchType` (`active` or `all`) are required path parameters, not query parameters. Send credentials in `X-RapidAPI-Key` and `X-RapidAPI-Host`. A RapidAPI failure does not block a US task; TSDR in Chrome desktop remains the official candidate verifier.

## USPTO TM Search

Use visible Chrome CDP at `https://tmsearch.uspto.gov/` for mandatory US trademark candidate recall. Execute every documented exact, phrase, and prefix query in `search-plan.json`; save the rendered query, a distinct result screenshot path, and final official URL for each capture. Use Signa/RapidAPI as optional phonetic/fuzzy cross-recall.

For `success`, retain every candidate's eight-digit serial number and mark text. `no_result` is valid only when the rendered official result confirms zero candidates and the capture includes a non-empty result message. CAPTCHA is `needs_user_action`; an inaccessible page, incomplete rendering, or unconfirmed zero result is `access_limited` or `failed`, never `no_result`.

## USPTO TSDR and Patent Public Search

The TSDR API is not used. Use visible Chrome CDP for all USPTO official verification. Recall trademarks in `https://tmsearch.uspto.gov/`, then open `https://tsdr.uspto.gov/` and record each candidate with `record_tsdr_browser_verification.py`. For patents and designs, open `https://ppubs.uspto.gov/basic/` and record each material candidate with `record_uspto_patent_chrome_verification.py`. Do not default to the Patent Public Search `external.html` Advanced SPA.

Every USPTO capture must declare `browser=chrome_desktop`, `capture_transport=cdp`, browser/protocol version, and a sanitized session ID. TM Search capture binds each query and strategy to the rendered result, final official URL, checked time, screenshot SHA-256, and either candidates or a rendered zero-result message. TSDR capture binds the same eight-digit serial across request, rendered page, and final official URL, with status, owners, goods/services, optional registration number and mark image, checked time, and screenshot SHA-256. Patent Public Search capture binds the record number across request and rendered page, and includes title, owners, legal status, final official URL, checked time, screenshot SHA-256, and relevant design views. An official valid no-case response is `no_result`; CAPTCHA is `needs_user_action`; an unverified material candidate blocks final grading.

## EUIPO

Use OAuth client credentials, Bearer access token, and `X-IBM-Client-Id`. Confirm subscriptions to both search products at preflight and cache tokens only in memory. Search candidates remain `not_checked`. A trademark becomes verified only after `GET /trademarks/{applicationNumber}` and, when present, `/image`; a design becomes verified only after `GET /designs/{designNumber}` and at least one `/views/{order}` response. Design text/classification search is not image similarity.

## Secret and failure rules

Read credentials from environment first and local config second. Save the raw body before normalization. Strip request headers and URL query keys from evidence. Classify quota, plan, auth, stale data, and schema drift distinctly. Never retry a paid-plan response with a paid operation.
