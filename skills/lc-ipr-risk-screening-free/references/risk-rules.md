# Risk and independent-review contract

Use modules exactly: `appearance_patent`, `utility_patent`, `pending_application`, `word_mark`, `figurative_trade_dress`, `copyright_ip`, `enforcement`.

Risks are `极低`, `低`, `中`, `高`, `极高`; confidence is `低`, `中`, `高`. Overall risk is the highest module risk. A one-level compound escalation requires explicit justification. Never average away a high module.

Each module contains `risk`, `confidence`, `reasoning`, and `findings`; each finding contains `finding_id`, `title`, `evidence_refs`, and `recommended_action`. Reviews also contain `review_triggers`, `summary_reasons`, and `recommended_actions`.

Mandatory source failure or a material candidate without official verification produces `incomplete` and no grade. Optional source loss prohibits `极低` and caps confidence at `中`. One Amazon image caps copyright, figurative-mark, and trade-dress confidence at `中`.

Require a second independent review when the first grade is high/extreme or a trigger is true. Both reviews record distinct session IDs and the same evidence/candidate digest; both declare `first_review_visible=false`. A difference of two or more overall levels requires human review; otherwise reconcile conservatively per module and retain non-duplicate findings from both reviews. Overall confidence follows the module(s) driving the overall risk; coverage confidence remains separately visible.
