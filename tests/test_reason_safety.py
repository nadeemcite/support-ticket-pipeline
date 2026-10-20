"""Escalation reasons never match S2 and never contain PII or placeholders (E-INV3/E-INV4)."""

import itertools

import pytest

from pipeline import guards
from pipeline.escalate import decide
from pipeline.schemas import Classification, ClassificationMeta
from pipeline.taxonomy import IssueType, ResolutionAction, Urgency
from tests.test_escalation_rules import ACCOUNT_KB, BILLING_KB, SUPPORT_KB

pytestmark = pytest.mark.stage4


def test_every_reason_is_safe():
    count = 0
    for issue, urgency, action, caution, fallback in itertools.product(IssueType, Urgency, ResolutionAction, (False, True), (False, True)):
        c = Classification(
            ticket_id="T-1", issue_type=issue, urgency=urgency, resolution_action=action, customer_sensitive=True,
            requires_refund_caution=caution, rationale="Contact jane@example.com about card 4111 1111 1111 1111",
            meta=ClassificationMeta(fallback=fallback),
        )
        reason = decide(c, [BILLING_KB, ACCOUNT_KB, SUPPORT_KB]).reason
        assert not guards.s2_refund_promise(reason) and not guards.has_pii(reason) and not guards.has_placeholder(reason), reason
        assert "jane" not in reason and "4111" not in reason  # the classification rationale is never copied
        count += 1
    assert count == 4 * 5 * 3 * 4
