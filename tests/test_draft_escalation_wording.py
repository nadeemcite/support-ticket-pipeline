"""D7/D12: the draft says "escalated" exactly when the final escalation decision (E1-E3, E6) escalates."""

import json

import pytest

from pipeline import guards
from pipeline.draft import check_draft, fallback_draft
from pipeline.schemas import DraftOutput
from pipeline.taxonomy import ResolutionAction, Urgency
from tests.test_escalation_rules import cls

pytestmark = pytest.mark.stage4


def draft(text):
    return DraftOutput(ticket_id="T-1", draft_response=text, citations=[])


def codes(text, classification, escalated):
    from tests.test_fallback_templates import ticket

    return [code for code, _ in check_draft(draft(text), ticket("en"), classification, ["KB-001"], 1500, escalated)]


@pytest.mark.parametrize("kwargs", [{"action": ResolutionAction.NEEDS_HUMAN_ESCALATION}, {"urgency": Urgency.CRITICAL}])
def test_d7_follows_the_decision_not_just_the_action(kwargs):
    c = cls(**{"action": ResolutionAction.ANSWER_FROM_KB, **kwargs})
    assert "D7" in codes("We are looking into it.", c, True)
    assert "D7" not in codes("We have escalated your case to our specialist team.", c, True)


def test_d12_no_escalation_claim_when_not_escalated():
    c = cls(action=ResolutionAction.ANSWER_FROM_KB)
    assert "D12" in codes("We have escalated your case to our specialist team.", c, False)
    assert "D12" not in codes("A support specialist will follow up with you.", c, False)
    assert "D12" not in codes("If it keeps happening we can escalate to billing support.", c, False)


@pytest.mark.parametrize(
    "text, claims",
    [
        ("We have escalated your case.", True), ("Your case has been escalated to billing ops.", True), ("It is being forwarded to a specialist.", True),
        ("Hemos escalado su caso.", True), ("Wir haben Ihren Fall weitergeleitet.", True),
        ("We have not escalated your case.", False), ("Please let us know if you want us to escalate.", False), ("A specialist will follow up.", False),
    ],
)
def test_s3_claims_escalation(text, claims):
    assert guards.s3_claims_escalation(text) is claims


def test_fallback_template_follows_the_decision():
    from tests.test_fallback_templates import ticket

    c = cls(action=ResolutionAction.ANSWER_FROM_KB, urgency=Urgency.CRITICAL)
    assert guards.s3_escalation_mention(fallback_draft(ticket("en"), c, True).draft_response)
    assert not guards.s3_claims_escalation(fallback_draft(ticket("en"), c, False).draft_response)


def test_prompt_tells_the_model_the_final_decision(make_config, scripted_llm):
    from pipeline.runner import run
    from tests.conftest import route

    provider = scripted_llm(respond=route())
    assert run(make_config()).exit_code in (0, 1)
    flags = {json.loads(m["content"].split("<classification>")[1].split("</classification>")[0])["escalated"] for call in provider.calls for m in call if "<classification>" in m["content"]}
    assert flags <= {True, False} and flags


@pytest.mark.parametrize("text", ["If two settled charges exist, this will be escalated to billing operations.", "Should it fail again, your case has been flagged and can be escalated."])
def test_conditional_escalation_is_not_a_claim(text):
    assert not guards.s3_claims_escalation(text)
