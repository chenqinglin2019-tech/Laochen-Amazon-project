---
name: lc-amazon-listing-creation
description: 基于 Amazon 空白类目模板和已完成的产品或 Listing 信息，生成并校验可上传的库存上架 Excel/XLSM。
---

# 易逊-上架表格生成

Create a new Amazon inventory upload workbook from product or finished Listing information. Always use an indexed blank Amazon template as the output base. A verified completed workbook may guide field selection, but it is never copied and its old product values are never exposed.

## Authorization Gate

Before reading or processing any business input, creating a project directory, or running any workflow command, read `INSTRUCTIONS.md` and complete its cloud authorization check. Continue with the original Scope and Workflow below only after the check returns `auth_passed`. If it fails, report the safe reason from the checker and stop this run; do not bypass the gate or continue the business workflow.

## Scope

- v1 supports new listings and `Create or Replace (Full Update)` only.
- One task handles exactly one marketplace, content language, Product Type, leaf browse node, and product family.
- The user must explicitly provide the marketplace and leaf node. Never infer either silently.
- This skill fills inventory workbooks. It does not research competitor ASINs or generate Listing copy from competitors.

## Required Project Layout

Use the user's project root. Keep template originals in these exact directories:

- `空白模板库/`: mandatory Amazon-downloaded blank workbooks.
- `样板模板库/`: optional completed workbooks that the user confirms Amazon accepted.
- `.amazon-inventory-fill/state.sqlite3`: generated template index, task snapshots, sample verification, and SKU reservations.

Never write an output into either library. Treat every user-provided blank or completed template as read-only: do not edit it in place and do not change its sheet names, headers, styles, dimensions, validations, or formatting. Create output only from a separate blank-template copy and verify the source hash is unchanged.

## Workflow

1. Collect the explicit task scope: marketplace ID, content language, Product Type, leaf browse node, and one product family.
2. Scan and query both libraries with `scripts/manage_template_library.py`.
   - No matching blank template: hard block and ask the user to add one from Amazon.
   - Matching blank but no verified sample: offer to add a sample or ask the user to explicitly approve no-sample mode.
   - A sample is usable only when its status is `user_confirmed` or `report_verified` and it matches the target node.
   - `templateIdentifier` and version are trace data. Cross-version samples are allowed when the technical-field schema is compatible.
3. Resolve the GTIN gate before Mapping creation.
   - Both product ID type and value present: validate the pair.
   - Only one present: block.
   - Both blank: require the user to choose `confirmed_exempt` or `unknown`.
   - `unknown` can only produce `DRAFT_NOT_FOR_UPLOAD`.
   - Write the template's exemption representation only for `confirmed_exempt` and only when the target template supports it.
   - The extractor returns a nonzero exit code when a product row has a one-sided ID or still requires the explicit exemption/unknown choice; callers must also retain the JSON preflight report.
4. Save the task snapshot and reserve each Parent, Child, or Standalone SKU with `scripts/manage_task_state.py`.
   - The immutable snapshot must contain the absolute product workbook path/SHA-256 and the complete selected-template metadata from Mapping v2.
   - A retry of the same task and source row must reuse its reservation.
   - Parent and child SKUs must be unique.
   - Mark reservations validated only after deterministic Mapping validation; commit them only after output validation.
5. Extract deterministic workbook and product context with `scripts/extract_inventory_context.py`.
   - The reference profile is separated by `Parent`, `Child`, or `Standalone` plus variation theme.
   - The profile contains field frequency and verification level, not sample brand, SKU, price, dimensions, IDs, or other values.
   - Target blank-template valid values are authoritative; localized sample enums must be remapped.
6. Use the current model to create Mapping 2.2 according to `references/mapping-schema.md`.
   - `must_fill`: official required fields applicable to the row, triggered conditional fields, and relationship/system fields.
   - `rule_default`: policy-controlled fields. It includes `Item Condition=New` on every row and the Mapping 2.2 sellable-row rules below.
   - `sample_preferred`: fields commonly filled by compatible samples of the same role/theme.
   - `evidence_fillable`: other applicable fields with explicit product evidence.
   - With a sample, use `must_fill ∪ rule_default ∪ sample_preferred ∪ evidence_fillable` when supported by evidence.
   - Without a sample, use `must_fill ∪ rule_default ∪ evidence_fillable`; do not add all conditional fields indiscriminately and do not exclude evidenced Optional/Recommended fields.
   - Copy `product_input` into `inputs.product`. Product-derived fields cite nonblank `Sheet!A1` references; explicit confirmations cite matching `confirmations[]` IDs. Arbitrary provenance labels are invalid.
   - Resolve each verified-sample nonblank field from explicit confirmations, structured product columns, fixed rules, normalized measurements, or high-confidence current-product evidence plus target data definitions.
   - If a same-role/same-theme sample field remains unresolved, write `信息不足，请人工核对` with `manual_review_marker`, add the matching top-level `manual_review[]` item, and force `DRAFT_NOT_FOR_UPLOAD`.
   - Never add the marker for a sample-blank field, in no-sample mode, or to a locally uploadable result.
7. Run `scripts/validate_inventory.py` before writing. Any invalid Mapping must fail.
8. Write with `scripts/write_inventory.py`. It clones the blank template's prototype row, writes a temporary workbook, validates structure, then publishes atomically.
9. Return the validation report and one result status:
   - `DRAFT_NOT_FOR_UPLOAD`
   - `LOCAL_VALIDATION_PASSED`
   - `ACCEPTED_USER_CONFIRMED`
   - `ACCEPTED_REPORT_VERIFIED`
10. After the user confirms Amazon acceptance, register the output in `样板模板库/`. Upgrade to `report_verified` only when an Amazon processing report is attached.

## Field Safety Rules

- Technical field names from `attributeRow` are authoritative; never map by fixed Excel column letters.
- Locate only `Template` or `模板`. Missing inventory sheet is a hard error.
- Do not invent SKU, GTIN, brand, price, dimensions, weight, country of origin, images, batteries, dangerous-goods, compliance, or other objective facts. A reserved SKU and a user-directed deterministic default are not inventions; both must retain their explicit rule provenance.
- Low-confidence compliance, dangerous-goods, battery, origin, and product-identity values stay blank and require confirmation.
- Every mapped field records value, source, confidence, confirmation state, and validation result.
- A product-cell source is checked against the current product workbook hash and actual nonblank cell. A blank cell, changed workbook, fabricated source type, or target-template candidate used as the sole proof of a sensitive fact is blocking.
- Every product data row maps exactly once by its actual row number. `source_key` is fixed as `product-row-<row number>` and the Mapping role must match `父子变体`.
- Mapping 2.2 field-decision sets are mutually exclusive in this order: `must_fill`, `rule_default`, `sample_preferred`, `evidence_fillable`. Mapping 2.0/2.1 retain their historical semantics.
- Numeric `.value` and `.unit` fields are filled as a pair.
- `Item Condition` always uses the target-template candidate `New`.
- A Chinese manual-review marker is a draft annotation, not a product fact. It may intentionally violate numeric or allowed-value constraints only while the task is `DRAFT_NOT_FOR_UPLOAD`.
- Every allowed-value field must use a candidate from the target blank template, never raw sample text.
- Sample blanks do not waive Amazon requirements. Sample nonblanks do not prove universal requirements.
- Parent rows have no product ID pair. Child and Standalone rows follow the GTIN gate.
- Each child must reference an existing Parent SKU and have a unique variation-attribute combination.

## Mapping 2.2 Sellable-row Rules

Apply these rules only to `Child` and `Standalone`; keep `Parent` fields blank unless the target template independently requires them.

- `Model Number` is a hard constraint equal to the current row's reserved SKU.
- `Manufacturer` is a hard constraint equal to the current row's confirmed brand.
- `Model Name`: use an explicit product value first; otherwise derive one concise core-keyword phrase from current title/bullets/description as “core feature words + core product-name words”. Exclude brand, variation size, pack count, price, and promotional language.
- `Part Number`: use an explicit product value first; otherwise use the same core-keyword fallback as Model Name.
- `Number of Items`: use an explicit sellable pack count such as `10PCS`, `Pack of 10`, or `10个装`; otherwise use `1`. Do not count accessories/components in one set as separately sold items.
- `Mounting Type`: remap an explicit value or select the best supported target-template enum from current-product evidence. If confidence is insufficient and the same-role verified sample filled the field, use the exact manual-review marker and keep the file a draft.
- `Fulfillment Channel Code`: remap an explicit method; when absent, use the target template's semantic FBA candidate. For the current US SCULPTURE template this is `Fulfillment by Amazon (NA)`.
- Fixed-rule or model-rule records use Mapping 2.2 rule IDs. The validator cross-checks Model Number against SKU, Manufacturer against Brand, fallback keyword consistency, positive item count, target enums, and deterministic measurement conversions.

## Product Spreadsheet

Read the first visible sheet. The supported columns are:

`父子变体`, `标题`, `副标题`, `关键词栏`, `五点描述1`–`五点描述5`, `长描`, `主图链接`, `附图1链接`–`附图7链接`, `Swatch Image链接`, `产品详细介绍`, `商品编号类型`, `商品ID`.

Rule-controlled and offer columns:

`品牌`, `型号名称`, `零件编号`, `销售件数`/`装数`, `安装方式`, `发货方式`/`物流渠道`, `商品核心关键词`, `售价`.

Physical-measurement columns:

`商品长度`, `商品宽度`, `商品高度`, `商品尺寸单位`, `商品重量`, `商品重量单位`, `包装长度`, `包装宽度`, `包装高度`, `包装尺寸单位`, `包装重量`, `包装重量单位`.

Also accept combined `商品尺寸`/`产品尺寸` and `包装尺寸` values in `L×W×H unit` form plus common English header aliases. Structured columns take precedence. For item dimensions map input width to Amazon front-to-back depth, input height to base-to-top height, and input length to side-to-side width; use the target-template exact `Inches` enums. Package L/W/H keeps its normal axis order. Convert mm/cm/m/in to Inches and g/kg/oz/lb to a target-supported US weight unit, keeping at most three decimals. If the target supports only pounds, use its exact field-specific candidates (for example `Pounds` and `pounds`). Fall back from missing package dimensions and weight to the corresponding product measurements. Never guess a source unit for numeric conversion. In sample-guided drafts where the item-dimension value fields are targeted but unresolved, the three item-dimension target units still use the user-directed exact `Inches` enum while the paired values use the manual-review marker; package and weight units remain unresolved unless supported by actual or fallback measurements. Do not treat S/M/L or compatible-statue sizes in titles as physical measurements.

Older files may omit the last two columns, but the explicit GTIN gate still applies.

The minimum required headers are `父子变体`, `标题`, and `产品详细介绍`. Missing any of them prevents `LOCAL_VALIDATION_PASSED`.

## Commands

Run from the skill directory or use absolute script paths.

```bash
python3 scripts/manage_template_library.py --project-root /path/to/project register-blank \
  --source /path/to/amazon-downloaded-template.xlsm

python3 scripts/manage_template_library.py --project-root /path/to/project scan
python3 scripts/manage_template_library.py --project-root /path/to/project query \
  --marketplace ATVPDKIKX0DER --content-language en_US \
  --product-type SCULPTURE --browse-node outdoor-statues
```

```bash
python3 scripts/extract_inventory_context.py \
  --product /path/to/product.xlsx \
  --template /path/to/project/空白模板库/template.xlsm \
  --reference /path/to/project/样板模板库/accepted-sample.xlsm \
  --reference-verification user_confirmed \
  --marketplace ATVPDKIKX0DER --content-language en_US \
  --product-type SCULPTURE --node outdoor-statues \
  --gtin-status confirmed_exempt --out /path/to/context.json
```

Omit `--reference` only after the user explicitly approves no-sample mode.

```bash
python3 scripts/manage_task_state.py --project-root /path/to/project save-task \
  --task-id run-001 --scope-json @/path/to/scope.json --snapshot-json @/path/to/snapshot.json

python3 scripts/manage_task_state.py --project-root /path/to/project reserve-sku \
  --task-id run-001 --role Parent --source-key product-row-2 --sku LC-PARENT-001

python3 scripts/validate_inventory.py \
  --project-root /path/to/project \
  --template /path/to/project/空白模板库/template.xlsm \
  --mapping /path/to/mapping.json

python3 scripts/write_inventory.py \
  --project-root /path/to/project \
  --template /path/to/project/空白模板库/template.xlsm \
  --mapping /path/to/mapping.json \
  --out /path/to/output.xlsm --report /path/to/output.validation.json

python3 scripts/export_manual_review_report.py \
  --mapping /path/to/mapping.json --out /path/to/manual-review.json
```

```bash
python3 scripts/manage_task_state.py --project-root /path/to/project set-task-result \
  --task-id run-001 --result-status ACCEPTED_USER_CONFIRMED \
  --note "User confirmed Amazon accepted the upload"

python3 scripts/manage_template_library.py --project-root /path/to/project register-sample \
  --source /path/to/output.xlsm --status user_confirmed
```

`ACCEPTED_REPORT_VERIFIED` and `register-sample --status report_verified` both require an existing nonempty `--report` evidence file. Neither a filename nor an unattached status claim is sufficient.

The report evidence must use a supported text/JSON/XML/XLSX format and contain recognizable feed-processing summary and record/error/SKU markers. This signature gate prevents arbitrary files from being attached; the user or executing workflow still confirms that the relevant submission has no errors.

## Verification Contract

Mapping validation covers nonempty rows, product input hash and cell provenance, confirmation records, fill-mode decision-set isolation, top-level blockers/pending states, field existence, target allowed values, row roles, parent-child relationships, variation uniqueness, GTIN pair/exemption state, applicable objective requirements, Item Condition defaults, and manual-review/sample eligibility.

It also binds the chosen blank/sample entry IDs, hashes, verification level, node, and schema compatibility to the live SQLite index; checks exact product-row identity; enforces mutually exclusive decision sets and value/unit pairs; and requires draft filenames to contain `DRAFT_NOT_FOR_UPLOAD`.

Output validation compares against the blank template: worksheet names/order/visibility, named ranges, data validations, conditional formatting, target-sheet non-data structure and row prototypes, every protected ZIP-part hash, relationship parts, and VBA-part hashes. Only mapped data-cell payloads and the necessary dimension may differ. ZIP and XML must remain readable. Current bundled verification has no real VBA fixture; do not claim Excel macro acceptance without a genuine macro-bearing workbook and Excel test.
