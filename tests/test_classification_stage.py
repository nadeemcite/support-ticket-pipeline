"""TICKETS_CLASSIFIED end to end (offline): artifact contract, log coverage, cache, guard, PII."""

import json

import pytest

from pipeline import pii
from pipeline.orchestrator import Stage
from pipeline.runner import EXIT_FATAL, run
from pipeline.schemas import Classification
from pipeline.taxonomy import IssueType, ResolutionAction, Urgency
from tests.conftest import EVAL, FIXTURES, ticket_id_from, valid_reply

pytestmark = pytest.mark.stage3


def _classifications(config):
    return json.loads((config.out_dir / "ticket_classification.json").read_text())["classifications"]


def _log(config):
    return [json.loads(line) for line in (config.out_dir / "llm_calls.jsonl").read_text().splitlines()]


def test_stub_run_on_eval_set(make_config):
    config = make_config(tickets=EVAL / "tickets.json", kb=EVAL / "kb_articles.json")
    outcome = run(config, until=Stage.TICKETS_CLASSIFIED)
    assert outcome.exit_code == 0 and outcome.manifest["final_stage"] == "TICKETS_CLASSIFIED"
    records = _classifications(config)
    expected_ids = [t["ticket_id"] for t in json.loads((EVAL / "tickets.json").read_text())["tickets"]]
    assert [r["ticket_id"] for r in records] == expected_ids
    for record in records:
        parsed = Classification.model_validate(record)
        assert parsed.issue_type in IssueType and parsed.urgency in Urgency and parsed.resolution_action in ResolutionAction
    log = _log(config)
    assert [r["ticket_id"] for r in log if r["status"] == "ok"] == expected_ids
    assert {r["stage"] for r in log} == {"classification"} and {r["provider"] for r in log} == {"stub"}
    assert outcome.manifest["llm"] == {"provider": "stub", "model": "stub"}
    assert outcome.manifest["counts"]["llm_calls"] == len(expected_ids)


def test_evidence_ids_match_retrieval(make_config):
    config = make_config(tickets=EVAL / "tickets.json", kb=EVAL / "kb_articles.json")
    run(config)
    retrieval = {r["ticket_id"]: [a["article_id"] for a in r["retrieved_articles"]]
                 for r in json.loads((config.out_dir / "retrieval_results.json").read_text())["results"]}
    for record in _classifications(config):
        assert record["meta"]["evidence_ids"] == retrieval[record["ticket_id"]]


def test_scripted_provider_sees_masked_text_only(make_config, scripted_llm):
    provider = scripted_llm(respond=lambda messages: valid_reply(ticket_id_from(messages)))
    config = make_config(tickets=EVAL / "tickets.json", kb=EVAL / "kb_articles.json")
    assert run(config).exit_code == 0
    raw = json.loads((EVAL / "tickets.json").read_text())["tickets"]
    raw_values = [d.value for t in raw for d in pii.detect(t["subject"] + " " + t["message"])]
    for call in provider.calls:
        for message in call:
            assert not any(value in message["content"] for value in raw_values)


def test_rerun_uses_llm_cache(make_config, scripted_llm):
    provider = scripted_llm(respond=lambda messages: valid_reply(ticket_id_from(messages)))
    config = make_config()
    run(config, until=Stage.TICKETS_CLASSIFIED)
    first_calls = len(provider.calls)
    outcome = run(config, until=Stage.TICKETS_CLASSIFIED)
    assert len(provider.calls) == first_calls == 3
    assert outcome.manifest["counts"]["llm_cache_hits"] == 3
    assert all(r["cached"] for r in _log(config))


def test_fallbacks_counted_and_run_still_succeeds(make_config, scripted_llm):
    scripted_llm(respond=lambda messages: "not json")
    outcome = run(make_config(), until=Stage.TICKETS_CLASSIFIED)
    assert outcome.exit_code == 0
    assert outcome.manifest["counts"]["classification_fallbacks"] == 3
    assert outcome.manifest["counts"]["llm_calls"] == 9  # 3 tickets x 3 attempts


def test_overrides_counted(make_config, scripted_llm):
    scripted_llm(respond=lambda messages: valid_reply(ticket_id_from(messages), issue_type="how_to", customer_sensitive=False))
    outcome = run(make_config(tickets=EVAL / "tickets.json", kb=EVAL / "kb_articles.json"))
    overrides = outcome.manifest["counts"]["overrides"]
    assert overrides.get("C1", 0) >= 5 and overrides.get("C3", 0) >= 1 and overrides.get("C5", 0) == 1


def test_empty_tickets_produce_empty_artifact(make_config):
    config = make_config(tickets=FIXTURES / "empty_tickets/tickets.json")
    assert run(config).exit_code == 0
    assert _classifications(config) == []
    assert (config.out_dir / "llm_calls.jsonl").read_text() == ""


def test_until_retrieval_makes_no_llm_calls(make_config, scripted_llm):
    provider = scripted_llm(respond=lambda messages: valid_reply(ticket_id_from(messages)))
    config = make_config()
    run(config, until=Stage.EVIDENCE_RETRIEVED)
    assert provider.calls == [] and (config.out_dir / "llm_calls.jsonl").read_text() == ""


def test_missing_llm_credentials_fail_before_any_stage(make_config):
    outcome = run(make_config(provider="ollama", model="glm-5.2"))
    assert outcome.exit_code == EXIT_FATAL and "OLLAMA_API_KEY" in outcome.error
    assert outcome.manifest["stage_trail"] == []
