"""Input loading rules I1-I9 (SPEC §3.3)."""

import json

import pytest

from pipeline.loader import InputError, load_inputs
from pipeline.runner import EXIT_FATAL, run
from tests.conftest import FIXTURES, ROOT

pytestmark = pytest.mark.stage1

ROOT_KB = ROOT / "kb_articles.json"


def test_root_samples_load():
    loaded = load_inputs(ROOT / "tickets.json", ROOT_KB)
    assert [t["ticket_id"] for t in loaded.tickets] == ["T-1001", "T-1002", "T-1003"]
    assert [a["article_id"] for a in loaded.articles] == ["KB-001", "KB-002", "KB-003", "KB-004"]
    assert loaded.rejected_tickets == loaded.duplicate_tickets == []


@pytest.mark.parametrize("fixture", ["malformed/invalid_json.txt", "malformed/wrong_top_level_key.json"])
def test_i1_malformed_tickets_raise(fixture):
    with pytest.raises(InputError):
        load_inputs(FIXTURES / fixture, ROOT_KB)


@pytest.mark.parametrize("fixture", ["malformed/invalid_json.txt", "malformed/wrong_top_level_key.json"])
def test_i1_malformed_tickets_exit_2_and_write_manifest(fixture, make_config):
    config = make_config(tickets=FIXTURES / fixture)
    outcome = run(config)
    assert outcome.exit_code == EXIT_FATAL
    assert outcome.manifest["final_stage"] == "FAILED"
    assert "InputError" in outcome.manifest["error"]
    assert (config.artifacts_dir / "run_manifest.json").is_file()
    assert not (config.artifacts_dir / "normalised_tickets.json").exists()


def test_i1_missing_file(tmp_path):
    with pytest.raises(InputError, match="not found"):
        load_inputs(tmp_path / "nope.json", ROOT_KB)


def test_i1_top_level_not_a_list(tmp_path):
    path = tmp_path / "tickets.json"
    path.write_text(json.dumps({"tickets": {"ticket_id": "T-1"}}))
    with pytest.raises(InputError, match="must be a list"):
        load_inputs(path, ROOT_KB)


def test_i1_malformed_kb(tmp_path):
    path = tmp_path / "kb.json"
    path.write_text(json.dumps({"docs": []}))
    with pytest.raises(InputError, match="articles"):
        load_inputs(ROOT / "tickets.json", path)


def test_i3_i4_edge_cases_rejected_and_duplicates():
    expected = json.loads((FIXTURES / "edge_cases/expected.json").read_text())
    loaded = load_inputs(FIXTURES / "edge_cases/tickets.json", ROOT_KB)
    assert sorted({t["ticket_id"] for t in loaded.tickets}) == expected["accepted_ticket_ids"]
    assert loaded.duplicate_tickets == expected["duplicates"]
    assert [{k: r[k] for k in ("input_index", "reason", "rule")} for r in loaded.rejected_tickets] == expected["rejected"]


def test_i4_first_occurrence_wins():
    loaded = load_inputs(FIXTURES / "edge_cases/tickets.json", ROOT_KB)
    first = next(t for t in loaded.tickets if t["ticket_id"] == "X-001")
    assert first["subject"] == "Cannot find invoices"
    assert first["input_index"] == 0


def test_i3_non_object_ticket_rejected(tmp_path):
    path = tmp_path / "tickets.json"
    path.write_text(json.dumps({"tickets": ["just a string", {"ticket_id": "  "}]}))
    loaded = load_inputs(path, ROOT_KB)
    assert loaded.tickets == []
    assert [r["input_index"] for r in loaded.rejected_tickets] == [0, 1]


def test_i2_extra_fields_preserved_on_raw_record():
    loaded = load_inputs(FIXTURES / "edge_cases/tickets.json", ROOT_KB)
    raw = next(t for t in loaded.tickets if t["ticket_id"] == "X-008")
    assert raw["channel"] == "email" and raw["tags"] == ["priority", "beta"]


def test_i7_empty_tickets_list():
    loaded = load_inputs(FIXTURES / "empty_tickets/tickets.json", ROOT_KB)
    assert loaded.tickets == [] and loaded.tickets_input_count == 0


def test_i8_empty_kb():
    loaded = load_inputs(ROOT / "tickets.json", FIXTURES / "empty_kb/kb_articles.json")
    assert loaded.articles == [] and len(loaded.tickets) == 3


def test_i9_duplicate_and_missing_article_ids(tmp_path):
    path = tmp_path / "kb.json"
    articles = [
        {"article_id": "KB-1", "title": "a", "category": "billing", "content": "first"},
        {"article_id": "KB-1", "title": "b", "category": "billing", "content": "second"},
        {"title": "no id", "category": "billing", "content": "x"},
    ]
    path.write_text(json.dumps({"articles": articles}))
    loaded = load_inputs(ROOT / "tickets.json", path)
    assert [a["content"] for a in loaded.articles] == ["first"]
    assert loaded.duplicate_articles == [{"article_id": "KB-1", "input_index": 1, "rule": "I9"}]
    assert loaded.rejected_articles[0]["input_index"] == 2


def test_input_hashes_recorded_and_canonical_hash_ignores_formatting(tmp_path):
    original = load_inputs(ROOT / "tickets.json", ROOT_KB)
    reformatted = tmp_path / "tickets.json"
    reformatted.write_text(json.dumps(json.loads((ROOT / "tickets.json").read_text()), indent=None))
    other = load_inputs(reformatted, ROOT_KB)
    assert original.tickets_file.sha256 != other.tickets_file.sha256
    assert original.tickets_file.canonical_sha256 == other.tickets_file.canonical_sha256
