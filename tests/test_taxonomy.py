"""T1: the taxonomy enums are the single source of truth."""

import pytest
from pydantic import ValidationError

from pipeline.schemas import Classification, Escalation
from pipeline.taxonomy import IssueType, LLMStage, ResolutionAction, TargetQueue, Urgency, values

pytestmark = pytest.mark.stage1

SPEC_TAXONOMY = {
    IssueType: ["billing", "account_access", "technical_problem", "how_to", "other"],
    Urgency: ["critical", "high", "medium", "low"],
    ResolutionAction: ["answer_from_kb", "needs_human_escalation", "request_more_info"],
    TargetQueue: ["billing_ops", "account_support", "general_support", "none"],
    LLMStage: ["classification", "drafting"],
}


@pytest.mark.parametrize("enum_cls", SPEC_TAXONOMY)
def test_enums_match_spec(enum_cls):
    assert values(enum_cls) == SPEC_TAXONOMY[enum_cls]


def _enum_in_schema(schema: dict, enum_name: str) -> list[str]:
    return schema["$defs"][enum_name]["enum"]


def test_classification_json_schema_lists_exactly_taxonomy_values():
    schema = Classification.model_json_schema()
    assert _enum_in_schema(schema, "IssueType") == values(IssueType)
    assert _enum_in_schema(schema, "Urgency") == values(Urgency)
    assert _enum_in_schema(schema, "ResolutionAction") == values(ResolutionAction)
    assert schema["additionalProperties"] is False


def test_escalation_json_schema_lists_exactly_queue_values():
    assert _enum_in_schema(Escalation.model_json_schema(), "TargetQueue") == values(TargetQueue)


VALID = {
    "ticket_id": "T-1",
    "issue_type": "billing",
    "urgency": "high",
    "resolution_action": "answer_from_kb",
    "customer_sensitive": True,
    "requires_refund_caution": True,
    "rationale": "Matches KB-001.",
}


def test_valid_classification_accepted():
    assert Classification.model_validate(VALID).issue_type is IssueType.BILLING


@pytest.mark.parametrize(
    "field, bad",
    [("issue_type", "refunds"), ("urgency", "urgent"), ("resolution_action", "close_ticket"), ("issue_type", "Billing")],
)
def test_invented_category_rejected(field, bad):
    with pytest.raises(ValidationError):
        Classification.model_validate({**VALID, field: bad})


def test_unknown_field_rejected():
    with pytest.raises(ValidationError):
        Classification.model_validate({**VALID, "sentiment": "angry"})


def test_empty_rationale_rejected():
    with pytest.raises(ValidationError):
        Classification.model_validate({**VALID, "rationale": ""})


@pytest.mark.parametrize(
    "escalate, queue, ok",
    [(False, "none", True), (True, "billing_ops", True), (False, "billing_ops", False), (True, "none", False)],
)
def test_escalation_queue_invariant(escalate, queue, ok):
    record = {"ticket_id": "T-1", "escalate": escalate, "target_queue": queue, "reason": "E5"}
    if ok:
        Escalation.model_validate(record)
    else:
        with pytest.raises(ValidationError, match="E-INV1"):
            Escalation.model_validate(record)
