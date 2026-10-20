"""Two runs produce byte-identical per-ticket artifacts (excluding timestamp, run_id, latency_ms)."""

import json

import pytest

from pipeline.runner import run
from tests.conftest import EVAL

pytestmark = pytest.mark.stage5

PER_TICKET = ("retrieval_results.json", "retrieval_debug.json", "ticket_classification.json", "draft_responses.json", "grounding_flags.json", "escalations.json", "artifacts/normalised_tickets.json", "artifacts/kb_index.json")
VOLATILE_LOG_FIELDS = {"timestamp", "latency_ms", "cached"}


def stable_log(path):
    return [{k: v for k, v in json.loads(line).items() if k not in VOLATILE_LOG_FIELDS} for line in path.read_text().splitlines()]


def stable_report(path):
    return {k: v for k, v in json.loads(path.read_text()).items() if k != "generated_at"}


def assert_same(a, b):
    for name in PER_TICKET:
        assert (a / name).read_bytes() == (b / name).read_bytes(), name
    assert stable_log(a / "llm_calls.jsonl") == stable_log(b / "llm_calls.jsonl")
    assert stable_report(a / "validation_report.json") == stable_report(b / "validation_report.json")


def test_rerun_in_the_same_directory_is_identical(make_config):
    config = make_config(tickets=EVAL / "tickets.json", kb=EVAL / "kb_articles.json")
    run(config)
    first = {n: (config.out_dir / n).read_bytes() for n in PER_TICKET}
    log = stable_log(config.out_dir / "llm_calls.jsonl")
    report = stable_report(config.out_dir / "validation_report.json")
    run(config)
    assert first == {n: (config.out_dir / n).read_bytes() for n in PER_TICKET}
    assert log == stable_log(config.out_dir / "llm_calls.jsonl") and report == stable_report(config.out_dir / "validation_report.json")


def test_two_cold_runs_in_different_directories_are_identical(make_config, tmp_path):
    from pipeline.config import Config

    configs = [Config(tickets_path=EVAL / "tickets.json", kb_path=EVAL / "kb_articles.json", out_dir=tmp_path / name, provider="stub", model="stub") for name in ("a", "b")]
    for config in configs:
        assert run(config).exit_code == 0
    assert_same(configs[0].out_dir, configs[1].out_dir)


def test_artifacts_are_fully_rewritten_not_appended(make_config):
    config = make_config()
    run(config)
    llm_lines = len((config.out_dir / "llm_calls.jsonl").read_text().splitlines())
    run(config)
    assert len((config.out_dir / "llm_calls.jsonl").read_text().splitlines()) == llm_lines == 6


def test_deleting_generated_artifacts_and_rerunning_recreates_them(make_config):
    """A2: outputs are generated, not static files."""
    config = make_config()
    run(config)
    names = ("retrieval_results.json", "ticket_classification.json", "draft_responses.json", "escalations.json", "validation_report.json", "llm_calls.jsonl")
    before = {n: (config.out_dir / n).read_bytes() for n in names if n.endswith(".json") and n != "validation_report.json"}
    for name in names:
        (config.out_dir / name).unlink()
    assert run(config).exit_code == 0
    assert all((config.out_dir / n).is_file() for n in names)
    assert before == {n: (config.out_dir / n).read_bytes() for n in before}
