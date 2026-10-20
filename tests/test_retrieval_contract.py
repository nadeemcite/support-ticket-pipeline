"""Retrieval contract (SPEC §6.1, check V06): <=3 hits, sorted, scores in range, IDs exist; empty cases."""

import json

import pytest

from pipeline.runner import run
from pipeline.schemas import RetrievalResult
from tests.conftest import EVAL, FIXTURES, ROOT

pytestmark = pytest.mark.stage2

INPUTS = [
    (ROOT / "tickets.json", ROOT / "kb_articles.json"),
    (EVAL / "tickets.json", EVAL / "kb_articles.json"),
    (FIXTURES / "edge_cases/tickets.json", ROOT / "kb_articles.json"),
]


def _results(config):
    return json.loads((config.out_dir / "retrieval_results.json").read_text())["results"]


@pytest.mark.parametrize("retriever", ["tfidf", "embedding"])
@pytest.mark.parametrize("tickets, kb", INPUTS, ids=["root", "eval", "edge"])
def test_contract(make_config, fake_embedder, retriever, tickets, kb):
    config = make_config(tickets=tickets, kb=kb, retriever=retriever)
    assert run(config).exit_code == 0
    kb_ids = {a["article_id"] for a in json.loads(kb.read_text())["articles"]}
    normalised = json.loads((config.artifacts_dir / "normalised_tickets.json").read_text())["tickets"]
    results = _results(config)
    assert [r["ticket_id"] for r in results] == [t["ticket_id"] for t in normalised]
    for record in results:
        RetrievalResult.model_validate(record)
        hits = record["retrieved_articles"]
        assert len(hits) <= config.top_k
        assert [(-h["score"], h["article_id"]) for h in hits] == sorted((-h["score"], h["article_id"]) for h in hits)
        for hit in hits:
            assert config.effective_min_score <= hit["score"] <= 1.0
            assert hit["article_id"] in kb_ids


@pytest.mark.parametrize("retriever", ["tfidf", "embedding"])
def test_empty_kb_gives_empty_results(make_config, fake_embedder, retriever):
    config = make_config(kb=FIXTURES / "empty_kb/kb_articles.json", retriever=retriever)
    outcome = run(config)
    assert outcome.exit_code == 0
    assert all(r["retrieved_articles"] == [] for r in _results(config))
    assert outcome.manifest["counts"]["tickets_without_evidence"] == 3


def test_empty_tickets_list(make_config):
    config = make_config(tickets=FIXTURES / "empty_tickets/tickets.json")
    assert run(config).exit_code == 0
    assert _results(config) == []


@pytest.mark.parametrize("ticket_id", ["E-2010", "E-2011", "E-2012"])
def test_no_match_tickets_return_empty_tfidf(make_config, ticket_id):
    config = make_config(tickets=EVAL / "tickets.json", kb=EVAL / "kb_articles.json")
    run(config)
    record = next(r for r in _results(config) if r["ticket_id"] == ticket_id)
    assert record["retrieved_articles"] == []


def test_empty_ticket_is_not_sent_to_embedder(make_config, fake_embedder):
    config = make_config(tickets=EVAL / "tickets.json", kb=EVAL / "kb_articles.json", retriever="embedding")
    run(config)
    sent = [text for call in fake_embedder.calls for text in call]
    assert "" not in sent and all(text.strip() for text in sent)
    record = next(r for r in _results(config) if r["ticket_id"] == "E-2011")
    assert record["retrieved_articles"] == []


def test_min_score_is_respected(make_config):
    strict = make_config(min_score=0.99)
    run(strict)
    assert all(r["retrieved_articles"] == [] for r in _results(strict))


def test_top_k_is_respected(make_config):
    config = make_config(tickets=EVAL / "tickets.json", kb=EVAL / "kb_articles.json", top_k=1, min_score=0.0)
    run(config)
    assert all(len(r["retrieved_articles"]) <= 1 for r in _results(config))
