"""E1-E5, Q1/Q2 truth table, E-INV1-3, determinism (T5)."""

import itertools

import pytest
from pydantic import ValidationError

from pipeline import guards
from pipeline.escalate import decide, find_clause
from pipeline.schemas import Classification, ClassificationMeta, Escalation, KBArticle
from pipeline.taxonomy import IssueType, ResolutionAction, TargetQueue, Urgency

pytestmark = pytest.mark.stage4


def article(article_id, category, content):
    return KBArticle(article_id=article_id, title="t", category=category, updated_at=None, content=content)


BILLING_KB = article("KB-001", "billing", "Pending holds clear. Escalate to billing ops if two settled charges exist for the same order.")
ACCOUNT_KB = article("KB-002", "account_access", "Retry login. If the reset succeeded but login still fails, escalate to account support.")
SUPPORT_KB = article("KB-006", "technical_problem", "Reinstall the app. If it still crashes, escalate to general support with the collected details.")
NO_CLAUSE = article("KB-007", "how_to", "Reports can be exported under Reports > Export.")


def cls(issue=IssueType.BILLING, urgency=Urgency.MEDIUM, action=ResolutionAction.ANSWER_FROM_KB, caution=False, fallback=False):
    return Classification(
        ticket_id="T-1", issue_type=issue, urgency=urgency, resolution_action=action, customer_sensitive=False,
        requires_refund_caution=caution, rationale="r", meta=ClassificationMeta(fallback=fallback),
    )


@pytest.mark.parametrize(
    "kwargs, rule, escalate",
    [
        (dict(action=ResolutionAction.NEEDS_HUMAN_ESCALATION), "E1", True),
        (dict(urgency=Urgency.CRITICAL), "E2", True),
        (dict(fallback=True), "E3", True),
        (dict(action=ResolutionAction.REQUEST_MORE_INFO), "E4", False),
        (dict(action=ResolutionAction.ANSWER_FROM_KB), "E5", False),
    ],
)
def test_decision_rules(kwargs, rule, escalate):
    result = decide(cls(**kwargs), [BILLING_KB])
    assert result.escalate is escalate and rule in result.meta.rules_fired and rule in result.reason


def test_all_matching_escalation_rules_are_listed():
    result = decide(cls(action=ResolutionAction.NEEDS_HUMAN_ESCALATION, urgency=Urgency.CRITICAL), [])
    assert result.meta.rules_fired[:2] == ["E1", "E2"]


def test_critical_beats_request_more_info():
    assert decide(cls(action=ResolutionAction.REQUEST_MORE_INFO, urgency=Urgency.CRITICAL), []).escalate


@pytest.mark.parametrize(
    "issue, evidence, queue, evidence_ids",
    [
        (IssueType.BILLING, [BILLING_KB], TargetQueue.BILLING_OPS, ["KB-001"]),  # Q1
        (IssueType.ACCOUNT_ACCESS, [ACCOUNT_KB], TargetQueue.ACCOUNT_SUPPORT, ["KB-002"]),
        (IssueType.TECHNICAL_PROBLEM, [SUPPORT_KB], TargetQueue.GENERAL_SUPPORT, ["KB-006"]),
        (IssueType.BILLING, [ACCOUNT_KB], TargetQueue.BILLING_OPS, []),  # Q2: clause is in another category
        (IssueType.ACCOUNT_ACCESS, [], TargetQueue.ACCOUNT_SUPPORT, []),
        (IssueType.HOW_TO, [NO_CLAUSE], TargetQueue.GENERAL_SUPPORT, []),
        (IssueType.OTHER, [], TargetQueue.GENERAL_SUPPORT, []),
    ],
)
def test_queue_routing(issue, evidence, queue, evidence_ids):
    result = decide(cls(issue=issue, action=ResolutionAction.NEEDS_HUMAN_ESCALATION), evidence)
    assert result.target_queue == queue and result.meta.evidence_ids == evidence_ids
    assert ("Q1" if evidence_ids else "Q2") in result.meta.rules_fired


def test_q1_uses_rank_order_and_quotes_the_clause():
    second = article("KB-009", "billing", "Escalate to account support immediately.")
    result = decide(cls(action=ResolutionAction.NEEDS_HUMAN_ESCALATION), [BILLING_KB, second])
    assert result.meta.evidence_ids == ["KB-001"]
    assert "KB-001" in result.reason and "'Escalate to billing ops if two settled charges exist for the same order.'" in result.reason  # E-INV2


@pytest.mark.parametrize(
    "sentence, queue",
    [
        ("Escalate to billing support.", TargetQueue.BILLING_OPS),
        ("Requests must be escalated to billing ops.", TargetQueue.BILLING_OPS),
        ("Escalate to the account team now.", TargetQueue.ACCOUNT_SUPPORT),
        ("Escalate to general support with the details.", TargetQueue.GENERAL_SUPPORT),
        ("Escalate to the security team if needed.", TargetQueue.GENERAL_SUPPORT),
    ],
)
def test_clause_team_mapping(sentence, queue):
    assert find_clause([article("KB-X", "billing", sentence)], IssueType.BILLING)[2] == queue


def test_invariant_queue_none_iff_not_escalated():  # E-INV1
    for issue, urgency, action in itertools.product(IssueType, Urgency, ResolutionAction):
        result = decide(cls(issue=issue, urgency=urgency, action=action), [BILLING_KB, ACCOUNT_KB])
        assert result.escalate == (result.target_queue != TargetQueue.NONE)
    with pytest.raises(ValidationError):
        Escalation(ticket_id="T", escalate=False, target_queue=TargetQueue.BILLING_OPS, reason="x")
    with pytest.raises(ValidationError):
        Escalation(ticket_id="T", escalate=True, target_queue=TargetQueue.NONE, reason="x")


def test_refund_caution_reason_is_safe_and_explicit():  # E-INV3
    result = decide(cls(action=ResolutionAction.NEEDS_HUMAN_ESCALATION, caution=True), [BILLING_KB])
    assert "verify settlement status" in result.reason and not guards.s2_refund_promise(result.reason)


def test_unsafe_kb_clause_is_dropped_from_the_reason():
    risky = article("KB-X", "billing", "We will refund you today. Escalate to billing ops.")
    result = decide(cls(action=ResolutionAction.NEEDS_HUMAN_ESCALATION, caution=True), [risky])
    assert not guards.s2_refund_promise(result.reason) and result.target_queue == TargetQueue.BILLING_OPS and "E1" in result.reason


def test_same_input_same_output():
    c = cls(action=ResolutionAction.NEEDS_HUMAN_ESCALATION, caution=True)
    assert decide(c, [BILLING_KB]).model_dump() == decide(c, [BILLING_KB]).model_dump()
