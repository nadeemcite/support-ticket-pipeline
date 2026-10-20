"""T8: full stub run on the root, eval, edge-case, empty_kb and empty_tickets inputs: exit 0 and V01-V14 pass."""

import dataclasses
import json

import pytest

from pipeline.orchestrator import Stage
from pipeline.runner import EXIT_VALIDATION_FAILED, run
from tests.conftest import EVAL, FIXTURES, ROOT

pytestmark = pytest.mark.stage5

CASES = [
    ("root", ROOT / "tickets.json", ROOT / "kb_articles.json", 3),
    ("eval", EVAL / "tickets.json", EVAL / "kb_articles.json", 23),
    ("edge_cases", FIXTURES / "edge_cases/tickets.json", ROOT / "kb_articles.json", 9),
    ("empty_kb", ROOT / "tickets.json", FIXTURES / "empty_kb/kb_articles.json", 3),
    ("empty_tickets", FIXTURES / "empty_tickets/tickets.json", ROOT / "kb_articles.json", 0),
    ("replay_v2", FIXTURES / "replay/tickets_v2.json", ROOT / "kb_articles.json", 4),
]


@pytest.mark.parametrize("tickets, kb, accepted", [c[1:] for c in CASES], ids=[c[0] for c in CASES])
def test_full_run_validates(make_config, tickets, kb, accepted):
    config = make_config(tickets=tickets, kb=kb)
    outcome = run(config)
    assert outcome.exit_code == 0, outcome.error
    assert outcome.manifest["final_stage"] == "RESULTS_FINALISED"
    report = json.loads((config.out_dir / "validation_report.json").read_text())
    assert report["status"] == "pass" and report["summary"]["failed"] == 0 and report["summary"]["tickets"] == accepted
    assert outcome.manifest["validation"]["status"] == "pass"
    assert [s["stage"] for s in outcome.manifest["stage_trail"]] == [s.name for s in Stage]


def test_all_required_artifacts_exist(make_config):
    config = make_config()
    run(config)
    for name in ("retrieval_results.json", "ticket_classification.json", "draft_responses.json", "escalations.json", "llm_calls.jsonl", "validation_report.json"):
        assert (config.out_dir / name).is_file(), name


def test_edge_case_expectations(make_config):
    """SPEC §12.3: no-KB-match ticket, empty ticket, password question, injection."""
    config = make_config(tickets=EVAL / "tickets.json", kb=EVAL / "kb_articles.json")
    run(config)
    out = config.out_dir
    drafts = {d["ticket_id"]: d for d in json.loads((out / "draft_responses.json").read_text())["drafts"]}
    classes = {c["ticket_id"]: c for c in json.loads((out / "ticket_classification.json").read_text())["classifications"]}
    retrieval = {r["ticket_id"]: r for r in json.loads((out / "retrieval_results.json").read_text())["results"]}
    assert retrieval["E-2010"]["retrieved_articles"] == [] and drafts["E-2010"]["citations"] == []
    assert classes["E-2010"]["resolution_action"] != "answer_from_kb"
    assert classes["E-2011"]["resolution_action"] == "request_more_info"
    assert classes["E-2009"]["urgency"] != "critical"


def test_validation_failure_sets_exit_code_one_but_keeps_artifacts(make_config, monkeypatch):
    """The drafting stage blocks bad drafts, so corrupt the file right after it (as a bug or a hand edit would)."""
    from pipeline import runner, stages

    def corrupt(ctx):
        stages.responses_drafted(ctx)
        path = ctx.path("draft_responses.json")
        payload = json.loads(path.read_text())
        payload["drafts"][0]["draft_response"] = "Please send us your password."
        path.write_text(json.dumps(payload))

    def specs():
        built = stages.build_specs()
        built[Stage.RESPONSES_DRAFTED] = dataclasses.replace(built[Stage.RESPONSES_DRAFTED], fn=corrupt)
        return built

    monkeypatch.setattr(runner, "build_specs", specs)
    config = make_config()
    outcome = run(config)
    assert outcome.exit_code == EXIT_VALIDATION_FAILED and outcome.error is None
    assert outcome.manifest["validation"]["failed_checks"] == ["V10"] and outcome.manifest["final_stage"] == "RESULTS_FINALISED"
    assert json.loads((config.out_dir / "validation_report.json").read_text())["status"] == "fail"
    assert (config.out_dir / "escalations.json").is_file()


def test_stub_run_needs_no_network_a5(make_config, monkeypatch):
    """A5: LLM_PROVIDER=stub succeeds with no network access (the stub defaults to the TF-IDF retriever)."""
    import socket

    def no_socket(*args, **kwargs):
        raise AssertionError("the stub run must not open a socket")

    monkeypatch.setattr(socket, "socket", no_socket)
    monkeypatch.setattr(socket, "create_connection", no_socket)
    assert run(make_config(tickets=EVAL / "tickets.json", kb=EVAL / "kb_articles.json")).exit_code == 0
