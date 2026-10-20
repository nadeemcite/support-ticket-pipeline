"""A3: pointing --tickets/--kb at other files with other IDs regenerates and validates everything for the new IDs."""

import json

import pytest

import run_pipeline
import validate
from tests.conftest import EVAL, FIXTURES, ROOT

pytestmark = pytest.mark.stage5


def ids(path, key):
    return [item["ticket_id"] for item in json.loads(path.read_text())[key]]


def test_eval_set_through_the_cli(tmp_path):
    args = ["--tickets", str(EVAL / "tickets.json"), "--kb", str(EVAL / "kb_articles.json"), "--out-dir", str(tmp_path)]
    assert run_pipeline.main(["--provider", "stub", *args]) == 0
    expected = [t["ticket_id"] for t in json.loads((EVAL / "tickets.json").read_text())["tickets"]]
    for filename, key in (("retrieval_results.json", "results"), ("ticket_classification.json", "classifications"), ("draft_responses.json", "drafts"), ("escalations.json", "escalations")):
        assert ids(tmp_path / filename, key) == expected, filename
    assert {"E-2001", "E-2020"} <= set(expected)  # IDs that exist only in the swapped-in file
    assert validate.main(args) == 0


def test_hand_written_tickets_with_new_ids(tmp_path):
    tickets = tmp_path / "my_tickets.json"
    tickets.write_text(json.dumps({"tickets": [
        {"ticket_id": "Z-1", "customer_tier": "vip", "language": "en", "subject": "Cannot log in", "message": "I can't log in after the password reset, it says invalid credentials."},
        {"ticket_id": "Z-2", "customer_tier": "standard", "language": "en", "subject": "Invoices", "message": "Where can I download my invoices as PDF?"},
        {"ticket_id": "Z-3", "customer_tier": "standard", "language": "es", "subject": "Reembolso", "message": "Me cobraron dos veces el mismo pedido y quiero mi dinero."},
    ]}))
    out = tmp_path / "out"
    args = ["--tickets", str(tickets), "--kb", str(ROOT / "kb_articles.json"), "--out-dir", str(out)]
    assert run_pipeline.main(["--provider", "stub", *args]) == 0
    assert ids(out / "escalations.json", "escalations") == ["Z-1", "Z-2", "Z-3"]
    assert validate.main(args) == 0


def test_a_different_kb_changes_the_evidence(tmp_path):
    out = tmp_path / "out"
    args = ["--tickets", str(ROOT / "tickets.json"), "--kb", str(FIXTURES / "empty_kb/kb_articles.json"), "--out-dir", str(out)]
    assert run_pipeline.main(["--provider", "stub", *args]) == 0
    results = json.loads((out / "retrieval_results.json").read_text())["results"]
    assert all(r["retrieved_articles"] == [] for r in results)
    drafts = json.loads((out / "draft_responses.json").read_text())["drafts"]
    assert all(d["citations"] == [] for d in drafts)
    assert validate.main(args) == 0
