import json
from pathlib import Path

import pytest

from pipeline.config import Config

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
FIXTURES = DATA / "fixtures"
EVAL = DATA / "eval"


def load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture
def make_config(tmp_path):
    """Config pointing at given inputs, writing into an isolated tmp dir."""

    def _make(tickets: Path = ROOT / "tickets.json", kb: Path = ROOT / "kb_articles.json", **overrides) -> Config:
        settings = {"provider": "stub", "model": "stub", **overrides}
        return Config(tickets_path=tickets, kb_path=kb, out_dir=tmp_path, **settings)

    return _make


SECRET_VARS = ("OPENAI_API_KEY", "OLLAMA_API_KEY", "OLLAMA_BASE_URL")


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    """Tests never touch the network or the real .env: no keys, no dotenv, no real embedder."""
    import run_pipeline
    from pipeline import stages

    for var in SECRET_VARS:
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr(run_pipeline, "load_dotenv", lambda *args, **kwargs: False)

    def no_network(config):
        raise AssertionError("tests must not create a real embedder; use the fake_embedder fixture")

    monkeypatch.setattr(stages, "make_embedder", no_network)


class FakeEmbedder:
    """Deterministic offline embedder: hashed bag of stemmed tokens. Records every call."""

    provider = "fake"
    model = "fake-embed"
    dims = 64

    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def vector(self, text: str) -> list[float]:
        import hashlib

        from pipeline.retrieval import tokens

        vec = [0.0] * self.dims
        for token in tokens(text):
            vec[int(hashlib.sha256(token.encode()).hexdigest(), 16) % self.dims] += 1.0
        return vec

    def embed(self, texts: list[str]) -> list[list[float]]:
        self.calls.append(list(texts))
        return [self.vector(t) for t in texts]


@pytest.fixture
def fake_embedder(monkeypatch):
    """Routes embedding retrieval to FakeEmbedder (and satisfies the credential check)."""
    from pipeline import stages

    fake = FakeEmbedder()
    monkeypatch.setenv("OPENAI_API_KEY", "test-key-not-real")
    monkeypatch.setattr(stages, "make_embedder", lambda config: fake)
    return fake
