"""Pydantic models for inputs and artifacts (SPEC §3, §6).

Output models use ``extra="forbid"`` so an unexpected field is a validation error,
never a silent pass-through.
"""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from pipeline.taxonomy import IssueType, LLMStage, PIIType, ResolutionAction, TargetQueue, Urgency

STRICT = ConfigDict(extra="forbid")


# --- Normalised inputs -------------------------------------------------------------------------


class PIISummaryEntry(BaseModel):
    """One masked value (SPEC §6.10). ``count`` = occurrences of the placeholder in the ticket."""

    model_config = STRICT

    type: PIIType
    placeholder: str
    count: int = Field(ge=1)
    hash: str


class NormalisedTicket(BaseModel):
    model_config = STRICT

    ticket_id: str
    input_index: int
    customer_tier: str
    language: str
    subject: str
    message: str
    created_at: str | None
    insufficient_content: bool = False
    truncated: bool = False
    notes: list[str] = Field(default_factory=list)
    extra: dict[str, Any] = Field(default_factory=dict)
    pii_summary: list[PIISummaryEntry] = Field(default_factory=list)
    content_hash: str


class KBArticle(BaseModel):
    model_config = STRICT

    article_id: str
    title: str
    category: str
    updated_at: str | None
    content: str


# --- Artifacts produced by later stages (defined now so the taxonomy is enforced everywhere) ----


class RetrievedArticle(BaseModel):
    model_config = STRICT

    article_id: str
    score: float = Field(ge=0.0, le=1.0)
    title: str


class RetrievalResult(BaseModel):
    model_config = STRICT

    ticket_id: str
    retrieved_articles: list[RetrievedArticle] = Field(max_length=3)


class ClassificationMeta(BaseModel):
    model_config = STRICT

    fallback: bool = False
    attempts: int = 1
    overrides: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)


class ClassificationOutput(BaseModel):
    """What the model must return (SPEC §6.3 fields, no ``meta``). Validated before any override."""

    model_config = STRICT

    ticket_id: str
    issue_type: IssueType
    urgency: Urgency
    resolution_action: ResolutionAction
    customer_sensitive: bool
    requires_refund_caution: bool
    rationale: str = Field(min_length=1, max_length=500)


class Classification(BaseModel):
    model_config = STRICT

    ticket_id: str
    issue_type: IssueType
    urgency: Urgency
    resolution_action: ResolutionAction
    customer_sensitive: bool
    requires_refund_caution: bool
    rationale: str = Field(min_length=1, max_length=500)
    meta: ClassificationMeta = Field(default_factory=ClassificationMeta)


class DraftMeta(BaseModel):
    model_config = STRICT

    language: str
    fallback: bool = False
    attempts: int = 1
    violations_resolved: list[str] = Field(default_factory=list)


class DraftResponse(BaseModel):
    model_config = STRICT

    ticket_id: str
    draft_response: str = Field(min_length=1)
    citations: list[str] = Field(default_factory=list)
    meta: DraftMeta


class DraftOutput(BaseModel):
    """What the model must return when drafting (SPEC §6.4 fields, no ``meta``)."""

    model_config = STRICT

    ticket_id: str
    draft_response: str
    citations: list[str] = Field(default_factory=list)


class GroundingFlag(BaseModel):
    """One unsupported claim in a draft (SPEC §6.6). Flags never block a draft."""

    model_config = STRICT

    ticket_id: str
    check: str
    claim_type: str
    sentence: str
    unsupported_tokens: list[str]
    cited_articles_checked: list[str]
    overlap: float = Field(ge=0.0, le=1.0)


class EscalationMeta(BaseModel):
    model_config = STRICT

    rules_fired: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)


class Escalation(BaseModel):
    model_config = STRICT

    ticket_id: str
    escalate: bool
    target_queue: TargetQueue
    reason: str = Field(min_length=1)
    meta: EscalationMeta = Field(default_factory=EscalationMeta)

    @model_validator(mode="after")
    def _queue_matches_escalate(self) -> "Escalation":
        # E-INV1: escalate == false <=> target_queue == "none"
        if (not self.escalate) != (self.target_queue == TargetQueue.NONE):
            raise ValueError("target_queue must be 'none' exactly when escalate is false (E-INV1)")
        return self


class LLMCallRecord(BaseModel):
    model_config = ConfigDict(extra="allow")

    stage: LLMStage
    ticket_id: str
    timestamp: str
    provider: str
    model: str
    prompt_hash: str
    input_artifacts: list[str]
    output_artifact: str
