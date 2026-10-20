"""E6: a ticket in a language the pipeline cannot check is escalated, not answered in English by a model (V09 fails otherwise)."""

import json

import pytest

from pipeline.config import Config
from pipeline.escalate import decide
from pipeline.runner import run
from pipeline.taxonomy import ResolutionAction
from pipeline.validation import validate
from tests.conftest import EVAL
from tests.test_escalation_rules import BILLING_KB, cls

pytestmark = pytest.mark.stage4

JA = {
    "ticket_id": "X-JA-1", "customer_tier": "standard", "language": "ja", "subject": "ログインできません",
    "message": "パスワードを変更した後、ログインできなくなりました。助けてください。", "created_at": "2026-06-01T09:00:00Z",
}


def test_e6_escalates_an_otherwise_quiet_ticket():
    quiet = cls(action=ResolutionAction.ANSWER_FROM_KB)
    assert not decide(quiet, [BILLING_KB]).escalate
    assert not decide(quiet, [BILLING_KB], "es-MX").escalate
    result = decide(quiet, [BILLING_KB], "ja")
    assert result.escalate and "E6" in result.meta.rules_fired and "'ja'" in result.reason
    assert result.target_queue.value != "none"


@pytest.fixture(scope="module")
def japanese_run(tmp_path_factory):
    tickets = json.loads((EVAL / "tickets.json").read_text())["tickets"][:3] + [JA]
    path = tmp_path_factory.mktemp("ja") / "tickets.json"
    path.write_text(json.dumps({"tickets": tickets}, ensure_ascii=False))
    config = Config(tickets_path=path, kb_path=EVAL / "kb_articles.json", out_dir=path.parent / "out", provider="stub", model="stub")
    outcome = run(config)
    return config, outcome


def test_unsupported_language_ticket_is_escalated_with_a_holding_note(japanese_run):
    config, outcome = japanese_run
    assert outcome.exit_code == 0, outcome.error
    out = config.out_dir
    esc = next(e for e in json.loads((out / "escalations.json").read_text())["escalations"] if e["ticket_id"] == "X-JA-1")
    draft = next(d for d in json.loads((out / "draft_responses.json").read_text())["drafts"] if d["ticket_id"] == "X-JA-1")
    assert esc["escalate"] and "E6" in esc["meta"]["rules_fired"]
    assert draft["meta"]["fallback"] and draft["meta"]["language"] == "en" and draft["meta"]["attempts"] == 0
    assert "escalated" in draft["draft_response"]
    calls = [json.loads(line) for line in (out / "llm_calls.jsonl").read_text().splitlines()]
    assert not [c for c in calls if c["ticket_id"] == "X-JA-1" and c["stage"] == "drafting"]


def test_validator_requires_e6_for_unsupported_language(japanese_run, tmp_path):
    config, _ = japanese_run
    report = validate(config.out_dir, config.tickets_path, config.kb_path, config.top_k, config.effective_min_score, write=False)
    assert report["status"] == "pass"
    broken = tmp_path / "broken"
    broken.mkdir()
    for f in config.out_dir.glob("*.json*"):
        (broken / f.name).write_bytes(f.read_bytes())
    path = broken / "escalations.json"
    payload = json.loads(path.read_text())
    for e in payload["escalations"]:
        if e["ticket_id"] == "X-JA-1":
            e["meta"]["rules_fired"] = [r for r in e["meta"]["rules_fired"] if r != "E6"]
    path.write_text(json.dumps(payload))
    report = validate(broken, config.tickets_path, config.kb_path, config.top_k, config.effective_min_score, write=False)
    v09 = next(c for c in report["checks"] if c["id"] == "V09")
    assert v09["status"] == "fail" and any("not escalated by E6" in d["message"] for d in v09["details"])
