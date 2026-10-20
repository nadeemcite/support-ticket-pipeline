"""G1-G3 against every case in data/fixtures/grounding_cases.json (T6), plus the guard's boundaries."""

import pytest

from pipeline.grounding import check_grounding
from pipeline.loader import load_inputs
from pipeline.normalise import normalise_article
from tests.conftest import FIXTURES, ROOT, load

pytestmark = pytest.mark.stage4

CASES = load(FIXTURES / "grounding_cases.json")["cases"]
KB = {a.article_id: a for a in map(normalise_article, load_inputs(ROOT / "tickets.json", ROOT / "kb_articles.json").articles)}


def _flags(sentence, citations, allowed=False):
    return check_grounding("T-1", sentence, [KB[c] for c in citations], allowed)


@pytest.mark.parametrize("case", CASES, ids=[c["id"] for c in CASES])
def test_fixture_case(case):
    flags = _flags(case["sentence"], case["citations"])
    assert bool(flags) is case["flag"], flags
    if case["flag"]:
        assert case["check"] in {f.check for f in flags}


def test_flag_carries_evidence_for_review():
    (flag,) = _flags("The pending charge will disappear within 24 hours.", ["KB-001"])
    assert flag.check == "G1" and flag.unsupported_tokens == ["24 hours"] and flag.cited_articles_checked == ["KB-001"]


def test_negated_kb_sentence_never_supports_a_commitment():  # G-05 / OD-4
    assert [f.check for f in _flags("We will refund the extra charge to your card.", ["KB-001"])] == ["G3"]


def test_only_cited_text_counts():  # G-11
    assert _flags("Invoices can be downloaded as PDF.", ["KB-003"]) == []
    assert _flags("Invoices can be downloaded as PDF.", ["KB-001"])


def test_escalation_statement_allowed_only_when_rules_allow_it():
    sentence = "We will escalate this to our account support team."
    assert _flags(sentence, ["KB-002"], allowed=True) == []
    assert _flags(sentence, ["KB-004"], allowed=False)  # KB-004 prescribes no escalation


def test_escalation_offer_is_supported_when_a_cited_article_prescribes_escalation():
    assert _flags("If invoices are missing, we will escalate your case to our billing support team.", ["KB-003"]) == []


def test_human_review_statements_are_process_not_product_claims():
    assert _flags("Our billing team will review whether a refund applies.", ["KB-004"]) == []


def test_single_number_matches_an_end_of_a_cited_range():
    assert _flags("If it persists after 5 business days, reply here.", ["KB-001"]) == []
    assert _flags("If it persists after 7 business days, reply here.", ["KB-001"])


def test_number_words_and_ranges_are_normalised():
    assert _flags("Pending holds clear in three to five business days.", ["KB-001"]) == []
    assert _flags("Pending holds clear in two business days.", ["KB-001"])


def test_courtesy_follow_up_is_not_a_claim():
    assert _flags("We will follow up with you shortly.", ["KB-001"]) == []


def test_kb_ids_and_bare_numbers_are_ignored():
    assert _flags("See KB-001 for order 12345.", ["KB-001"]) == []


def test_no_citations_flags_concrete_claims_only():
    assert _flags("Thank you for contacting us.", []) == []
    assert _flags("Refunds are processed within 2 days.", [])


def test_translated_menu_labels_are_not_flagged_outside_english():
    sentence = "Vous trouverez vos factures sous Facturation > Documents."
    assert check_grounding("T-1", sentence, [KB["KB-003"]], language="fr") == []
    assert [f.check for f in check_grounding("T-1", sentence, [KB["KB-003"]], language="en")] == ["G2"]
    assert check_grounding("T-1", "Vous trouverez vos factures sous Facturation > Archives.", [KB["KB-003"]], language="fr")


@pytest.mark.parametrize("sentence", ["I understand how worrying an unexpected charge can be.", "Once we have the details, we'll be glad to assist further."])
def test_empathy_and_courtesy_are_not_claims(sentence):
    assert _flags(sentence, ["KB-001"]) == []
