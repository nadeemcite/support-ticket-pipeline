"""PII detection and masking: every case in fixtures/pii_cases.json (P-DET, P-MASK)."""

import json

import pytest

from pipeline import pii
from pipeline.taxonomy import PIIType
from tests.conftest import FIXTURES

pytestmark = pytest.mark.stage1

CASES = json.loads((FIXTURES / "pii_cases.json").read_text())["cases"]
FALSE_POSITIVE_GUARDS = {"P05", "P09", "P10", "P12", "P14"}


@pytest.mark.parametrize("case", CASES, ids=[c["id"] for c in CASES])
def test_detected_types(case):
    assert [d.type.value for d in pii.detect(case["text"])] == case["expected"]


@pytest.mark.parametrize("case", CASES, ids=[c["id"] for c in CASES])
def test_exact_masked_output(case):
    assert pii.mask(case["text"]).text == case["masked"]


@pytest.mark.parametrize("case", CASES, ids=[c["id"] for c in CASES])
def test_unmask_restores_original(case):
    result = pii.mask(case["text"])
    assert pii.unmask(result.text, result.mapping) == case["text"]


@pytest.mark.parametrize("case", CASES, ids=[c["id"] for c in CASES])
def test_mask_is_idempotent(case):
    once = pii.mask(case["text"]).text
    assert pii.mask(once).text == once


def test_false_positive_guards_present():
    guards = {c["id"] for c in CASES if not c["expected"]}
    assert FALSE_POSITIVE_GUARDS <= guards


def test_repeated_value_reuses_placeholder_and_shared_mapping_numbers_consistently():
    mapping: dict[str, str] = {}
    subject = pii.mask("Reply to a@example.com", mapping).text
    message = pii.mask("Again a@example.com, or b@example.com", mapping).text
    assert subject == "Reply to [EMAIL_1]"
    assert message == "Again [EMAIL_1], or [EMAIL_2]"
    assert mapping == {"[EMAIL_1]": "a@example.com", "[EMAIL_2]": "b@example.com"}


def test_masked_text_contains_no_pii():
    for case in CASES:
        assert not pii.contains_pii(pii.mask(case["text"]).text), case["id"]


@pytest.mark.parametrize(
    "text, expected",
    [
        ("Error code is 503", []),
        ("The order code is 123456", []),
        ("Your verification code is 991204", ["credential"]),
        ("PIN: 4821", ["credential"]),
        ("Mon mot de passe est Soleil!2026", ["credential"]),
        ("Mein Passwort lautet Geheim99", ["credential"]),
        ("A senha é Azul@77", ["credential"]),
        ("national number 020 7946 0018", ["phone"]),
        ("Short number 12345", []),
        ("Card 5555 5555 5555 4444 and 4111 1111 1111 1111", ["card_number", "card_number"]),
        ("IBAN DE89 3704 0044 0532 0130 00", ["iban"]),
        ("IBAN GB00 WEST 1234 5698 7654 32 has a bad checksum", []),
    ],
)
def test_additional_patterns(text, expected):
    assert [d.type.value for d in pii.detect(text)] == expected


def test_card_digits_inside_iban_are_not_double_counted():
    detections = pii.detect("IBAN GB82 WEST 1234 5698 7654 32")
    assert [d.type for d in detections] == [PIIType.IBAN]


@pytest.mark.parametrize("digits, valid", [("4111111111111111", True), ("1234567890123456", False), ("41111", False)])
def test_luhn(digits, valid):
    assert pii.luhn_valid(digits) is valid


def test_iban_checksum():
    assert pii.iban_valid("GB82 WEST 1234 5698 7654 32")
    assert not pii.iban_valid("GB82 WEST 1234 5698 7654 33")
    assert not pii.iban_valid("GB82")


def test_placeholder_helpers():
    assert pii.contains_placeholder("see [CARD_NUMBER_2]")
    assert not pii.contains_placeholder("see [NOTE_1]")


def test_hash_is_salted_stable_and_type_scoped():
    first = pii.pii_hash("salt", PIIType.EMAIL, "a@example.com")
    assert first == pii.pii_hash("salt", PIIType.EMAIL, "a@example.com")
    assert first != pii.pii_hash("other", PIIType.EMAIL, "a@example.com")
    assert first != pii.pii_hash("salt", PIIType.CREDENTIAL, "a@example.com")
    assert first.startswith("sha256:") and "example" not in first
