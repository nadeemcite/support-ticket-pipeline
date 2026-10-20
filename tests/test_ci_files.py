"""CI workflow and Dockerfile stay consistent with the offline commands (not executed here: no Docker/Actions in the suite)."""

from pathlib import Path

import pytest
import yaml

pytestmark = pytest.mark.stage5
ROOT = Path(__file__).resolve().parent.parent


def test_workflow_runs_tests_stub_pipeline_and_validate():
    workflow = yaml.safe_load((ROOT / ".github" / "workflows" / "ci.yml").read_text())
    steps = [step.get("run", "") for job in workflow["jobs"].values() for step in job["steps"]]
    joined = "\n".join(steps)
    assert "requirements-dev.txt" in joined and "pytest" in joined
    assert "run_pipeline.py --provider stub" in joined and "validate.py" in joined
    assert "secrets." not in (ROOT / ".github" / "workflows" / "ci.yml").read_text()  # CI is offline, no keys


def test_dockerfile_is_offline_by_default_and_never_copies_secrets():
    dockerfile = (ROOT / "Dockerfile").read_text()
    assert "--provider stub" in dockerfile and "validate.py" in dockerfile and "requirements.txt" in dockerfile
    ignored = (ROOT / ".dockerignore").read_text().split()
    assert ".env" in ignored and ".git" in ignored
