# Mapping v2.2 Contract

`scripts/write_inventory.py` accepts Mapping `2.0`, `2.1`, and `2.2`. New work uses `2.2`; `2.0/2.1` retain their original semantics. Empty `{}`, empty `rows`, and legacy bare field values are invalid.

## Shape

```json
{
  "schema_version": "2.2",
  "task": {
    "task_id": "run-20260722-001",
    "marketplace": "ATVPDKIKX0DER",
    "content_language": "en_US",
    "product_type": "SCULPTURE",
    "browse_node": "outdoor-statues",
    "fill_mode": "SAMPLE_GUIDED",
    "gtin_status": "confirmed_exempt",
    "result_status": "DRAFT_NOT_FOR_UPLOAD"
  },
  "templates": {
    "blank_entry_id": 12,
    "blank_sha256": "...",
    "blank_schema_fingerprint": "...",
    "sample_entry_id": 18,
    "sample_sha256": "...",
    "sample_verification": "user_confirmed",
    "sample_schema_compatibility": "exact_schema"
  },
  "inputs": {
    "product": {
      "path": "/absolute/path/product.xlsx",
      "sha256": "..."
    }
  },
  "confirmations": [
    {
      "id": "confirm-brand-001",
      "field": "brand[marketplace_id=ATVPDKIKX0DER][language_tag=en_US]#1.value",
      "value": "Current Product Brand",
      "confirmed": true
    }
  ],
  "field_plan": {
    "must_fill": {
      "Parent": ["..."],
      "Child": ["..."]
    },
    "rule_default": {
      "Parent": ["condition_type[marketplace_id=ATVPDKIKX0DER]#1.value"],
      "Child": ["condition_type[marketplace_id=ATVPDKIKX0DER]#1.value"]
    },
    "sample_preferred": {
      "Parent": ["..."],
      "Child": ["..."]
    },
    "evidence_fillable": ["..."]
  },
  "rows": [
    {
      "source_row": 2,
      "source_key": "product-row-2",
      "role": "Parent",
      "must_fill": [
        "contribution_sku#1.value",
        "product_type#1.value",
        "::record_action"
      ],
      "fields": {
        "contribution_sku#1.value": {
          "value": "LC-PARENT-001",
          "decision_set": "must_fill",
          "source": {
            "type": "sku_reservation",
            "reference": "run-20260722-001/product-row-2"
          },
          "confidence": 1.0,
          "confirmation_status": "not_required",
          "validation": {
            "status": "passed",
            "messages": []
          }
        }
      }
    }
  ],
  "manual_review": [
    {
      "source_row": 3,
      "role": "Child",
      "field": "mounting_type[marketplace_id=ATVPDKIKX0DER][language_tag=en_US]#1.value",
      "label": "Mounting Type",
      "value": "信息不足，请人工核对",
      "reason": "产品信息未提供型号",
      "data_definition": {},
      "template_restriction": {"allowed_values": []}
    }
  ],
  "blocking_errors": [],
  "warnings": []
}
```

## Required enums

- `task.fill_mode`: `SAMPLE_GUIDED` or `NO_SAMPLE_CONFIRMED`.
- `task.gtin_status`: `provided`, `confirmed_exempt`, or `unknown`.
- `task.result_status` for a new write: `DRAFT_NOT_FOR_UPLOAD` or `LOCAL_VALIDATION_PASSED`. The two `ACCEPTED_*` states are external post-upload states and cannot be used to create a workbook.
- `rows[].role`: `Parent`, `Child`, or `Standalone`.
- Mapping `2.0` decision sets: `must_fill`, `sample_preferred`, `evidence_fillable`.
- Mapping `2.1` decision sets: `must_fill`, `rule_default`, `sample_preferred`, `evidence_fillable`.
- Mapping `2.2` decision sets: `must_fill`, `rule_default`, `sample_preferred`, `evidence_fillable`.
- `confirmation_status`: `confirmed`, `not_required`, or `pending`.
- `validation.status`: `passed`, `pending`, `warning`, or `blocked`.

## Field records

Every `rows[].fields` value is an object with all six properties:

- `value`: the exact value to write. It may be an empty string only when the field is not in that row's `must_fill` list.
- `decision_set`: why this field was selected. In 2.2, `rule_default` means a policy-controlled field; its row-level source may be an explicit product cell, deterministic business rule, or evidence-backed model rule.
- `source.type`: a current-product, user-confirmation, target-template, relationship, or SKU-reservation source type.
- `source.reference`: a precise product cell, confirmation ID, target-template candidate, task scope, relationship, or reservation reference.
- `confidence`: numeric value from `0` through `1`.
- `confirmation_status` and `validation`: explicit decision and validation state.

Sample workbooks may justify `decision_set=sample_preferred`, but a sample or reference workbook must never be the value source. Source types containing `sample` or `reference` are rejected.

Allowed `source.type` values are fixed:

- `product_cell`: the written value must equal a nonblank `Sheet!A1` cell in `inputs.product`.
- `model_extracted` or `model_summarized`: `source.reference` is one or more nonblank product-cell references used as evidence.
- `user_confirmation`: reference must be `confirmation:<id>` and match a `confirmations[]` record with the same field/value and `confirmed=true`.
- `task_scope` is limited to Product Type, `sku_reservation` to SKU, `relationship` to parentage/parent SKU/variation theme, and `system_generated` to `::record_action`.
- `business_rule` in Mapping `2.1` remains limited to exact `Item Condition=New`. Mapping `2.2` additionally permits only the documented rule-ID/field pairs; unknown rules fail.
- `model_rule` is Mapping `2.2` only. It cites one or more nonblank current-product cells in `source.reference` and an allowed `source.rule_id`.
- `manual_review_marker` is allowed only in Mapping `2.1/2.2` drafts. Its exact value is `信息不足，请人工核对` and its reference is `manual_review:<source_row>:<technical_field>`.
- `target_template_allowed_value` is limited to those structural fields. A target-template candidate alone can never prove brand, content, dimensions, compliance, identity, or another product fact.

`inputs.product.path` is absolute and its current SHA-256 must equal `inputs.product.sha256`. The task snapshot stores the same object and the complete `templates` object; the writer checks both for exact equality before publishing. Entry IDs, hashes, sample status, node match, and schema compatibility are rechecked against the current SQLite template index and files.

For `LOCAL_VALIDATION_PASSED`, nonempty product identity, country of origin, battery, dangerous-goods, and compliance values require confidence of at least `0.8` and `confirmation_status=confirmed`. Uncertain objective values stay blank and the task remains `DRAFT_NOT_FOR_UPLOAD`.

## Row rules

- `rows` must be a nonempty array.
- `blocking_errors` and `warnings` must both be arrays. `LOCAL_VALIDATION_PASSED` requires `blocking_errors=[]`, no pending confirmations, and no pending/blocked field validations.
- `must_fill` is the row-specific set after applying role and actual conditional triggers. Every listed field must exist and have a nonempty valid value, except the product ID value for confirmed GTIN exemption.
- Every nonempty product row must map exactly once. `source_row` must be the actual product-sheet row, `source_key` must be `product-row-<source_row>`, and the Mapping role must equal that row's `父子变体` role. These fields also bind retry-stable SKU reservation.
- The product sheet must contain `父子变体`, `标题`, and `产品详细介绍`. Missing minimum headers cannot produce `LOCAL_VALIDATION_PASSED`.
- Mapping `2.1` uses mutually exclusive decision sets in this order: `must_fill`, `rule_default`, `sample_preferred`, `evidence_fillable`.
- Mapping `2.2` uses the same mutually exclusive order. New 2.2 policy rules are not applied retroactively to 2.0/2.1 files.
- When a target schema contains a matching `.value` and `.unit` pair, either both are blank or both are filled.
- Parent rows must not contain product ID fields or a parent SKU.
- Child rows must reference the single Parent SKU in the same Mapping.
- Standalone rows must not contain parentage or variation fields.
- Every SKU is unique. Child variation combinations are unique under the same Parent.
- `NO_SAMPLE_CONFIRMED` forbids sample metadata, nonempty `field_plan.sample_preferred`, and every row-level `decision_set=sample_preferred`.

## Mapping 2.2 policy-controlled fields

- All roles: Item Condition uses exact target candidate `New` (`rule:item-condition-new`).
- Child/Standalone only:
  - Model Number equals the current row's reserved SKU (`rule:model-number-equals-sku`).
  - Manufacturer equals the row's confirmed Brand (`rule:manufacturer-equals-brand`).
  - Explicit Model Name wins; otherwise `rule:model-name-core-keyword-fallback` derives a concise core phrase from current Listing cells.
  - Explicit Part Number wins; otherwise `rule:part-number-core-keyword-fallback` uses the same core phrase.
  - Explicit sellable pack count wins; otherwise Number of Items is `1` (`rule:number-of-items-default-one`). Components in one set are not counted as separately sold items.
  - Explicit Mounting Type is remapped; otherwise `rule:mounting-type-enum-selection` selects the best target enum from current evidence or uses an eligible draft marker.
  - Explicit fulfillment wins; otherwise `rule:fulfillment-default-fba` selects the target-template semantic FBA candidate.
- Parent does not receive the seven sellable-row identity/offer rules merely because Child sample rows filled those fields.
- Rule-derived sensitive fields still require confidence `>=0.8`; deterministic cross-field equality replaces a redundant independent confirmation.

## Product measurements and defaults

- Mapping `2.1/2.2` writes the target-template candidate `New` to Item Condition for every Parent, Child, or Standalone row.
- Recognized physical-measurement headers include the structured Chinese columns documented in `SKILL.md`, their common English aliases, and the combined `商品尺寸`/`产品尺寸`/`包装尺寸` forms.
- Structured values take precedence over combined forms. Product width maps to front-to-back depth, product height to base-to-top height, and product length to side-to-side width. Package L/W/H keeps its normal axes.
- Convert mm/cm/m/in to the target exact `Inches` candidate. Convert g/kg/oz/lb to a target-supported Pounds/Ounces candidate, preferring Ounces below one pound only when every paired target unit field supports it. Keep at most three decimals.
- Main and normalized Item Weight values represent the same physical weight; field-specific unit capitalization must match target candidates exactly.
- Fall back from each missing package dimension to the corresponding product dimension and from missing package weight to product weight.
- Source units used to convert numeric measurements are never guessed. In a sample-guided draft, if targeted item-dimension values remain unresolved, their three target unit fields use the user-directed exact `Inches` enum and the paired values use the manual-review marker. Package and weight unit fields remain unresolved unless actual or fallback measurements supply sufficient evidence. Do not interpret variation values such as S/M/L or compatible-statue sizes as physical measurements.

## Manual-review markers

- A marker is eligible only when the selected verified sample filled that technical field for the same role and variation theme.
- The top-level `manual_review[]` entry and row field record must match exactly by `source_row` and `field`.
- Marker records use `validation.status=warning`, `confidence=0`, and `confirmation_status=not_required`.
- Markers may bypass numeric or allowed-value constraints only in `DRAFT_NOT_FOR_UPLOAD`; validation emits warnings and upload eligibility remains `NOT_FOR_UPLOAD`.
- A marker cannot appear in no-sample mode, cannot be used for a sample-blank field, and cannot produce `LOCAL_VALIDATION_PASSED`.
- Sample values remain hidden and are never copied; the marker only records that current-product evidence is missing.

## Product ID rules

- `provided`: type and value are both present and pass type-specific format/checksum checks.
- `confirmed_exempt`: the target template supports its exemption value; product ID type contains that exact target-template value and product ID value stays blank.
- `unknown`: only `DRAFT_NOT_FOR_UPLOAD` is permitted and no exemption claim is written.
- A one-sided type/value pair always fails.

## Writer rules

- Field keys are exact technical names from the target blank template `attributeRow`; column letters are forbidden.
- Allowed-value fields use only candidates extracted from the target blank template.
- The writer performs the deterministic validator again. A claimed `validation.status=passed` never bypasses checks.
- Mapping validation must succeed before any output file is created.
- The writer CLI requires `--project-root`; it compares product and template selections with the immutable task snapshot and verifies every Mapping SKU against the task reservations.
- `DRAFT_NOT_FOR_UPLOAD` output filenames must contain the literal marker `DRAFT_NOT_FOR_UPLOAD`; the report also returns `upload_eligibility=NOT_FOR_UPLOAD`.
- Only mapped data-cell payloads and the necessary worksheet dimension may change. Column widths, headers, formulas, styles, merged cells, hidden settings, and other non-data structure are protected.
- The source template and both template-library originals are read-only. Output is a new file outside both libraries; source hashes, headers, styles, validations, and protected OOXML parts are verified before atomic publication.
