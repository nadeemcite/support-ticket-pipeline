"""run_pipeline.py exit codes and output for Stage 1."""

import pytest

import run_pipeline
from tests.conftest import FIXTURES, ROOT

pytestmark = pytest.mark.stage1


def test_cli_success(tmp_path, capsys):
    code = run_pipeline.main(["--provider", "stub", "--out-dir", str(tmp_path), "--tickets", str(ROOT / "tickets.json"), "--kb", str(ROOT / "kb_articles.json")])
    assert code == 0
    assert "EVIDENCE_RETRIEVED" in capsys.readouterr().out
    assert (tmp_path / "artifacts/normalised_tickets.json").is_file()
    assert (tmp_path / "retrieval_results.json").is_file()


def test_cli_fatal_on_bad_input(tmp_path, capsys):
    code = run_pipeline.main(["--provider", "stub", "--out-dir", str(tmp_path), "--tickets", str(FIXTURES / "malformed/invalid_json.txt")])
    assert code == 2
    assert "InputError" in capsys.readouterr().err


def test_cli_fatal_on_bad_config(tmp_path, capsys, monkeypatch):
    monkeypatch.setenv("RETRIEVAL_TOP_K", "zero")
    assert run_pipeline.main(["--out-dir", str(tmp_path)]) == 2
    assert "RETRIEVAL_TOP_K" in capsys.readouterr().err


def test_cli_until_unimplemented_stage(tmp_path, capsys):
    code = run_pipeline.main(["--provider", "stub", "--out-dir", str(tmp_path), "--until", "TICKETS_CLASSIFIED"])
    assert code == 2
    assert "not implemented" in capsys.readouterr().err
