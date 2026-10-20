"""CLI contract for Stage 5 (SPEC §2.1, §11): run_pipeline.py exit codes and validate.py, which reproduces the report status (A4)."""

import json
import subprocess
import sys

import pytest

import run_pipeline
import validate
from tests.conftest import EVAL, FIXTURES, ROOT

pytestmark = pytest.mark.stage5


def common(tmp_path, tickets=ROOT / "tickets.json", kb=ROOT / "kb_articles.json"):
    return ["--tickets", str(tickets), "--kb", str(kb), "--out-dir", str(tmp_path)]


def test_exit_zero_and_summary(tmp_path, capsys):
    assert run_pipeline.main(["--provider", "stub", *common(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "final stage: RESULTS_FINALISED" in out and "validation: pass (14 passed, 0 failed, 0 warnings)" in out and "cache:" in out


def test_validate_exit_one_when_a_check_fails(tmp_path, capsys):
    assert run_pipeline.main(["--provider", "stub", *common(tmp_path)]) == 0
    path = tmp_path / "draft_responses.json"
    payload = json.loads(path.read_text())
    payload["drafts"][0]["draft_response"] = "Please send us your password."
    path.write_text(json.dumps(payload))
    capsys.readouterr()
    assert validate.main(common(tmp_path)) == 1
    out = capsys.readouterr().out
    assert "validation: fail" in out and "V10" in out
    assert json.loads((tmp_path / "validation_report.json").read_text())["status"] == "fail"


def test_validate_reproduces_the_pipeline_status_a4(tmp_path):
    assert run_pipeline.main(["--provider", "stub", *common(tmp_path, EVAL / "tickets.json", EVAL / "kb_articles.json")]) == 0
    in_pipeline = json.loads((tmp_path / "validation_report.json").read_text())
    assert validate.main(common(tmp_path, EVAL / "tickets.json", EVAL / "kb_articles.json")) == 0
    standalone = json.loads((tmp_path / "validation_report.json").read_text())
    strip = lambda r: {k: v for k, v in r.items() if k != "generated_at"}  # noqa: E731
    assert strip(in_pipeline) == strip(standalone)


def test_validate_on_empty_directory_fails_with_v01(tmp_path, capsys):
    assert validate.main(common(tmp_path)) == 1
    assert "V01" in capsys.readouterr().out


def test_validate_exit_two_on_unusable_inputs(tmp_path, capsys):
    assert validate.main(["--tickets", str(FIXTURES / "malformed/invalid_json.txt"), "--kb", str(ROOT / "kb_articles.json"), "--out-dir", str(tmp_path)]) == 2
    assert "InputError" in capsys.readouterr().err


def test_validate_makes_no_llm_or_network_call(tmp_path, monkeypatch):
    assert run_pipeline.main(["--provider", "stub", *common(tmp_path)]) == 0
    import socket

    def no_socket(*args, **kwargs):
        raise AssertionError("validate.py must not use the network")

    monkeypatch.setattr(socket, "socket", no_socket)
    assert validate.main(common(tmp_path)) == 0


def test_missing_key_message_is_actionable(tmp_path, capsys):
    assert run_pipeline.main(["--provider", "ollama", *common(tmp_path)]) == 2
    err = capsys.readouterr().err
    assert "OLLAMA_API_KEY" in err and "--provider stub" in err


def test_until_stops_early_and_skips_validation(tmp_path, capsys):
    assert run_pipeline.main(["--provider", "stub", "--until", "ESCALATIONS_DECIDED", *common(tmp_path)]) == 0
    assert not (tmp_path / "validation_report.json").exists()
    assert "validation:" not in capsys.readouterr().out


def test_scripts_run_as_subprocesses(tmp_path):
    for script, extra in (("run_pipeline.py", ["--provider", "stub"]), ("validate.py", [])):
        result = subprocess.run([sys.executable, str(ROOT / script), *extra, *common(tmp_path)], cwd=ROOT, capture_output=True, text=True)
        assert result.returncode == 0, result.stderr
