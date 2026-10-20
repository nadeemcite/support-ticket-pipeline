"""Sample tickets retrieve their expected article first (SPEC §12.2)."""

import json
import os
from pathlib import Path

import pytest

from pipeline.config import Config
from pipeline.runner import run
from tests.conftest import ROOT

pytestmark = pytest.mark.stage2

EXPECTED_TOP1 = {"T-1001": "KB-001", "T-1002": "KB-002", "T-1003": "KB-003"}


def _top1(out_dir: Path) -> dict[str, str]:
    results = json.loads((out_dir / "retrieval_results.json").read_text())["results"]
    return {r["ticket_id"]: r["retrieved_articles"][0]["article_id"] for r in results}


def test_tfidf_sample_top1(make_config):
    config = make_config()
    assert run(config).exit_code == 0
    assert _top1(config.out_dir) == EXPECTED_TOP1


def test_fake_embedding_sample_top1(make_config, fake_embedder):
    config = make_config(retriever="embedding")
    assert run(config).exit_code == 0
    assert _top1(config.out_dir) == EXPECTED_TOP1


@pytest.mark.live
def test_live_openai_embedding_sample_top1(tmp_path, monkeypatch):
    """Real OpenAI embeddings. Run explicitly: pytest -m live (needs OPENAI_API_KEY in .env)."""
    from dotenv import dotenv_values

    from pipeline import stages
    from pipeline.retrieval import LiteLLMEmbedder

    key = dotenv_values(ROOT / ".env").get("OPENAI_API_KEY") or os.environ.get("OPENAI_API_KEY")
    if not key:
        pytest.skip("OPENAI_API_KEY not available")
    monkeypatch.setenv("OPENAI_API_KEY", key)
    monkeypatch.setattr(stages, "make_embedder", lambda config: LiteLLMEmbedder(config.embedding_model))
    config = Config(provider="stub", model="stub", retriever="embedding", out_dir=tmp_path,
                    tickets_path=ROOT / "tickets.json", kb_path=ROOT / "kb_articles.json")
    assert run(config).exit_code == 0
    assert _top1(tmp_path) == EXPECTED_TOP1
