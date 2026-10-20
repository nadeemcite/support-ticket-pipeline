"""T7: invalid output is retried with error feedback; three failures fall back safely (C0, CF)."""

import json

import pytest

from pipeline.classify import FALLBACK_RATIONALE, classify_ticket
from pipeline.llm import LLMClient, LLMTransportError
from pipeline.normalise import normalise_ticket
from pipeline.orchestrator import Stage
from pipeline.schemas import KBArticle
from pipeline.taxonomy import IssueType, ResolutionAction, Urgency
from tests.conftest import ScriptedProvider, valid_reply

pytestmark = pytest.mark.stage3

KB = KBArticle(article_id="KB-001", title="Charges", category="billing", updated_at=None, content="Pending holds clear in 3-5 days.")
INPUTS = ["artifacts/normalised_tickets.json", "retrieval_results.json", "kb_articles.json"]


def _ticket(message="My card shows a pending hold", ticket_id="T-1"):
    return normalise_ticket({"ticket_id": ticket_id, "customer_tier": "standard", "language": "en", "subject": "Hold", "message": message}, 4000, "s")


def _client(provider, tmp_path):
    return LLMClient(provider=provider, max_tokens=500, temperature=0.0, log_path=tmp_path / "llm_calls.jsonl",
                     clock=lambda: "2026-01-01T00:00:00.000Z", current_stage=lambda: Stage.TICKETS_CLASSIFIED)


def _log(tmp_path):
    return [json.loads(line) for line in (tmp_path / "llm_calls.jsonl").read_text().splitlines()]


def test_valid_first_attempt(tmp_path):
    provider = ScriptedProvider([valid_reply("T-1")])
    result = classify_ticket(_client(provider, tmp_path), _ticket(), [KB], INPUTS)
    assert (result.issue_type, result.meta.attempts, result.meta.fallback) == (IssueType.BILLING, 1, False)
    assert [r["status"] for r in _log(tmp_path)] == ["ok"]


def test_invalid_json_then_valid(tmp_path):
    provider = ScriptedProvider(["this is not json", valid_reply("T-1")])
    result = classify_ticket(_client(provider, tmp_path), _ticket(), [KB], INPUTS)
    assert result.meta.attempts == 2 and not result.meta.fallback
    assert [r["status"] for r in _log(tmp_path)] == ["invalid_json", "ok"]


def test_invented_category_retried_with_error_feedback(tmp_path):
    provider = ScriptedProvider([valid_reply("T-1", issue_type="refunds"), valid_reply("T-1")])
    classify_ticket(_client(provider, tmp_path), _ticket(), [KB], INPUTS)
    retry_messages = provider.calls[1]
    assert retry_messages[-2] == {"role": "assistant", "content": valid_reply("T-1", issue_type="refunds")}
    feedback = retry_messages[-1]["content"]
    assert "issue_type" in feedback and "rejected" in feedback
    assert [r["status"] for r in _log(tmp_path)] == ["schema_error", "ok"]


@pytest.mark.parametrize(
    "bad",
    [
        valid_reply("T-1", urgency="urgent"),
        valid_reply("T-1", resolution_action="close"),
        valid_reply("T-1", rationale=""),
        valid_reply("T-1", rationale="x" * 501),
        json.dumps({**json.loads(valid_reply("T-1")), "sentiment": "angry"}),
        json.dumps({k: v for k, v in json.loads(valid_reply("T-1")).items() if k != "urgency"}),
        "[1, 2, 3]",
    ],
)
def test_schema_violations_are_rejected(tmp_path, bad):
    provider = ScriptedProvider([bad, valid_reply("T-1")])
    result = classify_ticket(_client(provider, tmp_path), _ticket(), [KB], INPUTS)
    assert result.meta.attempts == 2
    assert _log(tmp_path)[0]["status"] in ("schema_error", "invalid_json")


def test_wrong_ticket_id_is_a_rule_violation(tmp_path):
    provider = ScriptedProvider([valid_reply("T-999"), valid_reply("T-1")])
    classify_ticket(_client(provider, tmp_path), _ticket(), [KB], INPUTS)
    assert [r["status"] for r in _log(tmp_path)] == ["rule_violation", "ok"]
    assert 'ticket_id must be "T-1"' in provider.calls[1][-1]["content"]


def test_three_failures_fall_back(tmp_path):
    provider = ScriptedProvider(["nope", "still nope", valid_reply("T-1", issue_type="refunds")])
    result = classify_ticket(_client(provider, tmp_path), _ticket("Please refund me"), [KB], INPUTS)
    assert result.meta.fallback and result.meta.attempts == 3
    assert (result.issue_type, result.urgency, result.resolution_action) == (
        IssueType.OTHER, Urgency.MEDIUM, ResolutionAction.NEEDS_HUMAN_ESCALATION,
    )
    assert result.customer_sensitive and result.requires_refund_caution  # C1 still evaluated on the ticket
    assert result.rationale == FALLBACK_RATIONALE
    assert len(provider.calls) == 3


def test_transport_error_retries_same_prompt(tmp_path):
    provider = ScriptedProvider([LLMTransportError("RateLimitError: 429"), valid_reply("T-1")])
    result = classify_ticket(_client(provider, tmp_path), _ticket(), [KB], INPUTS)
    assert provider.calls[0] == provider.calls[1]
    log = _log(tmp_path)
    assert [r["status"] for r in log] == ["transport_error", "ok"] and "429" in log[0]["error"]
    assert not result.meta.fallback


def test_markdown_fenced_json_is_accepted(tmp_path):
    provider = ScriptedProvider(["```json\n" + valid_reply("T-1") + "\n```"])
    result = classify_ticket(_client(provider, tmp_path), _ticket(), [KB], INPUTS)
    assert result.meta.attempts == 1 and not result.meta.fallback


def test_evidence_ids_recorded(tmp_path):
    result = classify_ticket(_client(ScriptedProvider([valid_reply("T-1")]), tmp_path), _ticket(), [KB], INPUTS)
    assert result.meta.evidence_ids == ["KB-001"]
