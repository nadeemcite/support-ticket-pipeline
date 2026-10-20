"""Replay cache for retrieval (R1) and embeddings: reuse unchanged work, invalidate on any change."""

import json

import pytest

from pipeline.runner import run
from tests.conftest import FIXTURES, ROOT

pytestmark = pytest.mark.stage2


def _counts(outcome):
    return outcome.manifest["counts"]


def test_rerun_hits_cache_with_identical_output(make_config):
    config = make_config()
    first = run(config)
    output = (config.out_dir / "retrieval_results.json").read_bytes()
    second = run(config)
    assert _counts(first)["retrieval_cache"] == {"hits": 0, "misses": 3}
    assert _counts(second)["retrieval_cache"] == {"hits": 3, "misses": 0}
    assert (config.out_dir / "retrieval_results.json").read_bytes() == output


def test_changed_and_added_tickets_miss_only(make_config):
    expected = json.loads((FIXTURES / "replay/expected.json").read_text())["run_2"]["expected_cache"]["retrieval"]
    config = make_config()
    run(config)
    replay = type(config)(**{**config.__dict__, "tickets_path": FIXTURES / "replay/tickets_v2.json"})
    outcome = run(replay)
    assert _counts(outcome)["retrieval_cache"] == {"hits": len(expected["hits"]), "misses": len(expected["misses"])}


def test_kb_edit_invalidates_every_ticket(make_config, tmp_path):
    kb = json.loads((ROOT / "kb_articles.json").read_text())
    kb["articles"][3]["content"] += " Edited."
    edited = tmp_path / "kb_edited.json"
    edited.write_text(json.dumps(kb))
    config = make_config()
    run(config)
    outcome = run(type(config)(**{**config.__dict__, "kb_path": edited}))
    assert _counts(outcome)["retrieval_cache"] == {"hits": 0, "misses": 3}


def test_retrieval_settings_are_part_of_the_key(make_config):
    config = make_config()
    run(config)
    outcome = run(type(config)(**{**config.__dict__, "min_score": 0.2}))
    assert _counts(outcome)["retrieval_cache"]["misses"] == 3


def test_no_cache_recomputes_but_output_is_the_same(make_config):
    config = make_config()
    run(config)
    output = (config.out_dir / "retrieval_results.json").read_bytes()
    outcome = run(type(config)(**{**config.__dict__, "no_cache": True}))
    assert _counts(outcome)["retrieval_cache"] == {"hits": 0, "misses": 3}
    assert (config.out_dir / "retrieval_results.json").read_bytes() == output


def test_embedding_cache_avoids_api_calls_on_rerun(make_config, fake_embedder):
    config = make_config(retriever="embedding")
    first = run(config)
    calls_after_first = len(fake_embedder.calls)
    second = run(config)
    assert _counts(first)["embedding_api_calls"] == 3  # articles, sentences, tickets (batched)
    assert len(fake_embedder.calls) == calls_after_first  # nothing new sent
    assert _counts(second)["embedding_api_calls"] == 0
    assert _counts(second)["embedding_cache_hits"] == _counts(second)["embedding_texts"]


def test_corrupt_cache_entry_is_a_miss(make_config):
    config = make_config()
    run(config)
    for entry in (config.out_dir / ".cache" / "retrieval").rglob("*.json"):
        entry.write_text("{corrupt")
    outcome = run(config)
    assert _counts(outcome)["retrieval_cache"] == {"hits": 0, "misses": 3}
