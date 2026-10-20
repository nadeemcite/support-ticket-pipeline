"""L1/O3 end to end: llm_calls.jsonl only ever holds classification and drafting lines, tagged consistently."""

import json

import pytest

from pipeline.orchestrator import Stage
from pipeline.runner import run
from tests.conftest import EVAL, route

pytestmark = pytest.mark.stage5

EXPECTED = {
    "classification": ("classify.v1", "ticket_classification.json"),
    "drafting": ("draft.v2", "draft_responses.json"),
}


def log(config):
    return [json.loads(line) for line in (config.out_dir / "llm_calls.jsonl").read_text().splitlines()]


def test_only_the_two_llm_stages_appear_and_are_tagged_consistently(make_config):
    config = make_config(tickets=EVAL / "tickets.json", kb=EVAL / "kb_articles.json")
    assert run(config).exit_code == 0
    records = log(config)
    assert {r["stage"] for r in records} == set(EXPECTED)
    for r in records:
        version, artifact = EXPECTED[r["stage"]]
        assert r["prompt_version"] == version and r["output_artifact"] == artifact
        assert r["prompt_hash"].startswith("sha256:") and r["ticket_ids"] == [r["ticket_id"]]


def test_all_classification_lines_precede_all_drafting_lines(make_config):
    config = make_config()
    run(config)
    stages = [r["stage"] for r in log(config)]
    assert stages == ["classification"] * 3 + ["drafting"] * 3


@pytest.mark.parametrize("until", [Stage.INPUTS_LOADED, Stage.KB_INDEXED, Stage.TICKETS_NORMALISED, Stage.EVIDENCE_RETRIEVED])
def test_no_llm_line_before_classification(make_config, until):
    config = make_config()
    run(config, until=until)
    assert (config.out_dir / "llm_calls.jsonl").read_text() == ""


def test_validation_and_escalation_add_no_llm_calls(make_config, scripted_llm):
    provider = scripted_llm(respond=route())
    config = make_config()
    run(config, until=Stage.RESPONSES_DRAFTED)
    calls = len(provider.calls)
    assert calls == 6
    run(config)  # re-runs everything through V01-V14; every LLM call is a cache hit
    assert len(provider.calls) == calls and {r["stage"] for r in log(config)} == {"classification", "drafting"}
