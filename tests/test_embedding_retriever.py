"""Embedding path: PII never leaves (P-EXT), calls are logged and batched, failures are fatal and clear."""

import json

import pytest

from pipeline import pii, stages
from pipeline.cache import JsonCache
from pipeline.retrieval import CachedEmbedder, EmbeddingError, LiteLLMEmbedder, PIILeakError
from pipeline.runner import EXIT_FATAL, run
from tests.conftest import EVAL, FakeEmbedder

pytestmark = pytest.mark.stage2


def test_only_masked_text_reaches_the_embedder(make_config, fake_embedder):
    config = make_config(tickets=EVAL / "tickets.json", kb=EVAL / "kb_articles.json", retriever="embedding")
    assert run(config).exit_code == 0
    sent = [text for call in fake_embedder.calls for text in call]
    raw = json.loads((EVAL / "tickets.json").read_text())["tickets"]
    raw_values = [d.value for t in raw for d in pii.detect(t["subject"] + " " + t["message"])]
    assert raw_values
    for text in sent:
        assert not pii.contains_pii(text)
        assert not any(value in text for value in raw_values)
    assert any("[CARD_NUMBER_1]" in text for text in sent)


def test_cached_embedder_refuses_raw_pii(tmp_path):
    embedder = CachedEmbedder(FakeEmbedder(), JsonCache(tmp_path), clock=lambda: "t")
    with pytest.raises(PIILeakError):
        embedder.embed(["contact me at jane.doe@example.com"], purpose="ticket")
    assert embedder.inner.calls == []


def test_memo_logs_each_text_once_per_run(tmp_path):
    embedder = CachedEmbedder(FakeEmbedder(), JsonCache(tmp_path), clock=lambda: "t")
    embedder.embed(["alpha", "beta", "alpha"], purpose="kb_article")
    embedder.embed(["beta"], purpose="ticket")
    assert [r["purpose"] for r in embedder.log] == ["kb_article", "kb_article"]
    assert embedder.inner.calls == [["alpha", "beta"]]  # duplicates de-duplicated, one API call
    assert embedder.api_calls == 1


def test_embedding_log_artifact(make_config, fake_embedder):
    config = make_config(retriever="embedding")
    run(config)
    lines = [json.loads(line) for line in (config.artifacts_dir / "embedding_calls.jsonl").read_text().splitlines()]
    assert lines and {r["purpose"] for r in lines} == {"kb_article", "kb_sentence", "ticket"}
    for record in lines:
        assert set(record) == {"timestamp", "purpose", "provider", "model", "text_hash", "chars", "cached"}
        assert record["text_hash"].startswith("sha256:")


def test_tfidf_run_writes_empty_embedding_log(make_config):
    config = make_config()
    run(config)
    assert (config.artifacts_dir / "embedding_calls.jsonl").read_text() == ""


def test_missing_openai_key_is_fatal_with_clear_message(make_config):
    outcome = run(make_config(retriever="embedding"))
    assert outcome.exit_code == EXIT_FATAL
    assert "OPENAI_API_KEY" in outcome.error and "--retriever tfidf" in outcome.error


def test_embedding_api_failure_is_fatal(make_config, monkeypatch):
    class Broken(FakeEmbedder):
        def embed(self, texts):
            raise EmbeddingError("embedding call to fake failed: AuthenticationError")

    monkeypatch.setenv("OPENAI_API_KEY", "test-key-not-real")
    monkeypatch.setattr(stages, "make_embedder", lambda config: Broken())
    outcome = run(make_config(retriever="embedding"))
    assert outcome.exit_code == EXIT_FATAL and "EmbeddingError" in outcome.error
    assert outcome.manifest["final_stage"] == "FAILED"


def test_litellm_errors_are_wrapped(monkeypatch):
    import litellm

    def boom(**kwargs):
        raise RuntimeError("401 invalid api key")

    monkeypatch.setattr(litellm, "embedding", boom)
    with pytest.raises(EmbeddingError, match="RuntimeError: 401"):
        LiteLLMEmbedder("text-embedding-3-small").embed(["hello"])


def test_litellm_response_order_is_restored(monkeypatch):
    import litellm

    class Response:
        data = [{"index": 1, "embedding": [0.0, 1.0]}, {"index": 0, "embedding": [1.0, 0.0]}]

    monkeypatch.setattr(litellm, "embedding", lambda **kwargs: Response())
    assert LiteLLMEmbedder("m").embed(["a", "b"]) == [[1.0, 0.0], [0.0, 1.0]]


def test_cross_lingual_needs_embeddings_documented_by_eval_not_unit_tests():
    """Placeholder-free reminder: real cross-lingual quality is measured by evals/retrieval_eval.py,
    because the offline fake embedder is lexical and cannot match es/fr/de/pt to English."""
    assert FakeEmbedder().vector("contraseña") != FakeEmbedder().vector("password")
