"""Each V-check fails on exactly the artifact mutation it exists for (SPEC §8), and passes on the clean run."""

import json
import shutil

import pytest

from pipeline.runner import run
from pipeline.validation import validate
from tests.conftest import EVAL

pytestmark = pytest.mark.stage5


@pytest.fixture(scope="module")
def clean_run(tmp_path_factory):
    from pipeline.config import Config

    out = tmp_path_factory.mktemp("clean")
    config = Config(tickets_path=EVAL / "tickets.json", kb_path=EVAL / "kb_articles.json", out_dir=out, provider="stub", model="stub")
    outcome = run(config)
    assert outcome.exit_code == 0, outcome.error
    return config


@pytest.fixture
def work(clean_run, tmp_path):
    """A private copy of the clean run's artifacts that a test may corrupt."""
    return tmp_path, clean_run


_counter = iter(range(10_000))


def check(work, mutate):
    """Apply ``mutate`` to a fresh copy of the clean run, so mutations never accumulate within a test."""
    base, config = work
    out = base / f"run{next(_counter)}"
    shutil.copytree(config.out_dir, out, ignore=shutil.ignore_patterns(".cache"))
    mutate(out)
    report = validate(out, config.tickets_path, config.kb_path, config.top_k, config.effective_min_score, write=False)
    return {c["id"]: c for c in report["checks"]}, report


def edit(out, filename, key, fn):
    path = out / filename
    payload = json.loads(path.read_text())
    fn(payload[key])
    path.write_text(json.dumps(payload))


def failing(checks):
    return {i for i, c in checks.items() if c["status"] == "fail"}


def test_clean_run_passes_all_fourteen(clean_run):
    report = validate(clean_run.out_dir, clean_run.tickets_path, clean_run.kb_path, 3, clean_run.effective_min_score, write=False)
    assert report["status"] == "pass" and report["summary"] == {"checks": 14, "passed": 14, "failed": 0, "warnings": 0, "tickets": 23}
    assert [c["id"] for c in report["checks"]] == [f"V{n:02d}" for n in range(1, 15)]


def test_v01_missing_artifact_fails_and_dependents_say_so(work):
    checks, report = check(work, lambda out: (out / "draft_responses.json").unlink())
    assert "V01" in failing(checks) and report["status"] == "fail"
    assert {"V04", "V07", "V10", "V11", "V13", "V14"} <= failing(checks)
    assert any("missing" in d["message"] for d in checks["V07"]["details"])


def test_v02_unparsable_json_and_log_line(work):
    checks, _ = check(work, lambda out: (out / "escalations.json").write_text("{not json"))
    assert "V02" in failing(checks)
    checks, _ = check(work, lambda out: (out / "llm_calls.jsonl").write_text("{}\n"))
    assert "V02" in failing(checks)


def test_v03_schema_violation(work):
    checks, _ = check(work, lambda out: edit(out, "escalations.json", "escalations", lambda items: items[0].update(surprise=1)))
    assert "V03" in failing(checks)


def test_v04_missing_extra_and_duplicate_tickets(work):
    checks, _ = check(work, lambda out: edit(out, "ticket_classification.json", "classifications", lambda items: items.pop()))
    assert "V04" in failing(checks) and "ticket missing" in checks["V04"]["details"][0]["message"]
    checks, _ = check(work, lambda out: edit(out, "draft_responses.json", "drafts", lambda items: items.append(dict(items[0]))))
    assert "duplicate" in checks["V04"]["details"][0]["message"]
    checks, _ = check(work, lambda out: edit(out, "retrieval_results.json", "results", lambda items: items.append({"ticket_id": "T-9", "retrieved_articles": []})))
    assert any("unexpected" in d["message"] for d in checks["V04"]["details"])


def test_v05_label_outside_taxonomy(work):
    checks, _ = check(work, lambda out: edit(out, "ticket_classification.json", "classifications", lambda items: items[0].update(issue_type="spam")))
    assert {"V03", "V05"} <= failing(checks)


def test_v06_retrieval_contract(work):
    def too_many(items):
        hit = {"article_id": "KB-001", "score": 0.9, "title": "t"}
        items[0]["retrieved_articles"] = [hit] * 4

    checks, _ = check(work, lambda out: edit(out, "retrieval_results.json", "results", too_many))
    assert "V06" in failing(checks)
    checks, _ = check(work, lambda out: edit(out, "retrieval_results.json", "results", lambda items: items[0].update(retrieved_articles=[{"article_id": "KB-404", "score": 0.5, "title": "t"}])))
    assert "V06" in failing(checks)
    checks, _ = check(work, lambda out: edit(out, "retrieval_results.json", "results", lambda items: items[0].update(retrieved_articles=[{"article_id": "KB-001", "score": 0.2, "title": "a"}, {"article_id": "KB-002", "score": 0.4, "title": "b"}])))
    assert "V06" in failing(checks)


def test_v07_foreign_citation(work):
    checks, _ = check(work, lambda out: edit(out, "draft_responses.json", "drafts", lambda items: items[0].update(citations=["KB-011"])))
    assert failing(checks) >= {"V07"}


def test_v08_queue_escalate_mismatch(work):
    checks, _ = check(work, lambda out: edit(out, "escalations.json", "escalations", lambda items: items[0].update(escalate=True, target_queue="none")))
    assert {"V08", "V03"} <= failing(checks)
    checks, _ = check(work, lambda out: edit(out, "escalations.json", "escalations", lambda items: items[0].update(target_queue="vip_desk")))
    assert "V08" in failing(checks)


def test_v09_wrong_language_fails(work):
    spanish = next(t for t in json.loads((EVAL / "tickets.json").read_text())["tickets"] if t["language"] == "es")["ticket_id"]

    def english(items):
        next(i for i in items if i["ticket_id"] == spanish)["draft_response"] = "Thank you for contacting us. We have received your message and escalated it to our specialist team, who will help you with this."

    checks, report = check(work, lambda out: edit(out, "draft_responses.json", "drafts", english))
    assert checks["V09"]["status"] == "fail" and report["status"] == "fail"
    assert any(spanish == d["ticket_id"] for d in checks["V09"]["details"])


def test_v10_credential_request_and_refund_promise(work):
    checks, _ = check(work, lambda out: edit(out, "draft_responses.json", "drafts", lambda items: items[0].update(draft_response="Please send us your password.")))
    assert "V10" in failing(checks)

    def promise(out):
        edit(out, "ticket_classification.json", "classifications", lambda items: items[0].update(requires_refund_caution=True))
        edit(out, "draft_responses.json", "drafts", lambda items: items[0].update(draft_response="We will refund you today."))

    checks, _ = check(work, promise)
    assert "V10" in failing(checks)
    checks, _ = check(work, lambda out: (edit(out, "ticket_classification.json", "classifications", lambda i: i[0].update(requires_refund_caution=True)),
                                          edit(out, "escalations.json", "escalations", lambda i: i[0].update(reason="Your refund has been issued."))))
    assert "V10" in failing(checks)


def test_v11_escalation_consistency(work):
    def drop_mention(out):
        edit(out, "ticket_classification.json", "classifications", lambda items: items[0].update(resolution_action="needs_human_escalation"))
        edit(out, "draft_responses.json", "drafts", lambda items: items[0].update(draft_response="Here is some general help."))

    checks, _ = check(work, drop_mention)
    assert "V11" in failing(checks)

    def not_escalated(out):
        edit(out, "ticket_classification.json", "classifications", lambda items: items[0].update(resolution_action="needs_human_escalation"))
        edit(out, "draft_responses.json", "drafts", lambda items: items[0].update(draft_response="We have escalated this to our specialist team."))
        edit(out, "escalations.json", "escalations", lambda items: items[0].update(escalate=False, target_queue="none"))

    checks, _ = check(work, not_escalated)
    assert any("escalate is false" in d["message"] for d in checks["V11"]["details"])


def test_v12_flags_and_missing_log_coverage_warn(work):
    flag = {"ticket_id": "T-1001", "check": "G1", "claim_type": "number_or_duration", "sentence": "s", "unsupported_tokens": ["24 hours"], "cited_articles_checked": [], "overlap": 0.1}
    checks, report = check(work, lambda out: (out / "grounding_flags.json").write_text(json.dumps({"flags": [flag], "summary": {}})))
    assert checks["V12"]["status"] == "warn" and report["status"] == "pass"
    checks, report = check(work, lambda out: (out / "llm_calls.jsonl").write_text(""))
    assert checks["V12"]["status"] == "warn" and any("no successful" in d["message"] for d in checks["V12"]["details"])


def test_v13_raw_pii_in_draft_reason_and_log(work):
    checks, _ = check(work, lambda out: edit(out, "draft_responses.json", "drafts", lambda items: items[0].update(draft_response="Write to jane.doe@example.com for help.")))
    assert "V13" in failing(checks)
    checks, _ = check(work, lambda out: edit(out, "escalations.json", "escalations", lambda items: items[0].update(reason="Card 4111 1111 1111 1111 was used.")))
    assert "V13" in failing(checks)

    def leak_log(out):
        lines = (out / "llm_calls.jsonl").read_text().splitlines()
        record = json.loads(lines[0])
        record["error"] = "failed for jane.doe@example.com"
        (out / "llm_calls.jsonl").write_text("\n".join([json.dumps(record), *lines[1:]]) + "\n")

    checks, _ = check(work, leak_log)
    assert "V13" in failing(checks)


def test_v14_placeholder(work):
    checks, _ = check(work, lambda out: edit(out, "draft_responses.json", "drafts", lambda items: items[0].update(draft_response="We emailed [EMAIL_1].")))
    assert "V14" in failing(checks)
    checks, _ = check(work, lambda out: edit(out, "escalations.json", "escalations", lambda items: items[0].update(reason="See [CARD_NUMBER_2].")))
    assert "V14" in failing(checks)


def test_each_mutation_leaves_unrelated_checks_green(work):
    checks, _ = check(work, lambda out: edit(out, "draft_responses.json", "drafts", lambda items: items[0].update(draft_response="We emailed [EMAIL_1].")))
    assert failing(checks) == {"V14"}


def test_report_is_written_and_marks_status(clean_run, tmp_path):
    report = validate(clean_run.out_dir, clean_run.tickets_path, clean_run.kb_path, 3, clean_run.effective_min_score, write=True)
    on_disk = json.loads((clean_run.out_dir / "validation_report.json").read_text())
    assert on_disk["status"] == report["status"] == "pass" and set(on_disk) == {"generated_at", "status", "summary", "checks"}


S1_PHRASES = [
    "What is your password?",
    "Please let us know your password.",
    "Please share your login credentials.",
    "Could you share your login details with us?",
]
S2_PHRASES = [
    "Don't worry, you will get your money back.",
    "We will send you your money back.",
    "We have issued the refund.",
    "We've processed your refund today.",
    "The refund was reversed this morning.",
    "Your refund has been issued.",
    "Your payment will be reversed within 5 days.",
    "We will reverse the charge.",
    "We will credit the amount back to your card.",
    "We have reimbursed you.",
    "The money will be returned to your card.",
]


@pytest.mark.parametrize("phrase", S1_PHRASES)
def test_v10_catches_credential_phrasing(work, phrase):
    checks, report = check(work, lambda out: edit(out, "draft_responses.json", "drafts", lambda items: items[0].update(draft_response=phrase)))
    assert "V10" in failing(checks) and report["status"] == "fail"


@pytest.mark.parametrize("phrase", S2_PHRASES)
def test_v10_catches_refund_promise_phrasing(work, phrase):
    def promise(out):
        edit(out, "ticket_classification.json", "classifications", lambda items: items[0].update(requires_refund_caution=True))
        edit(out, "draft_responses.json", "drafts", lambda items: items[0].update(draft_response=phrase))

    checks, report = check(work, promise)
    assert "V10" in failing(checks) and report["status"] == "fail"


@pytest.mark.parametrize("phrase", ["We will never ask for your password.", "Never share your login credentials with anyone."])
def test_v10_allows_credential_advice(work, phrase):
    checks, _ = check(work, lambda out: edit(out, "draft_responses.json", "drafts", lambda items: items[0].update(draft_response=phrase)))
    assert "V10" not in failing(checks)


QUIET = "Thank you for contacting us. We are looking into your request and will be in touch."
ESCALATED = "Thank you for contacting us. We have escalated your case to our specialist team."


def _decide(rule):
    """Make ticket 0 escalate by exactly ``rule`` (E1, E2, E3 or E6) and give it ``text`` as its draft."""

    def classification(items):
        item = items[0]
        item.update(resolution_action="needs_human_escalation" if rule == "E1" else "answer_from_kb", urgency="critical" if rule == "E2" else "medium")
        item["meta"]["fallback"] = rule == "E3"

    def mutate(out, text, escalate=True):
        edit(out, "ticket_classification.json", "classifications", classification)
        edit(out, "escalations.json", "escalations", lambda i: i[0].update(escalate=escalate, target_queue="general_support" if escalate else "none", meta={**i[0]["meta"], "rules_fired": [rule] if escalate else ["E5"]}))
        edit(out, "draft_responses.json", "drafts", lambda i: i[0].update(draft_response=text))

    return mutate


@pytest.mark.parametrize("rule", ["E1", "E2", "E3"])
def test_v11_escalated_by_any_rule_needs_escalation_wording(work, rule):
    checks, _ = check(work, lambda out: _decide(rule)(out, QUIET))
    assert "V11" in failing(checks) and any(f"escalated ({rule})" in d["message"] for d in checks["V11"]["details"])
    checks, _ = check(work, lambda out: _decide(rule)(out, ESCALATED))
    assert "V11" not in failing(checks)


def test_v11_not_escalated_must_not_claim_escalation(work):
    checks, _ = check(work, lambda out: _decide("E5")(out, ESCALATED, escalate=False))
    assert "V11" in failing(checks) and any("not escalated but the draft says" in d["message"] for d in checks["V11"]["details"])
    checks, _ = check(work, lambda out: _decide("E5")(out, QUIET, escalate=False))
    assert "V11" not in failing(checks)


@pytest.mark.parametrize("phrase", ["The billing team will review whether a refund applies.", "A pending authorization will be reversed automatically."])
def test_v10_allows_safe_refund_wording(work, phrase):
    def edit_both(out):
        edit(out, "ticket_classification.json", "classifications", lambda items: items[0].update(requires_refund_caution=True))
        edit(out, "draft_responses.json", "drafts", lambda items: items[0].update(draft_response=phrase))

    checks, _ = check(work, edit_both)
    assert "V10" not in failing(checks)
