"""S1/S2 wording added after review: question forms, "login credentials", "money back", active-voice refunds.

Kept apart from ``data/fixtures/safety_cases.json`` (a fixture; changing it is a reviewed change).
"""

import pytest

from pipeline import guards

pytestmark = pytest.mark.stage4


@pytest.mark.parametrize(
    "text",
    [
        "What is your password?",
        "What's your password and PIN?",
        "Please let us know your password.",
        "Let us know your login details.",
        "Please share your login credentials.",
        "Share your login details so we can check.",
        "Could you send your account credentials?",
    ],
)
def test_s1_fires(text):
    assert guards.s1_credential_request(text)


@pytest.mark.parametrize(
    "text",
    [
        "Never share your login credentials with anyone.",
        "Please do not share your login details.",
        "There is no need to send your credentials.",
        "What is your order number?",
        "We need to know what is happening with your account.",
        "Please make sure you are using your most recent password.",
    ],
)
def test_s1_stays_quiet(text):
    assert not guards.s1_credential_request(text)


@pytest.mark.parametrize(
    "text",
    [
        "Don't worry, you will get your money back.",
        "We will send you your money back.",
        "Money back is on its way.",
        "We will return your money.",
        "We have issued the refund.",
        "We've processed your refund today.",
        "We reversed the refund.",
        "I approved the refund.",
        "The refund was issued yesterday.",
        "Your refund has been reversed.",
    ],
)
def test_s2_fires(text):
    assert guards.s2_refund_promise(text)


@pytest.mark.parametrize(
    "text",
    [
        "We cannot promise your money back.",
        "I'm not able to confirm that we have issued the refund.",
        "We have not issued the refund yet.",
        "Refunds depend on settlement status.",
        "Refunds are processed only after review.",
        "A pending authorization is reversed automatically.",
        "Our team will review the refund request.",
    ],
)
def test_s2_stays_quiet(text):
    assert not guards.s2_refund_promise(text)
