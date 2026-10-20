"""S1-S3 against every case in data/fixtures/safety_cases.json (T4), plus window/negation edge cases."""

import pytest

from pipeline import guards
from tests.conftest import FIXTURES, load

pytestmark = pytest.mark.stage4

CASES = load(FIXTURES / "safety_cases.json")
CHECKS = {
    "S1_credential_request": guards.s1_credential_request,
    "S2_refund_promise": guards.s2_refund_promise,
    "S3_escalation_mention": guards.s3_escalation_mention,
}


@pytest.mark.parametrize(
    "check, case",
    [(name, case) for name in CHECKS for case in CASES[name]],
    ids=[case["id"] for name in CHECKS for case in CASES[name]],
)
def test_fixture_case(check, case):
    assert CHECKS[check](case["text"]) is case["match"], case["text"]


@pytest.mark.parametrize(
    "text",
    [
        "We will not be able to help unless you send your password.",  # negation far from the verb
        "Please reply with your PIN.",
        "Could you share the CVV printed on the back?",
        "Bitte geben Sie Ihr Passwort an.",
        "Envíe su código de verificación.",
    ],
)
def test_s1_still_fires_when_negation_is_not_adjacent(text):
    assert guards.s1_credential_request(text)


@pytest.mark.parametrize(
    "text",
    [
        "Geben Sie Ihr Passwort niemals an andere weiter.",  # verb-final negation
        "If you shared them, please change your password now.",
        "Si vous les avez partagés, changez votre mot de passe.",
        "Please never send your PIN by email.",
    ],
)
def test_s1_does_not_fire_on_advice_or_participles(text):
    assert not guards.s1_credential_request(text)


@pytest.mark.parametrize(
    "text",
    [
        "We will not refund you today.",
        "We can't guarantee a refund.",
        "No refund has been issued yet.",
        "Billing will tell you whether a refund applies.",
    ],
)
def test_s2_negation_and_neutral_wording(text):
    assert not guards.s2_refund_promise(text)


@pytest.mark.parametrize(
    "text",
    ["We have refunded the charge.", "Wir erstatten Ihnen den Betrag heute.", "Nous vous rembourserons demain.", "Você será reembolsado hoje."],
)
def test_s2_other_languages_and_forms(text):
    assert guards.s2_refund_promise(text)


@pytest.mark.parametrize(
    "text, expected",
    [
        ("We will never ask for your password.", True),
        ("Never share your one-time code with anyone.", True),
        ("Nunca comparta su contraseña con nadie.", True),
        ("Please send your password.", False),
        ("Thanks for your message.", False),
    ],
)
def test_credential_advice_d10(text, expected):
    assert guards.has_credential_advice(text) is expected


def test_pii_and_placeholder_checks():
    assert guards.has_pii("write to jane.doe@example.com") and not guards.has_pii("the email address you provided")
    assert guards.has_placeholder("we sent it to [EMAIL_1]") and not guards.has_placeholder("Billing > Documents")


@pytest.mark.parametrize(
    "text",
    [
        "Please confirm you are using the most recent password.",  # found in a real draft: a fact about the password, not the password
        "Make sure that your password is correct.",
        "Please check whether your PIN has changed.",
    ],
)
def test_s1_ignores_clauses_about_a_secret(text):
    assert not guards.s1_credential_request(text)


def test_s1_still_fires_when_the_secret_is_the_object():
    assert guards.s1_credential_request("Please confirm your password and PIN.")
