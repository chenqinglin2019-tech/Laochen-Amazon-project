"""Shared model-content errors; never classify source or execution corruption."""


class ModelJudgmentError(ValueError):
    """The model's own output violates an existing judgment contract."""


def validate_statement(statement):
    if not isinstance(statement, dict) or any(
            not isinstance(statement.get(key), str) or not statement[key].strip()
            for key in ('overall', 'scope', 'limitations')):
        raise ModelJudgmentError('FINAL_REVIEW_CURRENT_OVERALL_SCOPE_LIMITATIONS_REQUIRED')


def validate_final_fields(raw):
    validate_statement(raw.get('final_review_statement'))
    validate_reviewer(raw)
    validate_confidence(raw)


def validate_reviewer(raw):
    from assessment_estimate import _text
    if not _text(raw.get('reviewer')):
        raise ModelJudgmentError('REVIEW_CONTEXT_INVALID')


def validate_confidence(raw):
    from assessment_estimate import CONFIDENCES, _text
    cap = raw.get('coverage_confidence_cap')
    if not isinstance(cap, str) or cap not in CONFIDENCES or not _text(raw.get('coverage_confidence_reasoning')):
        raise ModelJudgmentError('COVERAGE_CONFIDENCE_CAP_REQUIRED')
