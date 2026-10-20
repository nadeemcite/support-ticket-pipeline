"""LLM client (DESIGN §6.3, SPEC §9, rules L1-L7 and O3).

* Providers: ``ollama`` (Ollama Cloud, LiteLLM ``ollama_chat/``), ``openai`` (LiteLLM ``openai/``) and
  ``stub`` (deterministic, offline). All return raw text; callers validate it.
* ``prompt_hash`` = sha256 of canonical ``{provider, model, params, prompt_version, messages}`` (L4).
* Every attempt is appended to ``llm_calls.jsonl`` before its result is used (L5), with hashes
  only, never prompt text (P-LOG). Results are cached by prompt hash (R2).
* Calls are refused outside the classification / drafting stages (O3) and when a prompt contains
  raw PII (P-LLM).
"""

import json
import os
import re
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from pipeline import pii
from pipeline.cache import JsonCache
from pipeline.io_utils import atomic_write_json, canonical_json, sha256_canonical
from pipeline.orchestrator import Stage
from pipeline.taxonomy import LLMStage

SEED = 42
TRANSPORT_RETRIES = 3

# O3: which pipeline stage may make which kind of LLM call.
ALLOWED_STAGE = {LLMStage.CLASSIFICATION: Stage.TICKETS_CLASSIFIED, LLMStage.DRAFTING: Stage.RESPONSES_DRAFTED}

_FENCE_RE = re.compile(r"^\s*```(?:json)?\s*(.*?)\s*```\s*$", re.DOTALL)


class LLMStageError(RuntimeError):
    """An LLM call was attempted outside its stage (O3). Always a programming bug (exit 2)."""


class LLMTransportError(RuntimeError):
    """The provider failed after transport retries (network, auth, rate limit, timeout)."""


@dataclass(frozen=True)
class ChatResponse:
    text: str
    usage: dict[str, int] = field(default_factory=dict)


class ChatProvider(Protocol):
    name: str
    model: str

    def params(self, max_tokens: int, temperature: float) -> dict[str, Any]: ...

    def complete(self, messages: list[dict[str, str]], params: dict[str, Any], json_schema: dict | None) -> ChatResponse: ...


class LiteLLMProvider:
    """Ollama Cloud or OpenAI through LiteLLM. Keys come from the environment, never from config."""

    def __init__(self, name: str, model: str, timeout_s: int = 60) -> None:
        if name not in ("ollama", "openai"):
            raise ValueError(f"LiteLLMProvider does not handle {name!r}")
        self.name = name
        self.model = model
        self.timeout_s = timeout_s

    def params(self, max_tokens: int, temperature: float) -> dict[str, Any]:
        # OpenAI reasoning models take max_completion_tokens; Ollama takes max_tokens (SPEC §2.2).
        token_key = "max_completion_tokens" if self.name == "openai" else "max_tokens"
        return {token_key: max_tokens, "temperature": temperature, "seed": SEED}

    def _route(self) -> dict[str, Any]:
        if self.name == "ollama":
            base = os.environ.get("OLLAMA_BASE_URL", "https://ollama.com/v1").rstrip("/").removesuffix("/v1")
            return {"model": f"ollama_chat/{self.model}", "api_base": base, "api_key": os.environ.get("OLLAMA_API_KEY")}
        return {"model": f"openai/{self.model}"}

    def complete(self, messages: list[dict[str, str]], params: dict[str, Any], json_schema: dict | None) -> ChatResponse:
        import litellm  # imported lazily: offline runs never load it

        litellm.drop_params = True  # e.g. some reasoning models reject temperature/seed
        if json_schema is not None and self.name == "openai":
            response_format: dict[str, Any] = {
                "type": "json_schema",
                "json_schema": {"name": "output", "schema": json_schema, "strict": True},
            }
        else:
            response_format = {"type": "json_object"}
        def call(call_params: dict[str, Any]):
            return litellm.completion(
                messages=messages,
                response_format=response_format,
                timeout=self.timeout_s,
                num_retries=TRANSPORT_RETRIES,
                **call_params,
                **self._route(),
            )

        try:
            try:
                response = call(params)
            except Exception as exc:
                swapped = swap_token_param(params, str(exc))
                if swapped is None:
                    raise
                response = call(swapped)  # the model wanted the other token-limit name: retry once
        except Exception as exc:  # LiteLLM raises provider-specific types; normalise them
            raise LLMTransportError(f"{type(exc).__name__}: {str(exc)[:200]}") from exc
        usage = getattr(response, "usage", None)
        return ChatResponse(
            text=response.choices[0].message.content or "",
            usage={
                "prompt_tokens": int(getattr(usage, "prompt_tokens", 0) or 0),
                "completion_tokens": int(getattr(usage, "completion_tokens", 0) or 0),
            },
        )


def swap_token_param(params: dict[str, Any], error: str) -> dict[str, Any] | None:
    """``max_tokens`` <-> ``max_completion_tokens`` when the API says the one we sent is not supported (older chat models
    reject ``max_completion_tokens``, reasoning models reject ``max_tokens``). None when the error is about something else."""
    text = error.lower()
    for sent, other in (("max_completion_tokens", "max_tokens"), ("max_tokens", "max_completion_tokens")):
        if sent in params and sent in text and ("unsupported" in text or "not supported" in text or "unknown" in text or "unrecognized" in text):
            swapped = {k: v for k, v in params.items() if k != sent}
            swapped[other] = params[sent]
            return swapped
    return None


def strip_fences(text: str) -> str:
    """Some models wrap JSON in a markdown fence even in JSON mode."""
    match = _FENCE_RE.match(text)
    return match.group(1) if match else text.strip()


def prompt_hash(provider: str, model: str, params: dict[str, Any], prompt_version: str, messages: list[dict[str, str]]) -> str:
    payload = {"provider": provider, "model": model, "params": params, "prompt_version": prompt_version, "messages": messages}
    return "sha256:" + sha256_canonical(payload)


@dataclass(frozen=True)
class CallResult:
    text: str
    prompt_hash: str
    cached: bool
    latency_ms: float
    usage: dict[str, int]
    error: str | None = None


@dataclass
class LLMClient:
    provider: ChatProvider
    max_tokens: int
    temperature: float
    log_path: Path
    clock: Callable[[], str]
    cache: JsonCache | None = None
    cache_namespace: str = "llm"
    current_stage: Callable[[], Stage | None] = lambda: None
    prompts_dir: Path | None = None  # --log-prompts: masked prompts written here, keyed by hash
    records: list[dict[str, Any]] = field(default_factory=list)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)  # evals call from threads

    def call(self, llm_stage: LLMStage, messages: list[dict[str, str]], prompt_version: str, json_schema: dict | None) -> CallResult:
        running = self.current_stage()
        if running != ALLOWED_STAGE[llm_stage]:
            name = running.name if running is not None else "no stage"
            raise LLMStageError(f"{llm_stage.value} call refused during {name}; allowed only in {ALLOWED_STAGE[llm_stage].name}")
        for message in messages:
            if pii.contains_pii(message["content"]):
                raise pii.PIILeakError(f"refusing to send a {llm_stage.value} prompt containing raw PII (P-LLM)")

        params = self.provider.params(self.max_tokens, self.temperature)
        digest = prompt_hash(self.provider.name, self.provider.model, params, prompt_version, messages)
        if self.prompts_dir is not None:
            atomic_write_json(self.prompts_dir / f"{digest.removeprefix('sha256:')}.json", {"prompt_version": prompt_version, "messages": messages})

        cached = self.cache.get(self.cache_namespace, digest.removeprefix("sha256:")) if self.cache else None
        if cached is not None:
            return CallResult(text=cached["text"], prompt_hash=digest, cached=True, latency_ms=0.0, usage=cached.get("usage", {}))
        start = time.perf_counter()
        try:
            response = self.provider.complete(messages, params, json_schema)
        except LLMTransportError as exc:
            latency = round((time.perf_counter() - start) * 1000, 1)
            return CallResult(text="", prompt_hash=digest, cached=False, latency_ms=latency, usage={}, error=str(exc))
        latency = round((time.perf_counter() - start) * 1000, 1)
        if self.cache is not None:
            self.cache.put({"text": response.text, "usage": response.usage}, self.cache_namespace, digest.removeprefix("sha256:"))
        return CallResult(text=response.text, prompt_hash=digest, cached=False, latency_ms=latency, usage=response.usage)

    def log(self, *, llm_stage: LLMStage, ticket_id: str, result: CallResult, prompt_version: str, input_artifacts: list[str],
            output_artifact: str, attempt: int, status: str) -> None:
        """Append one line per attempt (SPEC §6.8). Called before the attempt's result is used (L5)."""
        record = {
            "stage": llm_stage.value,
            "ticket_id": ticket_id,
            "ticket_ids": [ticket_id],
            "timestamp": self.clock(),
            "provider": self.provider.name,
            "model": self.provider.model,
            "prompt_hash": result.prompt_hash,
            "prompt_version": prompt_version,
            "input_artifacts": input_artifacts,
            "output_artifact": output_artifact,
            "attempt": attempt,
            "status": status,
            "cached": result.cached,
            "latency_ms": result.latency_ms,
            "usage": result.usage,
        }
        if result.error:
            record["error"] = result.error[:200]
        with self._lock:
            self.records.append(record)
            with self.log_path.open("a", encoding="utf-8") as handle:
                handle.write(canonical_json(record) + "\n")


WITHHELD = "[previous output withheld: it contained personal data]"


def echo_for_retry(text: str) -> str:
    """Model output fed back in a retry prompt. Output containing PII is withheld so a retry can't trip P-LLM."""
    return WITHHELD if pii.contains_pii(text) else text[:2000]


def parse_json_object(text: str) -> dict[str, Any]:
    data = json.loads(strip_fences(text))
    if not isinstance(data, dict):
        raise ValueError("expected a JSON object")
    return data
