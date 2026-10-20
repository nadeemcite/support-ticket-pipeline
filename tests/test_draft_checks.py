"""Drafting hard rules (D3-D11): a violating model reply is blocked, retried with the reason, then replaced by the DF template."""

import json
import re

import pytest

from pipeline import guards
from pipeline.draft import MAX_ATTEMPTS
from pipeline.orchestrator import Stage
from pipeline.runner import run
from pipeline.schemas import DraftResponse
from tests.conftest import EVAL, GOOD_TEXT, draft_reply, first_evidence_id, good_draft, route, valid_reply

pytestmark = pytest.mark.stage4

CREDENTIAL_TICKET = "E-2008"


def good_text(messages) -> str:
    return GOOD_TEXT


def good_reply(messages, ticket_id):
    return good_draft(messages, ticket_id)


def run_eval(make_config, scripted_llm, draft, classify=None):
    scripted_llm(respond=route(classify=classify, draft=draft))
    config = make_config(tickets=EVAL / "tickets.json", kb=EVAL / "kb_articles.json")
    outcome = run(config, until=Stage.RESPONSES_DRAFTED)
    assert outcome.exit_code == 0, outcome.error
    drafts = {d["ticket_id"]: d for d in json.loads((config.out_dir / "draft_responses.json").read_text())["drafts"]}
    return config, outcome, drafts


def violating(code):
    cases = {
        "D3": lambda m, t: draft_reply(t, good_text(m), ["KB-999"]),
        "D5": lambda m, t: draft_reply(t, "Please send us your password so we can check. We have escalated this.", [first_evidence_id(m)] if first_evidence_id(m) else []),
        "D6": lambda m, t: draft_reply(t, "We will refund the charge today. We have escalated this.", [first_evidence_id(m)] if first_evidence_id(m) else []),
        "D9": lambda m, t: draft_reply(t, "x" * 5000, [first_evidence_id(m)] if first_evidence_id(m) else []),
        "D11": lambda m, t: draft_reply(t, "We will write to jane.doe@example.com and [EMAIL_1]. We have escalated this.", [first_evidence_id(m)] if first_evidence_id(m) else []),
    }
    return cases[code]


@pytest.mark.parametrize("code", ["D3", "D5", "D6", "D9", "D11"])
def test_violation_is_blocked_retried_then_falls_back(make_config, scripted_llm, code):
    classify = lambda m, t: valid_reply(t, requires_refund_caution=True, resolution_action="answer_from_kb")  # noqa: E731
    config, outcome, drafts = run_eval(make_config, scripted_llm, violating(code), classify)
    for ticket_id, draft in drafts.items():
        meta = draft["meta"]
        has_evidence = bool(json.loads((config.out_dir / "retrieval_results.json").read_text()))
        assert meta["fallback"] and meta["attempts"] == MAX_ATTEMPTS and draft["citations"] == []
        assert code in meta["violations_resolved"]
        assert not guards.has_pii(draft["draft_response"]) and not guards.has_placeholder(draft["draft_response"])
        assert not guards.s1_credential_request(draft["draft_response"]) and not guards.s2_refund_promise(draft["draft_response"])
    assert outcome.manifest["counts"]["draft_fallbacks"] == 23


def test_d4_missing_citation_is_blocked(make_config, scripted_llm):
    classify = lambda m, t: valid_reply(t, resolution_action="answer_from_kb")  # noqa: E731
    _, _, drafts = run_eval(make_config, scripted_llm, lambda m, t: draft_reply(t, "Here is some help.", []), classify)
    with_evidence = [d for d in drafts.values() if "D4" in d["meta"]["violations_resolved"]]
    assert with_evidence and all(d["meta"]["fallback"] for d in with_evidence)


def test_d7_escalation_mention_required(make_config, scripted_llm):
    classify = lambda m, t: valid_reply(t, resolution_action="needs_human_escalation")  # noqa: E731
    _, _, drafts = run_eval(make_config, scripted_llm, lambda m, t: draft_reply(t, "Thanks, we will look at it.", []), classify)
    assert all("D7" in d["meta"]["violations_resolved"] and d["meta"]["fallback"] for d in drafts.values())
    assert all(guards.s3_escalation_mention(d["draft_response"]) for d in drafts.values())


def test_d10_credential_advice_required_when_ticket_disclosed_a_secret(make_config, scripted_llm):
    classify = lambda m, t: valid_reply(t, resolution_action="needs_human_escalation")  # noqa: E731
    text = "We have escalated this to our specialist team."
    _, _, drafts = run_eval(make_config, scripted_llm, lambda m, t: draft_reply(t, text, []), classify)
    flagged = [t for t, d in drafts.items() if "D10" in d["meta"]["violations_resolved"]]
    assert flagged == [CREDENTIAL_TICKET]
    assert guards.has_credential_advice(drafts[CREDENTIAL_TICKET]["draft_response"])


def test_one_bad_attempt_then_good_is_resolved_not_fallback(make_config, scripted_llm):
    def draft(messages, ticket_id):
        if len(messages) == 2:  # first attempt: no rejection feedback yet
            return draft_reply(ticket_id, "Please send us your password. We have escalated this.", [])
        return good_reply(messages, ticket_id)

    classify = lambda m, t: valid_reply(t, resolution_action="needs_human_escalation")  # noqa: E731
    _, outcome, drafts = run_eval(make_config, scripted_llm, draft, classify)
    for d in drafts.values():
        assert not d["meta"]["fallback"] and d["meta"]["attempts"] == 2 and d["meta"]["violations_resolved"][0] == "D5"
    assert outcome.manifest["counts"]["draft_retries"] == 23


def test_retry_prompt_carries_the_violation(make_config, scripted_llm):
    seen = []

    def draft(messages, ticket_id):
        seen.append(messages)
        return good_reply(messages, ticket_id) if len(messages) > 2 else draft_reply(ticket_id, "Please send us your PIN. We have escalated this.", [])

    classify = lambda m, t: valid_reply(t, resolution_action="needs_human_escalation")  # noqa: E731
    run_eval(make_config, scripted_llm, draft, classify)
    retry = next(m for m in seen if len(m) > 2)
    assert "never ask for a password" in retry[-1]["content"] and retry[-2]["role"] == "assistant"


@pytest.mark.parametrize("reply", ["not json", "[]", json.dumps({"ticket_id": "x"}), json.dumps({"ticket_id": "x", "draft_response": "a", "citations": [], "extra": 1})])
def test_malformed_replies_fall_back(make_config, scripted_llm, reply):
    _, _, drafts = run_eval(make_config, scripted_llm, lambda m, t: reply)
    assert all(d["meta"]["fallback"] for d in drafts.values())
    for d in drafts.values():
        DraftResponse.model_validate(d)


def test_wrong_ticket_id_is_rejected(make_config, scripted_llm):
    _, _, drafts = run_eval(make_config, scripted_llm, lambda m, t: draft_reply("T-9999", good_text(m)))
    assert all(d["meta"]["fallback"] and "ID" in d["meta"]["violations_resolved"] for d in drafts.values())


def test_pii_in_a_rejected_draft_is_not_echoed_into_the_retry_prompt(make_config, scripted_llm):
    seen = []

    def draft(messages, ticket_id):
        seen.append(messages)
        return good_reply(messages, ticket_id) if len(messages) > 2 else draft_reply(ticket_id, "Write to jane.doe@example.com. We have escalated this.", [])

    run_eval(make_config, scripted_llm, draft, lambda m, t: valid_reply(t, resolution_action="needs_human_escalation"))
    retry = next(m for m in seen if len(m) > 2)
    assert "jane.doe" not in json.dumps(retry) and "withheld" in retry[-2]["content"]
