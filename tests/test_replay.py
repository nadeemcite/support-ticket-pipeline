"""T9 / R1-R6: changing one ticket recomputes only that ticket; an identical rerun is 100% cache hits;
a KB edit invalidates every retrieval entry. Expectations come from data/fixtures/replay/expected.json."""

import dataclasses
import json

import pytest

from pipeline.runner import run
from tests.conftest import FIXTURES, ROOT, load

pytestmark = pytest.mark.stage5

EXPECTED = load(FIXTURES / "replay/expected.json")
V2 = FIXTURES / "replay/tickets_v2.json"


def cache(outcome):
    return outcome.manifest["cache"]


def test_changed_and_added_tickets_miss_everything_else_hits(make_config):
    config = make_config(tickets=ROOT / "tickets.json")
    first = run(config)
    assert cache(first) == {"retrieval": {"hits": 0, "misses": 3}, "classification": {"hits": 0, "misses": 3}, "drafting": {"hits": 0, "misses": 3}}
    second = run(dataclasses.replace(config, tickets_path=V2))
    expected = EXPECTED["run_2"]["expected_cache"]
    for stage in ("retrieval", "classification", "drafting"):
        assert cache(second)[stage] == {"hits": len(expected[stage]["hits"]), "misses": len(expected[stage]["misses"])}, stage
    assert (EXPECTED["run_2"]["unchanged"], EXPECTED["run_2"]["changed"], EXPECTED["run_2"]["added"]) == (["T-1001", "T-1003"], ["T-1002"], ["T-1004"])


def test_identical_rerun_is_all_hits_and_byte_identical(make_config):
    config = make_config(tickets=V2)
    run(config)
    names = ("retrieval_results.json", "ticket_classification.json", "draft_responses.json", "escalations.json", "grounding_flags.json")
    before = {n: (config.out_dir / n).read_bytes() for n in names}
    third = run(config)
    for stage, counts in cache(third).items():
        assert counts["misses"] == 0 and counts["hits"] == 4, stage
    assert before == {n: (config.out_dir / n).read_bytes() for n in names}
    assert all(json.loads(l)["cached"] for l in (config.out_dir / "llm_calls.jsonl").read_text().splitlines())


def test_kb_edit_invalidates_all_retrieval_entries(make_config, tmp_path):
    kb = json.loads((ROOT / "kb_articles.json").read_text())
    kb_path = tmp_path / "kb.json"
    kb_path.write_text(json.dumps(kb))
    config = make_config(kb=kb_path)
    run(config)
    kb["articles"][0]["content"] += " An extra sentence about invoices."
    kb_path.write_text(json.dumps(kb))
    again = run(config)
    assert cache(again)["retrieval"] == {"hits": 0, "misses": 3}


def test_no_cache_recomputes_everything_but_output_is_identical(make_config):
    config = make_config()
    run(config)
    before = (config.out_dir / "draft_responses.json").read_bytes()
    fresh = run(dataclasses.replace(config, no_cache=True))
    assert all(c["hits"] == 0 for c in cache(fresh).values())
    assert (config.out_dir / "draft_responses.json").read_bytes() == before


def test_cache_directory_lives_under_the_output_directory(make_config):
    config = make_config()
    run(config)
    assert (config.out_dir / ".cache").is_dir()
