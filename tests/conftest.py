import json
from pathlib import Path

import pytest

from pipeline.config import Config
from pipeline.orchestrator import Pipeline, Stage
from pipeline.stages import build_specs

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
FIXTURES = DATA / "fixtures"
EVAL = DATA / "eval"


LATEST_STAGE = Pipeline(build_specs()).last_implemented()
NEXT_UNBUILT = Stage(LATEST_STAGE + 1) if LATEST_STAGE < Stage.RESULTS_FINALISED else None


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

    real_factory = stages.make_chat_provider

    def stub_only(config):
        if config.provider != "stub":
            raise AssertionError("tests must not create a real LLM provider; use the scripted_llm fixture")
        return real_factory(config)

    monkeypatch.setattr(stages, "make_chat_provider", stub_only)


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


class ScriptedProvider:
    """Fake LLM: replies come from a list (consumed in order) or a function of the messages."""

    name = "scripted"
    model = "scripted-1"

    def __init__(self, replies=None, respond=None) -> None:
        self.replies = list(replies or [])
        self.respond = respond
        self.calls: list[list[dict]] = []

    def params(self, max_tokens, temperature):
        return {"max_tokens": max_tokens, "temperature": temperature}

    def complete(self, messages, params, json_schema):
        from pipeline.llm import ChatResponse, LLMTransportError

        self.calls.append(messages)
        reply = self.respond(messages) if self.respond else self.replies.pop(0)
        if isinstance(reply, Exception):
            if isinstance(reply, LLMTransportError):
                raise reply
            raise LLMTransportError(str(reply))
        return ChatResponse(text=reply, usage={"prompt_tokens": 10, "completion_tokens": 5})


def valid_reply(ticket_id: str, **overrides) -> str:
    import json

    reply = {
        "ticket_id": ticket_id,
        "issue_type": "billing",
        "urgency": "medium",
        "resolution_action": "answer_from_kb",
        "customer_sensitive": True,
        "requires_refund_caution": False,
        "rationale": "Matches KB-001.",
    }
    reply.update(overrides)
    return json.dumps(reply)


def ticket_id_from(messages) -> str:
    import json
    import re

    user = next(m["content"] for m in messages if m["role"] == "user")
    return json.loads(re.search(r"<ticket>\s*(\{.*?\})\s*</ticket>", user, re.DOTALL).group(1))["ticket_id"]


@pytest.fixture
def scripted_llm(monkeypatch):
    """Install a ScriptedProvider for pipeline runs; credentials are faked so no network is used."""
    from pipeline import stages

    holder = {}

    def install(replies=None, respond=None) -> ScriptedProvider:
        provider = ScriptedProvider(replies, respond)
        holder["provider"] = provider
        monkeypatch.setattr(stages, "make_chat_provider", lambda config: provider)
        return provider

    return install


def draft_reply(ticket_id: str, text: str = "Thanks for reaching out. A support specialist will follow up.", citations=None) -> str:
    import json

    return json.dumps({"ticket_id": ticket_id, "draft_response": text, "citations": citations or []})


def is_draft_prompt(messages) -> bool:
    return "<classification>" in next(m["content"] for m in messages if m["role"] == "user")


def first_evidence_id(messages) -> str | None:
    import re

    user = next(m["content"] for m in messages if m["role"] == "user")
    found = re.findall(r"^\[(KB-[^\]]+)\]", user, re.MULTILINE)
    return found[0] if found else None


GOOD_TEXT = "Thanks for reaching out. We have escalated this to our specialist team. Never share your password or codes with anyone."


def good_draft(messages, ticket_id: str) -> str:
    """A reply that satisfies every hard drafting rule for any classification."""
    evidence = first_evidence_id(messages)
    return draft_reply(ticket_id, GOOD_TEXT, [evidence] if evidence else [])


def route(classify=None, draft=None):
    """Responder for ScriptedProvider: classification prompts and drafting prompts get different replies."""

    def respond(messages):
        ticket_id = ticket_id_from(messages)
        if is_draft_prompt(messages):
            return (draft or good_draft)(messages, ticket_id)
        return classify(messages, ticket_id) if classify else valid_reply(ticket_id)

    return respond


def eval_gold() -> dict[str, dict]:
    return {g["ticket_id"]: g for g in load(EVAL / "gold.json")["expectations"]}
