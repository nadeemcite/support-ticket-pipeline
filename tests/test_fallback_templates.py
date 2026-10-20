"""DF templates exist per language and pass S1/S2/V13/V14 by construction; escalation and password advice appear when required."""

import itertools

import pytest

from pipeline import guards
from pipeline.draft import TEMPLATE_LANGUAGES, TEMPLATES, check_draft, fallback_draft, template_language
from pipeline.schemas import Classification, NormalisedTicket, PIISummaryEntry
from pipeline.taxonomy import IssueType, PIIType, ResolutionAction, Urgency

pytestmark = pytest.mark.stage4


def ticket(language="en", credential=False):
    pii = [PIISummaryEntry(type=PIIType.CREDENTIAL, placeholder="[CREDENTIAL_1]", count=1, hash="sha256:x")] if credential else []
    return NormalisedTicket(
        ticket_id="T-1", input_index=0, customer_tier="standard", language=language, subject="s", message="m",
        created_at=None, pii_summary=pii, content_hash="sha256:x",
    )


def classification(action):
    return Classification(
        ticket_id="T-1", issue_type=IssueType.BILLING, urgency=Urgency.MEDIUM, resolution_action=action,
        customer_sensitive=True, requires_refund_caution=True, rationale="r",
    )


def test_all_five_languages_have_every_piece():
    assert set(TEMPLATE_LANGUAGES) == {"en", "es", "fr", "de", "pt"}
    for pieces in TEMPLATES.values():
        assert set(pieces) == {"ack", "escalation", "more_info", "password", "followup"}


@pytest.mark.parametrize("language, action, credential", list(itertools.product(TEMPLATE_LANGUAGES, ResolutionAction, (False, True))))
def test_fallback_is_safe_and_complete(language, action, credential):
    t, c = ticket(language, credential), classification(action)
    draft = fallback_draft(t, c)
    text = draft.draft_response
    assert draft.meta.fallback and draft.citations == [] and draft.meta.language == language
    assert not guards.s1_credential_request(text) and not guards.s2_refund_promise(text)
    assert not guards.has_pii(text) and not guards.has_placeholder(text)  # V13 / V14
    # every hard rule except citations (a fallback cites nothing by design)
    from pipeline.schemas import DraftOutput

    violations = check_draft(DraftOutput(ticket_id="T-1", draft_response=text, citations=[]), t, c, ["KB-001"], 1500)
    assert [code for code, _ in violations if code != "D4"] == []
    if action == ResolutionAction.NEEDS_HUMAN_ESCALATION:
        assert guards.s3_escalation_mention(text)
    if credential:
        assert guards.has_credential_advice(text)


def test_unknown_language_falls_back_to_english():
    assert template_language("ja") == "en" and template_language("pt-BR") == "pt" and template_language("EN") == "en"
    assert fallback_draft(ticket("ja"), classification(ResolutionAction.ANSWER_FROM_KB)).meta.language == "en"
