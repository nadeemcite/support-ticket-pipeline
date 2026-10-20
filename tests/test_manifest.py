"""run_manifest.json records input hashes, the stage trail and rejected/duplicate lists (O4)."""

import json

import pytest

from pipeline.io_utils import sha256_file
from pipeline.orchestrator import Stage
from pipeline.runner import run
from tests.conftest import FIXTURES, ROOT

pytestmark = pytest.mark.stage1


def _manifest(config):
    return json.loads((config.artifacts_dir / "run_manifest.json").read_text())


def test_manifest_contents_for_root_run(make_config):
    config = make_config()
    assert run(config).exit_code == 0
    manifest = _manifest(config)
    for key in ("run_id", "pipeline_version", "started_at", "finished_at", "status", "exit_code", "final_stage", "config", "inputs", "counts", "stage_trail"):
        assert key in manifest, key
    assert manifest["status"] == "ok" and manifest["error"] is None
    assert manifest["inputs"]["tickets"]["sha256"] == sha256_file(ROOT / "tickets.json")
    assert manifest["inputs"]["kb"]["sha256"] == sha256_file(ROOT / "kb_articles.json")
    for entry in manifest["stage_trail"]:
        assert set(entry) == {"stage", "entered_at", "duration_ms", "placeholder"}


def test_manifest_lists_rejected_and_duplicates(make_config):
    expected = json.loads((FIXTURES / "edge_cases/expected.json").read_text())
    config = make_config(tickets=FIXTURES / "edge_cases/tickets.json")
    run(config)
    manifest = _manifest(config)
    assert manifest["duplicate_tickets"] == expected["duplicates"]
    assert [r["input_index"] for r in manifest["rejected_tickets"]] == [r["input_index"] for r in expected["rejected"]]
    assert manifest["counts"]["tickets_accepted"] == len(expected["accepted_ticket_ids"])
    assert manifest["counts"]["tickets_insufficient_content"] == 1


def test_manifest_has_no_secrets(make_config, monkeypatch):
    monkeypatch.setenv("OLLAMA_API_KEY", "sk-very-secret-value")
    config = make_config(pii_salt="private-salt-value")
    run(config)
    text = (config.artifacts_dir / "run_manifest.json").read_text()
    assert "sk-very-secret-value" not in text and "private-salt-value" not in text


def test_manifest_written_on_failure(make_config):
    config = make_config(tickets=FIXTURES / "malformed/wrong_top_level_key.json")
    run(config)
    manifest = _manifest(config)
    assert manifest["status"] == "failed" and manifest["exit_code"] == 2
    assert manifest["final_stage"] == "FAILED"
    assert [s["stage"] for s in manifest["stage_trail"]] == ["INIT"]


@pytest.mark.parametrize(
    "tickets, kb, accepted",
    [
        (ROOT / "tickets.json", ROOT / "kb_articles.json", 3),
        (FIXTURES / "edge_cases/tickets.json", ROOT / "kb_articles.json", 9),
        (ROOT / "tickets.json", FIXTURES / "empty_kb/kb_articles.json", 3),
        (FIXTURES / "empty_tickets/tickets.json", ROOT / "kb_articles.json", 0),
        (FIXTURES / "replay/tickets_v2.json", ROOT / "kb_articles.json", 4),
    ],
    ids=["root", "edge_cases", "empty_kb", "empty_tickets", "replay_v2"],
)
def test_artifacts_for_every_fixture(make_config, tickets, kb, accepted):
    config = make_config(tickets=tickets, kb=kb)
    outcome = run(config, until=Stage.TICKETS_NORMALISED)
    assert outcome.exit_code == 0
    normalised = json.loads((config.artifacts_dir / "normalised_tickets.json").read_text())
    assert len(normalised["tickets"]) == accepted
    assert (config.out_dir / "llm_calls.jsonl").read_text() == ""


def test_rerun_produces_identical_normalised_artifact(make_config):
    config = make_config(tickets=FIXTURES / "edge_cases/tickets.json")
    run(config)
    first = (config.artifacts_dir / "normalised_tickets.json").read_bytes()
    run(config)
    assert (config.artifacts_dir / "normalised_tickets.json").read_bytes() == first
