"""Config precedence (CLI > env/.env > defaults), model ID normalisation and credential checks."""

from pathlib import Path

import pytest

from pipeline.config import ConfigError, load_config, normalise_model_id

pytestmark = pytest.mark.stage1


def test_defaults(tmp_path):
    config = load_config({}, env={}, dotenv_path=None)
    assert (config.provider, config.model, config.fast_model) == ("ollama", "glm-5.2", "glm-5.3-flash")
    assert (config.top_k, config.temperature, config.retriever) == (3, 0.0, "embedding")
    assert config.min_score is None and config.effective_min_score == 0.25
    stub = load_config({"provider": "stub"}, env={}, dotenv_path=None)
    assert (stub.retriever, stub.effective_min_score) == ("tfidf", 0.05)


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
    assert load_config({"provider": "openai"}, env={}, dotenv_path=None).model == "gpt-6.1-sol"
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


def test_credentials_check():
    config = load_config({}, env={}, dotenv_path=None)
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
