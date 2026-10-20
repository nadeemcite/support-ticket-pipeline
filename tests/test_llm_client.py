"""LLM client: logging (L5, P-LOG), prompt hashing (L4), caching (R2), stage guard (O3), provider params."""

import json

import pytest

from pipeline import llm
from pipeline.cache import JsonCache
from pipeline.llm import LiteLLMProvider, LLMClient, LLMStageError, LLMTransportError, prompt_hash, strip_fences
from pipeline.orchestrator import Stage
from pipeline.pii import PIILeakError
from pipeline.taxonomy import LLMStage
from tests.conftest import ScriptedProvider

pytestmark = pytest.mark.stage3

MESSAGES = [{"role": "system", "content": "sys"}, {"role": "user", "content": "classify T-1 about invoices"}]


def _client(tmp_path, provider, stage=Stage.TICKETS_CLASSIFIED, cache=None):
    return LLMClient(provider=provider, max_tokens=100, temperature=0.0, log_path=tmp_path / "log.jsonl",
                     clock=lambda: "t", cache=cache, current_stage=lambda: stage)


# --- prompt hash ---------------------------------------------------------------------------------

def test_prompt_hash_is_stable_and_sensitive_to_every_input():
    base = prompt_hash("ollama", "glm-5.2", {"max_tokens": 1}, "classify.v1", MESSAGES)
    assert base == prompt_hash("ollama", "glm-5.2", {"max_tokens": 1}, "classify.v1", [dict(m) for m in MESSAGES])
    assert base.startswith("sha256:")
    variants = [
        prompt_hash("openai", "glm-5.2", {"max_tokens": 1}, "classify.v1", MESSAGES),
        prompt_hash("ollama", "glm-5.3-flash", {"max_tokens": 1}, "classify.v1", MESSAGES),
        prompt_hash("ollama", "glm-5.2", {"max_tokens": 2}, "classify.v1", MESSAGES),
        prompt_hash("ollama", "glm-5.2", {"max_tokens": 1}, "classify.v2", MESSAGES),
        prompt_hash("ollama", "glm-5.2", {"max_tokens": 1}, "classify.v1", MESSAGES[:1]),
    ]
    assert base not in variants and len(set(variants)) == len(variants)


# --- stage guard ---------------------------------------------------------------------------------

@pytest.mark.parametrize(
    "stage, llm_stage, allowed",
    [
        (Stage.TICKETS_CLASSIFIED, LLMStage.CLASSIFICATION, True),
        (Stage.RESPONSES_DRAFTED, LLMStage.DRAFTING, True),
        (Stage.EVIDENCE_RETRIEVED, LLMStage.CLASSIFICATION, False),
        (Stage.TICKETS_CLASSIFIED, LLMStage.DRAFTING, False),
        (Stage.RESPONSES_DRAFTED, LLMStage.CLASSIFICATION, False),
        (None, LLMStage.CLASSIFICATION, False),
    ],
)
def test_stage_guard(tmp_path, stage, llm_stage, allowed):
    provider = ScriptedProvider(["{}"])
    client = _client(tmp_path, provider, stage=stage)
    if allowed:
        client.call(llm_stage, MESSAGES, "v1", None)
    else:
        with pytest.raises(LLMStageError):
            client.call(llm_stage, MESSAGES, "v1", None)
        assert provider.calls == []


def test_raw_pii_in_prompt_is_refused(tmp_path):
    provider = ScriptedProvider(["{}"])
    with pytest.raises(PIILeakError):
        _client(tmp_path, provider).call(LLMStage.CLASSIFICATION, [{"role": "user", "content": "mail me at a@example.com"}], "v1", None)
    assert provider.calls == []


# --- logging -------------------------------------------------------------------------------------

def test_log_record_fields_and_no_prompt_text(tmp_path):
    client = _client(tmp_path, ScriptedProvider(["{}"]))
    result = client.call(LLMStage.CLASSIFICATION, MESSAGES, "classify.v1", None)
    client.log(llm_stage=LLMStage.CLASSIFICATION, ticket_id="T-1", result=result, prompt_version="classify.v1",
               input_artifacts=["a.json"], output_artifact="ticket_classification.json", attempt=1, status="ok")
    text = (tmp_path / "log.jsonl").read_text()
    record = json.loads(text)
    for field in ("stage", "ticket_id", "timestamp", "provider", "model", "prompt_hash", "input_artifacts", "output_artifact"):
        assert field in record
    assert record["prompt_hash"] == result.prompt_hash and record["ticket_ids"] == ["T-1"]
    assert "classify T-1 about invoices" not in text  # hashes only (P-LOG)


def test_transport_error_is_returned_not_raised(tmp_path):
    result = _client(tmp_path, ScriptedProvider([LLMTransportError("APIConnectionError: down")])).call(
        LLMStage.CLASSIFICATION, MESSAGES, "v1", None)
    assert result.error and result.text == ""


def test_log_prompts_writes_masked_prompt_by_hash(tmp_path):
    client = _client(tmp_path, ScriptedProvider(["{}"]))
    client.prompts_dir = tmp_path / "prompts"
    result = client.call(LLMStage.CLASSIFICATION, MESSAGES, "classify.v1", None)
    dumped = json.loads((tmp_path / "prompts" / f"{result.prompt_hash.removeprefix('sha256:')}.json").read_text())
    assert dumped == {"prompt_version": "classify.v1", "messages": MESSAGES}


# --- cache ---------------------------------------------------------------------------------------

def test_cache_hit_skips_provider(tmp_path):
    provider = ScriptedProvider(['{"a": 1}'])
    cache = JsonCache(tmp_path / ".cache")
    first = _client(tmp_path, provider, cache=cache).call(LLMStage.CLASSIFICATION, MESSAGES, "v1", None)
    second = _client(tmp_path, provider, cache=cache).call(LLMStage.CLASSIFICATION, MESSAGES, "v1", None)
    assert len(provider.calls) == 1
    assert (first.cached, second.cached) == (False, True) and second.text == '{"a": 1}'
    assert second.prompt_hash == first.prompt_hash


def test_no_cache_reads_still_call_provider(tmp_path):
    provider = ScriptedProvider(['{"a": 1}', '{"a": 2}'])
    _client(tmp_path, provider, cache=JsonCache(tmp_path / ".cache")).call(LLMStage.CLASSIFICATION, MESSAGES, "v1", None)
    result = _client(tmp_path, provider, cache=JsonCache(tmp_path / ".cache", read_enabled=False)).call(
        LLMStage.CLASSIFICATION, MESSAGES, "v1", None)
    assert len(provider.calls) == 2 and result.text == '{"a": 2}'


def test_transport_errors_are_not_cached(tmp_path):
    provider = ScriptedProvider([LLMTransportError("down"), '{"ok": true}'])
    cache = JsonCache(tmp_path / ".cache")
    _client(tmp_path, provider, cache=cache).call(LLMStage.CLASSIFICATION, MESSAGES, "v1", None)
    result = _client(tmp_path, provider, cache=cache).call(LLMStage.CLASSIFICATION, MESSAGES, "v1", None)
    assert result.text == '{"ok": true}' and not result.cached


# --- provider adapter ----------------------------------------------------------------------------

def test_provider_params():
    assert LiteLLMProvider("openai", "gpt-6.1-sol").params(900, 0.0) == {"max_completion_tokens": 900, "temperature": 0.0, "seed": 42}
    assert LiteLLMProvider("ollama", "glm-5.2").params(900, 0.0) == {"max_tokens": 900, "temperature": 0.0, "seed": 42}
    with pytest.raises(ValueError):
        LiteLLMProvider("stub", "x")


class _Response:
    class _Choice:
        class message:  # noqa: N801 - mimics the LiteLLM response shape
            content = '{"ok": true}'

    choices = [_Choice()]

    class usage:  # noqa: N801
        prompt_tokens = 12
        completion_tokens = 3


@pytest.mark.parametrize(
    "name, model, expected_model, response_type",
    [("ollama", "glm-5.2", "ollama_chat/glm-5.2", "json_object"), ("openai", "gpt-6.1-sol", "openai/gpt-6.1-sol", "json_schema")],
)
def test_litellm_routing(monkeypatch, name, model, expected_model, response_type):
    import litellm

    captured = {}
    monkeypatch.setenv("OLLAMA_BASE_URL", "https://ollama.com/v1")
    monkeypatch.setenv("OLLAMA_API_KEY", "k")
    monkeypatch.setattr(litellm, "completion", lambda **kw: captured.update(kw) or _Response())
    provider = LiteLLMProvider(name, model)
    response = provider.complete(MESSAGES, provider.params(10, 0.0), {"type": "object"})
    assert captured["model"] == expected_model and captured["response_format"]["type"] == response_type
    assert response.text == '{"ok": true}' and response.usage == {"prompt_tokens": 12, "completion_tokens": 3}
    if name == "ollama":
        assert captured["api_base"] == "https://ollama.com" and captured["api_key"] == "k"


def test_litellm_errors_become_transport_errors(monkeypatch):
    import litellm

    def boom(**kwargs):
        raise RuntimeError("401 Unauthorized")

    monkeypatch.setattr(litellm, "completion", boom)
    with pytest.raises(LLMTransportError, match="RuntimeError: 401"):
        LiteLLMProvider("openai", "gpt-6.1-sol").complete(MESSAGES, {}, None)


@pytest.mark.parametrize("raw", ['{"a": 1}', '```json\n{"a": 1}\n```', '```\n{"a": 1}\n```', '  {"a": 1}  '])
def test_strip_fences(raw):
    assert llm.parse_json_object(raw) == {"a": 1}
    assert strip_fences(raw) == '{"a": 1}'
