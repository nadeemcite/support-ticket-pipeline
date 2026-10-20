"""Run configuration (SPEC §2.2). Precedence: CLI flags > environment / .env > defaults.

Secrets are read from the environment only when needed and are never stored on ``Config``
or written to any artifact.
"""

import os
from collections.abc import Mapping
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from dotenv import dotenv_values

PROVIDERS = ("ollama", "openai", "stub")
RETRIEVERS = ("embedding", "tfidf")

# Minimum similarity per retriever (SPEC §2.2), chosen from the Stage 2 threshold sweep. Cosine
# scales differ: embedding similarities of unrelated texts sit around 0.1-0.2 (highest no-match
# ticket 0.21, lowest relevant top-1 0.39); TF-IDF scores of unrelated texts are ~0.
DEFAULT_MIN_SCORE = {"embedding": 0.25, "tfidf": 0.05}

DEFAULT_MODELS = {
    "ollama": "glm-5.2",
    "openai": "gpt-6.1-sol",
    "stub": "stub",
}

CREDENTIAL_VARS = {
    "ollama": ("OLLAMA_API_KEY", "OLLAMA_BASE_URL"),
    "openai": ("OPENAI_API_KEY",),
    "stub": (),
}
EMBEDDING_CREDENTIAL_VARS = ("OPENAI_API_KEY",)

# Default salt for PII hashes. Hashes link PII occurrences across artifacts without revealing
# values; override PII_HASH_SALT in production so hashes can't be brute-forced from a known salt.
DEFAULT_PII_SALT = "ticket-triage-pii-v1"


class ConfigError(ValueError):
    """Invalid or incomplete configuration. Fatal (exit 2)."""


def normalise_model_id(model: str) -> str:
    """``glm-5.2:cloud`` -> ``glm-5.2``. The ``:cloud`` suffix is a local Ollama CLI convention."""
    model = model.strip()
    return model.removesuffix(":cloud").removesuffix("-cloud") if model.endswith("cloud") else model


@dataclass(frozen=True)
class Config:
    provider: str = "ollama"
    model: str = DEFAULT_MODELS["ollama"]
    fast_model: str = "glm-5.3-flash"
    temperature: float = 0.0
    max_tokens: int = 1500
    timeout_s: int = 60
    retriever: str = "tfidf"
    embedding_model: str = "text-embedding-3-small"
    top_k: int = 3
    min_score: float | None = None  # None -> DEFAULT_MIN_SCORE[retriever]
    max_ticket_chars: int = 4000
    max_draft_chars: int = 1500
    tickets_path: Path = Path("tickets.json")
    kb_path: Path = Path("kb_articles.json")
    out_dir: Path = Path(".")
    no_cache: bool = False
    log_prompts: bool = False
    pii_salt: str = field(default=DEFAULT_PII_SALT, repr=False)

    @property
    def effective_min_score(self) -> float:
        return DEFAULT_MIN_SCORE[self.retriever] if self.min_score is None else self.min_score

    @property
    def artifacts_dir(self) -> Path:
        return self.out_dir / "artifacts"

    @property
    def cache_dir(self) -> Path:
        return self.out_dir / ".cache"

    def public_dict(self) -> dict[str, Any]:
        """Config as recorded in the manifest: no salt, paths as strings."""
        data = asdict(self)
        data.pop("pii_salt")
        data["min_score"] = self.effective_min_score
        return {key: str(value) if isinstance(value, Path) else value for key, value in data.items()}

    def require_credentials(self, env: Mapping[str, str] | None = None) -> None:
        env = os.environ if env is None else env
        missing = [var for var in CREDENTIAL_VARS[self.provider] if not env.get(var)]
        if missing:
            raise ConfigError(
                f"{', '.join(missing)} not set for provider '{self.provider}' "
                "- export it, add it to .env, or use --provider stub"
            )

    def require_embedding_credentials(self, env: Mapping[str, str] | None = None) -> None:
        if self.retriever != "embedding":
            return
        env = os.environ if env is None else env
        missing = [var for var in EMBEDDING_CREDENTIAL_VARS if not env.get(var)]
        if missing:
            raise ConfigError(
                f"{', '.join(missing)} not set for embedding retrieval "
                "- export it, add it to .env, or use --retriever tfidf"
            )


def _env_with_dotenv(env: Mapping[str, str] | None, dotenv_path: Path | None) -> dict[str, str]:
    merged: dict[str, str] = {}
    if dotenv_path is not None and Path(dotenv_path).is_file():
        merged.update({k: v for k, v in dotenv_values(dotenv_path).items() if v is not None})
    merged.update(os.environ if env is None else env)
    return merged


def load_config(
    cli: Mapping[str, Any] | None = None,
    env: Mapping[str, str] | None = None,
    dotenv_path: Path | None = Path(".env"),
) -> Config:
    cli = {k: v for k, v in (cli or {}).items() if v is not None}
    environ = _env_with_dotenv(env, dotenv_path)

    def pick(cli_key: str, env_key: str, default: Any, cast: type = str) -> Any:
        if cli_key in cli:
            return cast(cli[cli_key])
        if environ.get(env_key):
            try:
                return cast(environ[env_key])
            except ValueError as exc:
                raise ConfigError(f"{env_key}={environ[env_key]!r} is not a valid {cast.__name__}") from exc
        return default

    provider = pick("provider", "LLM_PROVIDER", "ollama").strip().lower()
    if provider not in PROVIDERS:
        raise ConfigError(f"Unknown provider {provider!r}; expected one of {', '.join(PROVIDERS)}")

    model = normalise_model_id(pick("model", "LLM_MODEL", DEFAULT_MODELS[provider]))
    fast_model = normalise_model_id(pick("fast_model", "LLM_FAST_MODEL", "glm-5.3-flash"))

    # Offline by default with the stub provider; embeddings otherwise (OD-2).
    retriever = pick("retriever", "RETRIEVER", "tfidf" if provider == "stub" else "embedding").strip().lower()
    if retriever not in RETRIEVERS:
        raise ConfigError(f"Unknown retriever {retriever!r}; expected one of {', '.join(RETRIEVERS)}")

    config = Config(
        provider=provider,
        model=model,
        fast_model=fast_model,
        temperature=pick("temperature", "LLM_TEMPERATURE", 0.0, float),
        max_tokens=pick("max_tokens", "LLM_MAX_TOKENS", 1500, int),
        timeout_s=pick("timeout_s", "LLM_TIMEOUT_S", 60, int),
        retriever=retriever,
        embedding_model=pick("embedding_model", "EMBEDDING_MODEL", "text-embedding-3-small"),
        top_k=pick("top_k", "RETRIEVAL_TOP_K", 3, int),
        min_score=pick("min_score", "RETRIEVAL_MIN_SCORE", None, float),
        max_ticket_chars=pick("max_ticket_chars", "MAX_TICKET_CHARS", 4000, int),
        max_draft_chars=pick("max_draft_chars", "MAX_DRAFT_CHARS", 1500, int),
        tickets_path=Path(pick("tickets", "TICKETS_PATH", "tickets.json")),
        kb_path=Path(pick("kb", "KB_PATH", "kb_articles.json")),
        out_dir=Path(pick("out_dir", "OUT_DIR", ".")),
        no_cache=bool(cli.get("no_cache", False)),
        log_prompts=bool(cli.get("log_prompts", False)),
        pii_salt=environ.get("PII_HASH_SALT") or DEFAULT_PII_SALT,
    )
    if config.top_k < 1:
        raise ConfigError("RETRIEVAL_TOP_K must be >= 1")
    if not 0.0 <= config.effective_min_score <= 1.0:
        raise ConfigError("RETRIEVAL_MIN_SCORE must be within [0, 1]")
    if config.max_ticket_chars < 1:
        raise ConfigError("MAX_TICKET_CHARS must be >= 1")
    return config
