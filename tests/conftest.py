import json
from pathlib import Path

import pytest

from pipeline.config import Config

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
FIXTURES = DATA / "fixtures"
EVAL = DATA / "eval"


def load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture
def make_config(tmp_path):
    """Config pointing at given inputs, writing into an isolated tmp dir."""

    def _make(tickets: Path = ROOT / "tickets.json", kb: Path = ROOT / "kb_articles.json", **overrides) -> Config:
        settings = {"provider": "stub", "model": "stub", **overrides}
        return Config(tickets_path=tickets, kb_path=kb, out_dir=tmp_path, **settings)

    return _make
