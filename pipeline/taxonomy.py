"""Controlled taxonomy (SPEC §4). The single source of truth for every allowed label.

Prompts, Pydantic schemas and the validator all read these enums, so they can never drift apart.
"""

from enum import StrEnum


class IssueType(StrEnum):
    BILLING = "billing"
    ACCOUNT_ACCESS = "account_access"
    TECHNICAL_PROBLEM = "technical_problem"
    HOW_TO = "how_to"
    OTHER = "other"


class Urgency(StrEnum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class ResolutionAction(StrEnum):
    ANSWER_FROM_KB = "answer_from_kb"
    NEEDS_HUMAN_ESCALATION = "needs_human_escalation"
    REQUEST_MORE_INFO = "request_more_info"


class TargetQueue(StrEnum):
    BILLING_OPS = "billing_ops"
    ACCOUNT_SUPPORT = "account_support"
    GENERAL_SUPPORT = "general_support"
    NONE = "none"


class LLMStage(StrEnum):
    CLASSIFICATION = "classification"
    DRAFTING = "drafting"


class PIIType(StrEnum):
    EMAIL = "email"
    PHONE = "phone"
    CARD_NUMBER = "card_number"
    IBAN = "iban"
    CREDENTIAL = "credential"


KNOWN_CUSTOMER_TIERS = frozenset({"standard", "vip"})

URGENCY_GUIDANCE: dict[Urgency, str] = {
    Urgency.CRITICAL: "Security compromise, account takeover, fraud, or a widespread outage",
    Urgency.HIGH: "Customer blocked from core use (can't log in, money in dispute), or a VIP blocked",
    Urgency.MEDIUM: "Degraded experience, a workaround exists",
    Urgency.LOW: "Information / how-to request",
}


def values(enum_cls: type[StrEnum]) -> list[str]:
    """Allowed values of a taxonomy enum, in declaration order."""
    return [member.value for member in enum_cls]
