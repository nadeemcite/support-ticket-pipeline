"""An evaluator with only OPENAI_API_KEY: run_pipeline picks openai (LLM + embeddings) and never asks for OLLAMA_*."""

import json

import pytest

import run_pipeline
from tests.conftest import ROOT, route

pytestmark = pytest.mark.stage5


def test_only_openai_key_runs_end_to_end(fake_embedder, scripted_llm, monkeypatch, tmp_path, capsys):
    for var in ("OLLAMA_API_KEY", "OLLAMA_BASE_URL", "LLM_PROVIDER", "RETRIEVER", "OPENAI_MODEL"):
        monkeypatch.delenv(var, raising=False)
    provider = scripted_llm(respond=route())  # the mocked client; fake_embedder sets OPENAI_API_KEY and mocks embeddings
    code = run_pipeline.main(["--tickets", str(ROOT / "tickets.json"), "--kb", str(ROOT / "kb_articles.json"), "--out-dir", str(tmp_path)])
    captured = capsys.readouterr()
    assert code in (0, 1), captured.err
    assert "OLLAMA" not in captured.out + captured.err
    assert "using the openai provider" in captured.err
    config = json.loads((tmp_path / "artifacts" / "run_manifest.json").read_text())["config"]
    assert (config["provider"], config["model"], config["retriever"]) == ("openai", "gpt-4o-mini", "embedding")
    assert provider.calls and fake_embedder.calls


def test_no_ollama_variable_is_read_for_openai(monkeypatch):
    from pipeline.config import load_config

    monkeypatch.delenv("OLLAMA_API_KEY", raising=False)
    config = load_config({}, env={"OPENAI_API_KEY": "k"}, dotenv_path=None)
    config.require_credentials(env={"OPENAI_API_KEY": "k"})
