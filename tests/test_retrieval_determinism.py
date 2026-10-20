"""T2: retrieval artifacts are byte-identical across runs; ties break by article_id."""

import json

import pytest

from pipeline.normalise import normalise_ticket
from pipeline.retrieval import TfidfRetriever, retrieve
from pipeline.runner import run
from pipeline.schemas import KBArticle
from tests.conftest import EVAL

pytestmark = pytest.mark.stage2

ARTIFACTS = ("retrieval_results.json", "retrieval_debug.json", "artifacts/kb_index.json")


def _run_twice(make_config, tmp_path, **overrides):
    first_dir, second_dir = tmp_path / "first", tmp_path / "second"
    kwargs = dict(tickets=EVAL / "tickets.json", kb=EVAL / "kb_articles.json", **overrides)
    for out in (first_dir, second_dir):
        config = make_config(**kwargs)
        config = type(config)(**{**config.__dict__, "out_dir": out, "no_cache": True})
        assert run(config).exit_code == 0
    return first_dir, second_dir


@pytest.mark.parametrize("artifact", ARTIFACTS)
def test_tfidf_artifacts_byte_identical(make_config, tmp_path, artifact):
    first, second = _run_twice(make_config, tmp_path)
    assert (first / artifact).read_bytes() == (second / artifact).read_bytes()


@pytest.mark.parametrize("artifact", ARTIFACTS)
def test_embedding_artifacts_byte_identical(make_config, tmp_path, fake_embedder, artifact):
    first, second = _run_twice(make_config, tmp_path, retriever="embedding")
    assert (first / artifact).read_bytes() == (second / artifact).read_bytes()


def test_ties_break_by_article_id():
    content = "Invoice PDFs are available under Billing > Documents."
    articles = [
        KBArticle(article_id=aid, title="Invoices", category="billing", updated_at=None, content=content)
        for aid in ("KB-B", "KB-C", "KB-A")
    ]
    ticket = normalise_ticket({"ticket_id": "T", "subject": "invoice", "message": "where are invoice PDFs"}, 4000, "s")
    result, debug = retrieve(TfidfRetriever(articles), ticket, top_k=2, min_score=0.0)
    assert [a.article_id for a in result.retrieved_articles] == ["KB-A", "KB-B"]
    assert [c["article_id"] for c in debug["candidates"]] == ["KB-A", "KB-B", "KB-C"]
    assert len({c["score"] for c in debug["candidates"]}) == 1


def test_results_follow_input_ticket_order(make_config):
    config = make_config(tickets=EVAL / "tickets.json", kb=EVAL / "kb_articles.json")
    run(config)
    results = json.loads((config.out_dir / "retrieval_results.json").read_text())["results"]
    expected = [t["ticket_id"] for t in json.loads((EVAL / "tickets.json").read_text())["tickets"]]
    assert [r["ticket_id"] for r in results] == expected
