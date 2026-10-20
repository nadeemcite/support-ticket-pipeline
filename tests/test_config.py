"""Config precedence (CLI > env/.env > defaults), model ID normalisation and credential checks."""

from pathlib import Path

import pytest

from pipeline.config import ConfigError, load_config, normalise_model_id

pytestmark = pytest.mark.stage1


KEYS = {"OLLAMA_API_KEY": "k", "OLLAMA_BASE_URL": "u"}


def test_defaults(tmp_path):
    config = load_config({}, env={**KEYS, "OPENAI_API_KEY": "k", "LLM_PROVIDER": "ollama"}, dotenv_path=None)
    assert (config.provider, config.model, config.fast_model) == ("ollama", "glm-5.2", "glm-5.3-flash")
    assert (config.top_k, config.temperature, config.retriever) == (3, 0.0, "embedding")
    assert config.min_score is None and config.effective_min_score == 0.25
    stub = load_config({"provider": "stub"}, env={}, dotenv_path=None)
    assert (stub.retriever, stub.effective_min_score) == ("tfidf", 0.07)


def test_precedence_cli_over_env_over_dotenv(tmp_path):
    dotenv = tmp_path / ".env"
    dotenv.write_text("LLM_MODEL=from-dotenv\nRETRIEVAL_TOP_K=5\nMAX_TICKET_CHARS=100\n")
    config = load_config({"model": "from-cli"}, env={"RETRIEVAL_TOP_K": "4"}, dotenv_path=dotenv)
    assert config.model == "from-cli"
    assert config.top_k == 4
    assert config.max_ticket_chars == 100


@pytest.mark.parametrize(
    "raw, expected",
    [("glm-5.2:cloud", "glm-5.2"), ("glm-5.3-flash:cloud", "glm-5.3-flash"), ("clef:27b-cloud", "clef:27b"), ("gpt-6.1-sol", "gpt-6.1-sol")],
)
def test_cloud_suffix_stripped(raw, expected):
    assert normalise_model_id(raw) == expected
    assert load_config({"model": raw}, env={}, dotenv_path=None).model == expected


def test_provider_default_model():
    assert load_config({"provider": "openai"}, env={}, dotenv_path=None).model == "gpt-4o-mini"
    assert load_config({}, env={"LLM_PROVIDER": "stub"}, dotenv_path=None).model == "stub"


@pytest.mark.parametrize(
    "cli, env",
    [
        ({"provider": "anthropic-direct"}, {}),
        ({}, {"RETRIEVAL_TOP_K": "three"}),
        ({}, {"RETRIEVAL_TOP_K": "0"}),
        ({}, {"RETRIEVAL_MIN_SCORE": "1.5"}),
        ({}, {"MAX_TICKET_CHARS": "0"}),
    ],
)
def test_invalid_config_raises(cli, env):
    with pytest.raises(ConfigError):
        load_config(cli, env=env, dotenv_path=None)


def test_no_keys_falls_back_to_stub_with_a_note():
    config = load_config({}, env={}, dotenv_path=None)
    assert (config.provider, config.retriever, config.effective_min_score) == ("stub", "tfidf", 0.07)
    assert len(config.notes) == 1 and "no LLM API key" in config.notes[0] and "stub" in config.notes[0]
    assert "notes" not in config.public_dict()


def test_provider_detection_order():
    both = {"OPENAI_API_KEY": "k", **KEYS}
    assert load_config({}, env=both, dotenv_path=None).provider == "openai"  # OPENAI_API_KEY beats Ollama variables
    assert load_config({}, env={"OPENAI_API_KEY": "k"}, dotenv_path=None).provider == "openai"
    assert load_config({}, env=KEYS, dotenv_path=None).provider == "ollama"
    assert load_config({}, env={"OLLAMA_API_KEY": "k"}, dotenv_path=None).provider == "ollama"
    assert load_config({}, env={}, dotenv_path=None).provider == "stub"
    assert load_config({"provider": "stub"}, env=both, dotenv_path=None).provider == "stub"  # explicit flag wins
    assert load_config({}, env={**both, "LLM_PROVIDER": "ollama"}, dotenv_path=None).provider == "ollama"  # so does LLM_PROVIDER


def test_openai_only_setup():
    config = load_config({}, env={"OPENAI_API_KEY": "k"}, dotenv_path=None)
    assert (config.provider, config.model, config.retriever) == ("openai", "gpt-4o-mini", "embedding")
    config.require_credentials(env={"OPENAI_API_KEY": "k"})
    config.require_embedding_credentials(env={"OPENAI_API_KEY": "k"})  # never asks for OLLAMA_*
    assert load_config({}, env={"OPENAI_API_KEY": "k", "OPENAI_MODEL": "gpt-4.1-mini"}, dotenv_path=None).model == "gpt-4.1-mini"
    assert load_config({}, env={"OPENAI_API_KEY": "k", "OPENAI_MODEL": "a", "LLM_MODEL": "b"}, dotenv_path=None).model == "b"
    assert load_config({"model": "c"}, env={"OPENAI_API_KEY": "k", "OPENAI_MODEL": "a"}, dotenv_path=None).model == "c"


def test_ollama_only_setup_uses_tfidf_instead_of_failing_on_embeddings():
    config = load_config({}, env=KEYS, dotenv_path=None)
    assert (config.provider, config.retriever) == ("ollama", "tfidf")
    assert any("TF-IDF" in n for n in config.notes)
    assert load_config({"retriever": "embedding"}, env=KEYS, dotenv_path=None).retriever == "embedding"  # explicit wins


@pytest.mark.parametrize("cli, env", [({"provider": "ollama"}, {}), ({}, {"LLM_PROVIDER": "ollama"})])
def test_explicit_provider_is_never_replaced(cli, env):
    config = load_config(cli, env=env, dotenv_path=None)
    assert config.provider == "ollama" and not any("stub" in n or "openai provider" in n for n in config.notes)


def test_credentials_check():
    config = load_config({"provider": "ollama"}, env={}, dotenv_path=None)
    with pytest.raises(ConfigError, match="OLLAMA_API_KEY, OLLAMA_BASE_URL"):
        config.require_credentials(env={})
    config.require_credentials(env={"OLLAMA_API_KEY": "k", "OLLAMA_BASE_URL": "u"})
    load_config({"provider": "stub"}, env={}, dotenv_path=None).require_credentials(env={})


def test_public_dict_hides_salt_and_stringifies_paths():
    config = load_config({"out_dir": "out"}, env={"PII_HASH_SALT": "s3cret"}, dotenv_path=None)
    assert config.pii_salt == "s3cret"
    public = config.public_dict()
    assert "pii_salt" not in public and "s3cret" not in str(public)
    assert public["out_dir"] == "out"
    assert config.artifacts_dir == Path("out/artifacts")


def test_cli_flags():
    config = load_config({"no_cache": True, "log_prompts": True, "tickets": "a.json", "kb": "b.json"}, env={}, dotenv_path=None)
    assert config.no_cache and config.log_prompts
    assert (config.tickets_path, config.kb_path) == (Path("a.json"), Path("b.json"))
