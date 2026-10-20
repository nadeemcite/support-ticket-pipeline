"""retrieval_debug.json explains every ranking (SPEC §6.2)."""

import json

import pytest

from pipeline.runner import run
from tests.conftest import EVAL

pytestmark = pytest.mark.stage2


def _debug(make_config, **overrides):
    config = make_config(tickets=EVAL / "tickets.json", kb=EVAL / "kb_articles.json", **overrides)
    assert run(config).exit_code == 0
    return config, json.loads((config.out_dir / "retrieval_debug.json").read_text())


@pytest.mark.parametrize("retriever", ["tfidf", "embedding"])
def test_debug_structure_and_kept_flags(make_config, fake_embedder, retriever):
    config, debug = _debug(make_config, retriever=retriever)
    results = {r["ticket_id"]: r for r in json.loads((config.out_dir / "retrieval_results.json").read_text())["results"]}
    assert debug["config"]["method"] == retriever
    assert debug["config"]["min_score"] == config.effective_min_score
    assert debug["config"]["kb_hash"].startswith("sha256:")
    for entry in debug["results"]:
        kept_ids = [a["article_id"] for a in results[entry["ticket_id"]]["retrieved_articles"]]
        candidates = entry["candidates"]
        assert [c["rank"] for c in candidates] == list(range(1, len(candidates) + 1))
        assert [c["article_id"] for c in candidates if c["kept"]] == kept_ids
        for c in candidates:
            assert set(c) == {"article_id", "rank", "score", "lexical_score", "kept", "shared_terms", "top_terms", "best_snippet"}
            if c["kept"]:
                assert c["best_snippet"], (entry["ticket_id"], c["article_id"])
        if not kept_ids:
            assert entry["note"]


def test_tfidf_kept_hits_have_top_terms(make_config):
    _, debug = _debug(make_config)
    for entry in debug["results"]:
        for c in entry["candidates"]:
            if c["kept"]:
                assert c["top_terms"] and c["top_terms"][0]["contribution"] > 0


def test_dropped_candidates_are_listed(make_config):
    _, debug = _debug(make_config)
    dropped = [c for e in debug["results"] for c in e["candidates"] if not c["kept"]]
    assert dropped, "expected some candidates below the cut to be reported with kept=false"


def test_snippet_comes_from_the_article(make_config):
    _, debug = _debug(make_config)
    kb = {a["article_id"]: a for a in json.loads((EVAL / "kb_articles.json").read_text())["articles"]}
    title_only = 0
    for entry in debug["results"]:
        for c in entry["candidates"]:
            if c["best_snippet"]:
                article = kb[c["article_id"]]
                assert c["best_snippet"] in article["content"] or c["best_snippet"] == article["title"]
                title_only += c["best_snippet"] == article["title"]
    assert title_only >= 1  # E-2014 matches KB-003 only through its title ("...from the dashboard")


def test_empty_ticket_note(make_config):
    _, debug = _debug(make_config)
    entry = next(e for e in debug["results"] if e["ticket_id"] == "E-2011")
    assert entry["note"] == "empty ticket: nothing to match" and entry["candidates"] == []


def test_kb_index_artifact(make_config, fake_embedder):
    config, _ = _debug(make_config, retriever="embedding")
    index = json.loads((config.artifacts_dir / "kb_index.json").read_text())
    assert index["method"] == "embedding" and index["model"] == "fake-embed"
    assert [a["article_id"] for a in index["articles"]] == [f"KB-{i:03d}" for i in range(1, 12)]
    assert index["config_hash"].startswith("sha256:") and index["embedding_dims"] == 64
