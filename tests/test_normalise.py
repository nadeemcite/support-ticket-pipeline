"""Normalisation: every assertion in fixtures/edge_cases/expected.json, plus idempotency."""

import json
import unicodedata

import pytest

from pipeline.config import DEFAULT_PII_SALT
from pipeline.loader import load_inputs
from pipeline.normalise import clean_text, normalise_article, normalise_language, normalise_ticket, normalise_tickets
from tests.conftest import EVAL, FIXTURES, ROOT

pytestmark = pytest.mark.stage1

EXPECTED = json.loads((FIXTURES / "edge_cases/expected.json").read_text())


@pytest.fixture(scope="module")
def edge_tickets():
    loaded = load_inputs(FIXTURES / "edge_cases/tickets.json", ROOT / "kb_articles.json")
    return {t.ticket_id: t for t in normalise_tickets(loaded.tickets, 4000, DEFAULT_PII_SALT)}


@pytest.mark.parametrize("ticket_id", sorted(EXPECTED["normalised"]))
def test_edge_case_expectations(edge_tickets, ticket_id):
    ticket = edge_tickets[ticket_id]
    for key, expected in EXPECTED["normalised"][ticket_id].items():
        if key == "rule":
            continue
        if key == "notes_contain":
            assert any(expected in note for note in ticket.notes), ticket.notes
        elif key == "message_is_nfc":
            assert unicodedata.is_normalized("NFC", ticket.message)
        else:
            assert getattr(ticket, key) == expected, key


def test_nfc_composes_decomposed_characters(edge_tickets):
    assert "Café vs Café" in edge_tickets["X-007"].message


def test_accepted_ids_in_input_order(edge_tickets):
    assert list(edge_tickets) == EXPECTED["accepted_ticket_ids"]


def _round_trip(ticket):
    return normalise_ticket(ticket.model_dump(mode="json"), 4000, DEFAULT_PII_SALT)


@pytest.mark.parametrize(
    "source", [FIXTURES / "edge_cases/tickets.json", EVAL / "tickets.json", ROOT / "tickets.json"], ids=["edge", "eval", "root"]
)
def test_idempotent(source):
    loaded = load_inputs(source, ROOT / "kb_articles.json")
    for ticket in normalise_tickets(loaded.tickets, 4000, DEFAULT_PII_SALT):
        again = _round_trip(ticket)
        assert again.model_dump_json() == ticket.model_dump_json(), ticket.ticket_id


def test_deterministic_across_runs():
    loaded = load_inputs(EVAL / "tickets.json", ROOT / "kb_articles.json")
    first = [t.model_dump_json() for t in normalise_tickets(loaded.tickets, 4000, DEFAULT_PII_SALT)]
    second = [t.model_dump_json() for t in normalise_tickets(loaded.tickets, 4000, DEFAULT_PII_SALT)]
    assert first == second


def test_truncation_sets_flag_and_note():
    raw = {"ticket_id": "L-1", "customer_tier": "standard", "language": "en", "subject": "s", "message": "word " * 50}
    ticket = normalise_ticket(raw, 40, DEFAULT_PII_SALT)
    assert ticket.truncated and len(ticket.message) <= 40
    assert any("truncated" in note for note in ticket.notes)
    assert _round_trip_with_limit(ticket, 40).model_dump_json() == ticket.model_dump_json()


def _round_trip_with_limit(ticket, limit):
    return normalise_ticket(ticket.model_dump(mode="json"), limit, DEFAULT_PII_SALT)


def test_truncation_never_leaves_partial_placeholder_or_pii():
    message = "x" * 30 + " contact jane.doe@example.com today"
    ticket = normalise_ticket({"ticket_id": "L-2", "message": message}, 42, DEFAULT_PII_SALT)
    assert "jane" not in ticket.message and "[EMAIL_" not in ticket.message
    assert ticket.pii_summary.count == 1


def test_missing_fields_get_notes():
    ticket = normalise_ticket({"ticket_id": "M-1"}, 4000, DEFAULT_PII_SALT)
    assert ticket.customer_tier == "unknown" and ticket.language == "en"
    assert ticket.insufficient_content and ticket.created_at is None
    for expected in ("customer_tier missing", "subject missing", "message missing", "created_at missing"):
        assert any(expected in note for note in ticket.notes)


def test_extra_fields_are_pii_masked():
    raw = {"ticket_id": "E-1", "message": "hi", "contact": {"email": "a.b@example.com", "alt": ["c.d@example.org"]}}
    ticket = normalise_ticket(raw, 4000, DEFAULT_PII_SALT)
    assert ticket.extra == {"contact": {"email": "[EMAIL_1]", "alt": ["[EMAIL_2]"]}}


def test_content_hash_changes_with_content_only():
    base = {"ticket_id": "H-1", "customer_tier": "standard", "language": "en", "subject": "s", "message": "m"}
    first = normalise_ticket(base, 4000, DEFAULT_PII_SALT)
    same = normalise_ticket({**base, "created_at": "2026-01-01T00:00:00Z", "input_index": 5}, 4000, DEFAULT_PII_SALT)
    changed = normalise_ticket({**base, "message": "m2"}, 4000, DEFAULT_PII_SALT)
    assert first.content_hash == same.content_hash != changed.content_hash


@pytest.mark.parametrize(
    "raw, expected", [("en-GB", "en"), ("EN", "en"), ("pt_BR", "pt"), ("  es ", "es"), ("", None), (None, None)]
)
def test_normalise_language(raw, expected):
    assert normalise_language(raw) == expected


def test_clean_text():
    assert clean_text("  a\t\tb\n\nc\u0000d\u0007 ") == "a b cd"
    assert clean_text(None) == ""


def test_normalise_article():
    article = normalise_article(
        {"article_id": " KB-9 ", "title": " T ", "category": "Billing", "content": "a  b", "input_index": 0}
    )
    assert (article.article_id, article.title, article.category, article.content, article.updated_at) == (
        "KB-9", "T", "billing", "a b", None,
    )
