---
name: lc-ipr-risk-screening-free
description: Screen one Amazon product for patent, pending-application, design, word-mark, figurative-mark, trade-dress, copyright, character-IP, and enforcement risks using free-tier discovery APIs plus official registries. Use only when explicitly invoked for an ASIN or Amazon product URL and the user wants browser-collected Amazon facts, one current-variant main image, traceable JSON evidence, independent review, and Markdown/HTML reports without SellerSprite, Trohub, Feishu, batch queues, or automatic paid usage. This is an operational risk screen, not legal advice.
---

# LC IPR Risk Screening Free

Run one traceable Amazon intellectual-property screen with free-tier sources. Keep discovery, official verification, and AI assessment separate. Never convert missing evidence into a low-risk conclusion.

## Mandatory boundaries

- Read `INSTRUCTIONS.md` and run its cloud authorization command as the first business action of every invocation. Before it passes, do not inspect business input, read business references, create a task directory, open Amazon, start Chrome/CDP, or call any provider. When authorization fails, relay both the fixed stop message and the safe reason emitted by `scripts/auth_gate.py`, then stop immediately.
- After the first authorization passes, run `scripts/preflight.py --phase credentials` at the original workflow position before opening Amazon or collecting product facts. Its repeated internal authorization check is a non-billing safeguard and does not replace the mandatory first action.
- Use visible Chrome desktop over Playwright CDP for Amazon, USPTO TM Search, TSDR, and Patent Public Search. Use a dedicated non-default Chrome profile and loopback-only random debugging port. Never persist the endpoint, port, profile path, cookies, local storage, or passwords in task evidence.
- Perform every WIPO PATENTSCOPE query manually. CDP may save the operator-confirmed screenshot only; it must not submit the query or extract the result DOM. Do not automate Espacenet; use EPO OPS for automated patent retrieval. Never scrape SellerSprite and never call Trohub.
- Use only the current Amazon variant and one main image. Record browser screenshots and the final ASIN/variant.
- Never pay, upgrade, or enable overage automatically. Preserve collected evidence and set the task to `incomplete` when required free access is unavailable.
- Keep secrets in environment variables or `config.local.json`. Never print credentials, place them in raw evidence, or publish them.
- Use third-party services only for discovery. Officially verify every material patent, design, or trademark candidate before final grading.
- Do not call the USPTO TSDR API. For US patent work, use manual WIPO PATENTSCOPE recall, EPO OPS, SerpApi/Serper supplementation, then USPTO Patent Public Search CDP recall and candidate verification. Verify US trademark candidates in TSDR. A material candidate without official verification blocks final grading; an unfinished WIPO, EPO OPS, or USPTO Patent Public Search recall can never support a final low-risk conclusion.

## Required reading

0. Read and execute `INSTRUCTIONS.md`; continue only after cloud authorization passes.
1. Read `references/workflow-business-logic.md` before running a task.
2. Read `references/evidence-schema.md` before writing task or evidence files.
3. Read `references/providers.md` before any API collection.
4. Read `references/browser-product-capture.md` before opening Amazon.
5. Read `references/trademark-copyright.md` when names, logos, artwork, packaging graphics, characters, or licensed assets appear.
6. Read `references/risk-rules.md` before either review.
7. Read `references/official-sources.md` before official verification.

## Workflow

0. Run the cloud authorization gate from `INSTRUCTIONS.md`. This is the first business action and must complete before reading or processing the Amazon input.
1. After authorization passes, create a task shell from the Amazon URL with `scripts/create_task.py`. Do not require title, brand, or image at this stage.
2. Run credential preflight. It checks the repeated cloud safeguard, required keys, runtime free-access signals, required Signa coverage for non-US tasks, the non-blocking US EPO OPS low-risk gate, and jurisdiction-specific providers. In EUIPO Sandbox, use fixed fixture `000000013-0001` to verify Design Detail, view metadata, one View, and its Thumbnail; never use this fixture as product evidence or in Production. USPTO TM Search is the fixed US trademark-recall route in visible Chrome CDP; any missing mandatory source forces `incomplete`.
3. Install the pinned CDP runtime once with `npm ci --ignore-scripts --prefix tools/cdp`, then run `node tools/cdp/cdp-cli.mjs doctor`. After credential preflight, capture Amazon with `capture-amazon`. Save the two required screenshots, one main image, and a browser-capture JSON matching `references/browser-product-capture.md`.
4. Ingest the capture with `scripts/record_browser_product.py`, then run evidence preflight with `--cdp-capability-confirmed`. ASIN mismatch, unknown variant, an absent/changed main image, or unavailable visible Chrome CDP prevents full grading.
5. Generate `search-plan.json` with `scripts/generate_search_plan.py`. Every entry has a stable `query_id`, required/optional flag, execution wave, complete non-secret request parameters, and Amazon/image provenance. Never edit away failed planned queries.
6. For US, run patent discovery in this order: operator-performed WIPO PATENTSCOPE recall → EPO OPS → SerpApi Google Patents/Serper Patents supplement → USPTO Patent Public Search CDP recall and official verification. Record WIPO and USPTO recall with `scripts/record_patent_browser_recall.py`; use `scripts/record_uspto_patent_chrome_verification.py` for every material candidate. EPO OPS failure remains a low-risk gate rather than a blocker for detected higher risk. For non-US, EPO OPS remains a required primary source, followed by SerpApi, Serper, and the applicable official registry.
7. For US, run exact, phrase, and prefix trademark recall with `run-planned-query` in USPTO TM Search. Record the rendered query and distinct screenshot for each query/strategy, then verify material candidates with `verify-candidate` in TSDR. Use optional Signa/RapidAPI for phonetic/fuzzy cross-recall only. For EU and other non-US tasks, probe Signa coverage first; EUIPO search is discovery until its official detail and image/view endpoints complete.
8. For EU designs, discover via patent sources, search EUIPO Design by text/Locarno, and compare all official views to the Amazon main image manually. EUIPO Design is not reverse-image search.
9. Run `scripts/blacklist_check.py`, then use Serper Images, Serper Web, optional runtime-probed Serper Lens, official mark images, and `assets/high-risk-ip.json` for copyright, character, figurative-mark, trade-dress, and enforcement evidence.
10. Record every operator-confirmed WIPO capture with `capture_transport=manual` and `operator_confirmed=true`. Record USPTO CDP captures with `capture_transport=cdp`, browser/protocol version, and sanitized session ID. Use `scripts/record_provider_result.py` for non-US manual official registries. Then normalize with `scripts/merge_candidates.py`.
11. Write `first-review.json` from evidence only. Include `review_context.session_id`, the evidence/candidate SHA-256 digest, and `first_review_visible=false`. When required, run the second review in a different session with the same input digest and without exposing the first review.
12. Generate the fixed `IPR Evidence Dossier v1.0` outputs (`report.md`, `report.html`, and `report-manifest.json`) with `scripts/build_report.py`. Include the Amazon main image and material USPTO/EUIPO drawings, figures, details, TSDR, and other key screenshots with hashes. Finish with `scripts/validate_run.py`.

## Browser bridge

Use `tools/cdp/cdp-cli.mjs` for visible Amazon and USPTO work. It launches or reconnects to a dedicated Chrome profile, binds CDP to loopback on a random port, and stores its protected runtime descriptor outside task evidence. Pass generated capture JSON to the matching Python recorder. Search and detail pages are complete only after the required semantic fields remain unchanged for the configured consecutive samples; `domcontentloaded` or a fixed sleep is not sufficient. When a patent PDF/figure view is opened, wait for a stable rendered frame and preserve it as an evidence image. Record every opened patent detail in `browser-candidate-journal.json`; unresolved entries block a completed assessment and must remain visible in the report. Treat CAPTCHA, login, uncertain rendering, and CDP timeout as `needs_user_action` or `access_limited`; refresh visible page state before deciding whether an action completed, and never resubmit solely because the client timed out. Strip `requestToken`, access tokens, and similar query credentials from persisted URLs. Never inspect cookies, local storage, the default Chrome profile, or passwords.

## State and evidence rules

Use task states:

`pending -> preflight_credentials -> awaiting_browser -> preflight_evidence -> collecting -> ready_for_assessment -> assessing -> needs_review/completed`

Use `needs_user_action`, `incomplete`, or `failed` for abnormal outcomes. Use only source statuses:

`success`, `no_result`, `not_applicable`, `needs_user_action`, `access_limited`, `failed`.

`no_result` means a successful request with a valid response schema and zero candidates. Missing credentials, stale data, quota limits, CAPTCHA, or schema drift are never `no_result`.

## Output rules

- Write task output under `/Users/laochen/Documents/产品专利等知识产权排查/runs-free/` by default; never write runtime data inside either Skill installation directory.
- Keep raw API responses out of reports and reference them from `evidence.json`.
- Cite an evidence ID, URL, screenshot, or raw path for every finding.
- Keep module risk and confidence separate. Use risks `极低`, `低`, `中`, `高`, `极高` and confidence `低`, `中`, `高`.
- Output no final risk grade when a mandatory source fails or a material candidate lacks official verification.
- For a US task, if any planned manual WIPO PATENTSCOPE, EPO OPS, or USPTO Patent Public Search recall is unfinished, a final `极低` or `低` result is prohibited. The final overall conclusion is capped at `中` with low confidence; detected higher risk remains reportable.
- With only one main image, cap copyright, figurative-mark, and trade-dress confidence at `中`.
- Include the disclaimer that the report is a seller-operations screen, not licensed legal advice.

## Commands

```bash
python scripts/auth_gate.py
python scripts/create_task.py --url "https://www.amazon.com/dp/B012345678" --jurisdictions US
python scripts/preflight.py --task /absolute/run/task.json --phase credentials
node tools/cdp/cdp-cli.mjs doctor
node tools/cdp/cdp-cli.mjs capture-amazon --task-dir /absolute/run
python scripts/record_browser_product.py --task-dir /absolute/run --capture /absolute/browser-capture.json
python scripts/preflight.py --task /absolute/run/task.json --phase evidence --cdp-capability-confirmed
python scripts/generate_search_plan.py --task-dir /absolute/run
python scripts/run_api_plan.py --task-dir /absolute/run --wave 1
python scripts/record_patent_browser_recall.py --task-dir /absolute/run --provider wipo_patentscope_browser --capture /absolute/wipo-browser-capture.json
node tools/cdp/cdp-cli.mjs run-planned-query --task-dir /absolute/run --query-id QRY-...
python scripts/record_patent_browser_recall.py --task-dir /absolute/run --provider uspto_patent_browser --capture /absolute/uspto-patent-recall-capture.json
python scripts/record_uspto_tmsearch_browser_result.py --task-dir /absolute/run --capture /absolute/tmsearch-browser-capture.json
node tools/cdp/cdp-cli.mjs verify-candidate --task-dir /absolute/run --provider uspto_tsdr --record 12345678
python scripts/record_tsdr_browser_verification.py --task-dir /absolute/run --capture /absolute/tsdr-browser-capture.json
python scripts/record_uspto_patent_chrome_verification.py --task-dir /absolute/run --capture /absolute/uspto-patent-chrome-capture.json
python scripts/blacklist_check.py --task-dir /absolute/run
python scripts/merge_candidates.py --task-dir /absolute/run
python scripts/finalize_assessment.py --task-dir /absolute/run --first-review /absolute/run/first-review.json
python scripts/build_report.py --task-dir /absolute/run
python scripts/validate_run.py --task-dir /absolute/run
```
