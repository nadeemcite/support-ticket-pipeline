"""Offline tests for the Stage 4 eval tooling: scoring rules, report gates, judge schema, calibration, language heuristic."""

import json

import pytest
from pydantic import ValidationError

from evals import calibration
from evals.drafting_eval import asserted_hits
from evals.judge import JudgeScore
from evals.report_drafting import gates
from pipeline.language import detect_language, matches_language

pytestmark = pytest.mark.stage4


@pytest.mark.parametrize(
    "text, expected",
    [
        ("Please never share your password with anyone.", []),  # advice, not an echo of the secret
        ("We cannot use your password to log in for you.", []),
        ("I can't confirm whether we offer sponsorships.", []),
        ("Yes, we offer sponsorships for clubs.", ["we offer sponsorships"]),
        ("Not sure. We offer sponsorships.", ["we offer sponsorships"]),  # negation belongs to another sentence
    ],
)
def test_must_not_include_is_negation_aware(text, expected):
    phrase = {"never share your password with anyone": "share your password", "log in for you": "log in for you", "we offer sponsorships": "we offer sponsorships"}
    phrases = [p for key, p in phrase.items() if p.lower() in text.lower()]
    assert asserted_hits(text, phrases) == expected


def test_judge_schema_is_strict():
    ok = {"faithfulness": 5, "helpfulness": 4, "tone": 5, "policy": 5, "language": 5, "rationale": "fine"}
    assert JudgeScore.model_validate(ok).faithfulness == 5
    for bad in ({**ok, "tone": 6}, {**ok, "tone": 0}, {**ok, "extra": 1}, {k: v for k, v in ok.items() if k != "policy"}):
        with pytest.raises(ValidationError):
            JudgeScore.model_validate(bad)


def record(**checks):
    base = {"citation_valid": True, "s1_credential_request": False, "s2_refund_promise": False, "pii_leak": False, "placeholder_leak": False,
            "escalation_mentioned": None, "must_not_include_violations": [], "must_include_hit": True, "language_match": True,
            "fallback": False, "first_attempt_ok": True, "grounding_flags": []}
    score = {"faithfulness": 5, "helpfulness": 5, "tone": 5, "policy": 5, "language": 5, "rationale": "r"}
    return {"checks": {**base, **checks}, "judge": {"scores": score}}


def by_name(rows):
    return {name: (ok, hard) for name, _, _, ok, hard in rows}


def test_gates_pass_on_clean_drafts_and_fail_on_each_hard_violation():
    clean = [record() for _ in range(10)]
    assert all(ok for ok, _ in by_name(gates(clean)).values())
    for field, value in [("citation_valid", False), ("s1_credential_request", True), ("s2_refund_promise", True), ("pii_leak", True),
                         ("placeholder_leak", True), ("escalation_mentioned", False), ("must_not_include_violations", ["x"]), ("language_match", False)]:
        rows = by_name(gates([*clean[:-1], record(**{field: value})]))
        assert any(not ok and hard for ok, hard in rows.values()), field


def test_soft_gates_and_judge_downgrade():
    flagged = [record(grounding_flags=[{"x": 1}, {"x": 2}]) for _ in range(4)]
    assert not by_name(gates(flagged))["Grounding flags per draft"][0]
    fallbacks = [record(fallback=True)] + [record() for _ in range(3)]
    assert not by_name(gates(fallbacks))["Fallback rate"][0]
    weak = [{**record(), "judge": {"scores": {"faithfulness": 3, "helpfulness": 5, "tone": 5, "policy": 5, "language": 5, "rationale": "r"}}}]
    assert by_name(gates(weak))["Judge faithfulness, mean (1–5)"] == (False, True)
    advisory = by_name(gates(weak, downgraded=True))["Judge faithfulness, mean (1–5) — advisory"]
    assert advisory == (False, False)  # downgraded by calibration: reported, no longer a hard gate


def test_missing_judge_scores_fail_hard():
    rows = by_name(gates([{**record(), "judge": {"scores": None}}]))
    assert rows["Judge scores complete"] == (False, True)


def test_calibration_selection_is_deterministic_blind_and_stratified():
    tags = {f"T{i}": t for i, t in enumerate([["non_english"], ["pii"], ["safety"], ["refund_caution"], ["escalation"], ["prompt_injection"], ["how_to"], ["billing"], ["other"], ["other"]])}
    data = {m: {mode: [{"ticket_id": t} for t in tags] for mode in ("oracle", "e2e")} for m in ("a", "b")}
    first = calibration.select(data, tags)
    assert first == calibration.select(data, tags) and len(first) == 8 and len({t for _, _, t in first}) == 8
    covered = {tag for _, _, t in first for tag in tags[t]}
    assert {"non_english", "pii", "safety", "refund_caution"} <= covered


def test_calibration_sheet_parsing_and_agreement():
    sheet = "### C1\n```\nfaithfulness: 5\nhelpfulness: 4\ntone: 5\npolicy: 5\nlanguage: _\n```\n### C2\nfaithfulness: 2\n"
    parsed = calibration.parse_sheet(sheet)
    assert parsed == {"C1": {"faithfulness": 5, "helpfulness": 4, "tone": 5, "policy": 5}, "C2": {"faithfulness": 2}}
    judge = {k: 5 for k in ("faithfulness", "helpfulness", "tone", "policy", "language")}
    result = calibration.agreement(parsed, {"C1": {"judge": judge}, "C2": {"judge": judge}})
    assert result["pairs"] == 5 and result["within_1"] == 4 and not result["complete"]  # C2 faithfulness 2 vs 5 is outside ±1


@pytest.mark.parametrize(
    "text, language",
    [
        ("Thank you for contacting us. We have received your message.", "en"),
        ("Gracias por contactarnos. Hemos recibido su mensaje para el equipo.", "es"),
        ("Merci de nous avoir contactés. Nous avons bien reçu votre message.", "fr"),
        ("Vielen Dank für Ihre Nachricht. Wir haben sie erhalten und geprüft.", "de"),
        ("Obrigado por entrar em contato. Recebemos a sua mensagem para o suporte.", "pt"),
    ],
)
def test_language_detection(text, language):
    assert detect_language(text) == language and matches_language(text, language) is True
    assert matches_language(text, "de" if language != "de" else "en") is False


def test_language_heuristic_abstains_when_unsure():
    assert detect_language("OK") is None and matches_language("Hello there friend, ok", "ja") is None
    assert matches_language("xyz qrs tuv wxy", "en") is None
