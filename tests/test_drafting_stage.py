"""RESPONSES_DRAFTED and ESCALATIONS_DECIDED end to end (offline): artifacts, log coverage, cache, stage guard, masking, determinism."""

import json

import pytest

from pipeline import pii
from pipeline.llm import LLMClient, LLMStageError
from pipeline.orchestrator import Stage
from pipeline.runner import run
from pipeline.schemas import DraftResponse, Escalation, GroundingFlag
from pipeline.taxonomy import LLMStage
from tests.conftest import EVAL, FIXTURES, draft_reply, route, valid_reply

pytestmark = pytest.mark.stage4


def read(config, name):
    return json.loads((config.out_dir / name).read_text())


def test_stub_run_writes_all_three_artifacts(make_config):
    config = make_config(tickets=EVAL / "tickets.json", kb=EVAL / "kb_articles.json")
    outcome = run(config, until=Stage.ESCALATIONS_DECIDED)
    assert outcome.exit_code == 0 and outcome.manifest["final_stage"] == "ESCALATIONS_DECIDED"
    ids = [t["ticket_id"] for t in json.loads((EVAL / "tickets.json").read_text())["tickets"]]
    drafts = [DraftResponse.model_validate(d) for d in read(config, "draft_responses.json")["drafts"]]
    escalations = [Escalation.model_validate(e) for e in read(config, "escalations.json")["escalations"]]
    flags = read(config, "grounding_flags.json")
    assert [d.ticket_id for d in drafts] == ids and [e.ticket_id for e in escalations] == ids
    assert [GroundingFlag.model_validate(f) for f in flags["flags"]] is not None
    assert flags["summary"]["total_flags"] == len(flags["flags"])
    retrieval = {r["ticket_id"]: {a["article_id"] for a in r["retrieved_articles"]} for r in read(config, "retrieval_results.json")["results"]}
    for draft in drafts:
        assert set(draft.citations) <= retrieval[draft.ticket_id]


def test_log_covers_both_llm_stages(make_config):
    config = make_config(tickets=EVAL / "tickets.json", kb=EVAL / "kb_articles.json")
    run(config)
    log = [json.loads(line) for line in (config.out_dir / "llm_calls.jsonl").read_text().splitlines()]
    for stage in ("classification", "drafting"):
        assert len([r for r in log if r["stage"] == stage and r["status"] == "ok"]) == 23
    assert [r["stage"] for r in log][:23] == ["classification"] * 23  # drafting only after classification
    assert {r["prompt_version"] for r in log} == {"classify.v1", "draft.v1"}
    assert all(r["output_artifact"] in ("ticket_classification.json", "draft_responses.json") for r in log)


def test_escalations_are_identical_across_reruns(make_config):
    config = make_config(tickets=EVAL / "tickets.json", kb=EVAL / "kb_articles.json")
    run(config)
    first = (config.out_dir / "escalations.json").read_bytes()
    run(config)
    assert (config.out_dir / "escalations.json").read_bytes() == first


def test_rerun_uses_llm_cache_for_drafting(make_config, scripted_llm):
    provider = scripted_llm(respond=route())
    config = make_config()
    run(config)
    calls = len(provider.calls)
    outcome = run(config)
    assert len(provider.calls) == calls == 6  # 3 tickets x (classify + draft)
    assert outcome.manifest["counts"]["llm_cache_hits"] == 6


def test_until_drafted_stops_before_escalation(make_config):
    config = make_config()
    run(config, until=Stage.RESPONSES_DRAFTED)
    assert (config.out_dir / "draft_responses.json").exists() and not (config.out_dir / "escalations.json").exists()


def test_drafting_prompt_sees_masked_text_only(make_config, scripted_llm):
    provider = scripted_llm(respond=route())
    config = make_config(tickets=EVAL / "tickets.json", kb=EVAL / "kb_articles.json")
    assert run(config, until=Stage.ESCALATIONS_DECIDED).exit_code == 0
    raw = json.loads((EVAL / "tickets.json").read_text())["tickets"]
    raw_values = [d.value for t in raw for d in pii.detect(t["subject"] + " " + t["message"])]
    drafting = [c for c in provider.calls if "<classification>" in c[1]["content"]]
    assert len(drafting) == 23
    for call in drafting:
        assert not any(value in message["content"] for message in call for value in raw_values)


def test_prompt_contains_only_retrieved_articles(make_config, scripted_llm):  # D1
    provider = scripted_llm(respond=route())
    config = make_config(tickets=EVAL / "tickets.json", kb=EVAL / "kb_articles.json")
    run(config)
    retrieval = {r["ticket_id"]: [a["article_id"] for a in r["retrieved_articles"]] for r in read(config, "retrieval_results.json")["results"]}
    from tests.conftest import ticket_id_from

    for call in provider.calls:
        if "<classification>" not in call[1]["content"]:
            continue
        evidence = call[1]["content"].split("<evidence>")[1].split("</evidence>")[0]
        shown = [line[1:].split("]")[0] for line in evidence.splitlines() if line.startswith("[KB-")]
        assert shown == retrieval[ticket_id_from(call)]


def test_drafting_call_refused_outside_its_stage(make_config, tmp_path):
    client = LLMClient(provider=None, max_tokens=1, temperature=0, log_path=tmp_path / "l.jsonl", clock=lambda: "t", current_stage=lambda: Stage.TICKETS_CLASSIFIED)
    with pytest.raises(LLMStageError):
        client.call(LLMStage.DRAFTING, [{"role": "user", "content": "hi"}], "draft.v1", None)


def test_grounding_flags_are_written_and_never_block(make_config, scripted_llm):
    def draft(messages, ticket_id):
        evidence = [line[1:].split("]")[0] for line in messages[1]["content"].splitlines() if line.startswith("[KB-")]
        return draft_reply(ticket_id, "The pending charge will disappear within 24 hours.", evidence[:1])

    scripted_llm(respond=route(classify=lambda m, t: valid_reply(t), draft=draft))
    config = make_config()
    outcome = run(config)
    assert outcome.exit_code == 0
    flags = read(config, "grounding_flags.json")
    assert flags["flags"] and {f["check"] for f in flags["flags"]} <= {"G1", "G2", "G3"}
    assert outcome.manifest["counts"]["grounding_flags"] == len(flags["flags"])
    assert all(not d["meta"]["fallback"] for d in read(config, "draft_responses.json")["drafts"])


def test_empty_tickets_produce_empty_stage_four_artifacts(make_config):
    config = make_config(tickets=FIXTURES / "empty_tickets/tickets.json")
    assert run(config).exit_code == 0
    assert read(config, "draft_responses.json") == {"drafts": []} and read(config, "escalations.json") == {"escalations": []}
    assert read(config, "grounding_flags.json")["flags"] == []


def test_fallback_classification_escalates_via_e3(make_config, scripted_llm):
    scripted_llm(respond=lambda messages: "not json" if "<classification>" not in messages[1]["content"] else draft_reply("x"))
    config = make_config()
    outcome = run(config)
    assert outcome.exit_code == 0
    for escalation in read(config, "escalations.json")["escalations"]:
        assert escalation["escalate"] and "E3" in escalation["meta"]["rules_fired"]
