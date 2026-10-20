"""A1/A2: a copy of the repo without any generated file runs the pipeline and creates every required artifact."""

import shutil
import subprocess
import sys

import pytest

from tests.conftest import ROOT

pytestmark = pytest.mark.stage5

SOURCE = ("tickets.json", "kb_articles.json", "run_pipeline.py", "validate.py", "requirements.txt")
REQUIRED = ("retrieval_results.json", "ticket_classification.json", "draft_responses.json", "escalations.json", "llm_calls.jsonl", "validation_report.json")


@pytest.fixture
def checkout(tmp_path):
    for name in SOURCE:
        shutil.copy(ROOT / name, tmp_path / name)
    shutil.copytree(ROOT / "pipeline", tmp_path / "pipeline", ignore=shutil.ignore_patterns("__pycache__"))
    return tmp_path


def test_fresh_copy_runs_offline_and_creates_every_artifact(checkout):
    assert not any((checkout / name).exists() for name in REQUIRED)
    env = {"PATH": "/usr/bin:/bin", "HOME": str(checkout)}
    result = subprocess.run([sys.executable, "run_pipeline.py", "--provider", "stub"], cwd=checkout, capture_output=True, text=True, env=env)
    assert result.returncode == 0, result.stderr
    assert all((checkout / name).is_file() for name in REQUIRED)
    assert (checkout / "artifacts" / "run_manifest.json").is_file()
    again = subprocess.run([sys.executable, "validate.py"], cwd=checkout, capture_output=True, text=True, env=env)
    assert again.returncode == 0, again.stdout + again.stderr
