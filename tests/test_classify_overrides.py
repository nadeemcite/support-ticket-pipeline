"""Deterministic overrides C1-C5: each fires on a minimal input and is recorded in meta.overrides."""

import pytest

from pipeline.classify import REFUND_RE, apply_overrides
from pipeline.normalise import normalise_ticket
from pipeline.schemas import ClassificationOutput, KBArticle
from pipeline.taxonomy import IssueType, ResolutionAction

pytestmark = pytest.mark.stage3

KB = KBArticle(article_id="KB-1", title="t", category="billing", updated_at=None, content="Refunds depend on settlement.")


def _output(**kw):
    base = dict(ticket_id="T", issue_type="how_to", urgency="low", resolution_action="answer_from_kb",
                customer_sensitive=False, requires_refund_caution=False, rationale="r")
    return ClassificationOutput(**{**base, **kw})


def _ticket(subject="Question", message="How do I export a report?"):
    return normalise_ticket({"ticket_id": "T", "subject": subject, "message": message}, 4000, "s")


def _rules(overrides):
    return [o.split(":")[0] for o in overrides]


def test_no_override_when_model_is_consistent():
    values, overrides = apply_overrides(_output(), _ticket(), [KB])
    assert overrides == [] and values["resolution_action"] == ResolutionAction.ANSWER_FROM_KB


@pytest.mark.parametrize(
    "text",
    [
        "Please refund me", "I was charged twice", "chargeback filed", "I want my money back",
        "Bekomme ich das Geld für diesen Monat zurück?", "Quiero un reembolso", "remboursement svp",
        "billed twice this month", "duplicate charge on my card",
    ],
)
def test_c1_refund_language_in_ticket(text):
    values, overrides = apply_overrides(_output(), _ticket(message=text), [KB])
    assert values["requires_refund_caution"] and _rules(overrides) == ["C1"]


@pytest.mark.parametrize("text", ["My phone charger broke", "How do I export a CSV?", "Where are my invoices?"])
def test_c1_not_fired_without_refund_language(text):
    values, overrides = apply_overrides(_output(), _ticket(message=text), [KB])
    assert not values["requires_refund_caution"] and "C1" not in _rules(overrides)


def test_c1_ignores_evidence_text():
    """Evidence like 'Refunds depend on settlement' is retrieved for unrelated tickets; it must not trigger C1."""
    assert REFUND_RE.search(KB.content)
    values, _ = apply_overrides(_output(), _ticket(message="Where are my invoices?"), [KB])
    assert not values["requires_refund_caution"]


def test_c2_insufficient_content():
    values, overrides = apply_overrides(_output(), _ticket(subject="", message=""), [KB])
    assert values["resolution_action"] == ResolutionAction.REQUEST_MORE_INFO and "C2" in _rules(overrides)


def test_c3_no_evidence():
    values, overrides = apply_overrides(_output(), _ticket(), [])
    assert values["resolution_action"] == ResolutionAction.NEEDS_HUMAN_ESCALATION and _rules(overrides) == ["C3"]


def test_c2_takes_precedence_over_c3_for_empty_ticket():
    values, overrides = apply_overrides(_output(), _ticket(subject="", message=""), [])
    assert values["resolution_action"] == ResolutionAction.REQUEST_MORE_INFO and _rules(overrides) == ["C2"]


@pytest.mark.parametrize("issue", [IssueType.BILLING, IssueType.ACCOUNT_ACCESS])
def test_c4_sensitive_issue_types(issue):
    values, overrides = apply_overrides(_output(issue_type=issue.value), _ticket(), [KB])
    assert values["customer_sensitive"] and _rules(overrides) == ["C4"]


def test_c5_credential_disclosure():
    ticket = _ticket(message="My password is Summer2026! please help")
    assert ticket.pii_summary[0].type.value == "credential"
    values, overrides = apply_overrides(_output(issue_type="technical_problem"), ticket, [KB])
    assert values["customer_sensitive"] and _rules(overrides) == ["C5"]


def test_overrides_never_touch_issue_type_or_urgency():
    values, _ = apply_overrides(_output(urgency="critical"), _ticket(subject="", message=""), [])
    assert (values["issue_type"], values["urgency"]) == (IssueType.HOW_TO, "critical")
