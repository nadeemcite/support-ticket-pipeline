"""Ticket classification (SPEC §7.1): one LLM call per ticket, validated, retried, then overridden by rules.

Flow per ticket: prompt (P1-P6) -> model JSON -> Pydantic + taxonomy validation (C0) with up to two
content retries carrying the errors -> fallback (CF) if still invalid -> deterministic overrides C1-C5.
Every override is recorded in ``meta.overrides``.
"""

import re
from dataclasses import dataclass

from pydantic import ValidationError

from pipeline.llm import CallResult, LLMClient, echo_for_retry, parse_json_object
from pipeline.prompts import CLASSIFY_VERSION, classification_json_schema, classify_messages, retry_feedback
from pipeline.schemas import Classification, ClassificationMeta, ClassificationOutput, KBArticle, NormalisedTicket
from pipeline.taxonomy import IssueType, LLMStage, PIIType, ResolutionAction, Urgency

MAX_ATTEMPTS = 3
OUTPUT_ARTIFACT = "ticket_classification.json"

# C1: refund/charge language in the ticket itself (en + es/fr/de/pt). Evidence is not scanned: retrieval
# keeps loosely related articles (e.g. a refund-policy article next to an invoice question).
REFUND_RE = re.compile(
    r"\b(refund\w*|charge[sd]?|charging|chargeback\w*|billed twice|double[- ]charged?|duplicate charges?|money back|"
    r"reimburs\w*|reembols\w*|rembours\w*|r[uü]ckerstatt\w*|erstatt\w*|cobr[oa]\w*|d[eé]bit\w*|abgebucht)\b"
    r"|\bgeld\b.{0,40}\bzur[uü]ck\b",
    re.IGNORECASE,
)

FALLBACK_RATIONALE = "Automatic fallback: model output failed validation"


@dataclass(frozen=True)
class AttemptOutcome:
    status: str
    output: ClassificationOutput | None
    errors: list[str]


def _check(result: CallResult, ticket_id: str) -> AttemptOutcome:
    if result.error:
        return AttemptOutcome("transport_error", None, [result.error])
    try:
        data = parse_json_object(result.text)
    except ValueError as exc:
        return AttemptOutcome("invalid_json", None, [f"not a valid JSON object ({exc})"])
    try:
        output = ClassificationOutput.model_validate(data)
    except ValidationError as exc:
        errors = [f"{'.'.join(str(p) for p in err['loc']) or 'output'}: {err['msg']}" for err in exc.errors()]
        return AttemptOutcome("schema_error", None, errors)
    if output.ticket_id != ticket_id:
        return AttemptOutcome("rule_violation", None, [f'ticket_id must be "{ticket_id}", got "{output.ticket_id}"'])
    return AttemptOutcome("ok", output, [])


def apply_overrides(output: ClassificationOutput, ticket: NormalisedTicket, evidence: list[KBArticle]) -> tuple[dict, list[str]]:
    """Deterministic rules C1-C5; code overrides the model on safety-relevant fields."""
    values = output.model_dump()
    overrides: list[str] = []
    text = f"{ticket.subject} {ticket.message}"
    if not values["requires_refund_caution"] and REFUND_RE.search(text):
        values["requires_refund_caution"] = True
        overrides.append("C1: refund/charge language in ticket -> requires_refund_caution=true")
    if ticket.insufficient_content and values["resolution_action"] == ResolutionAction.ANSWER_FROM_KB:
        values["resolution_action"] = ResolutionAction.REQUEST_MORE_INFO
        overrides.append("C2: insufficient content, answer_from_kb -> request_more_info")
    if not evidence and values["resolution_action"] == ResolutionAction.ANSWER_FROM_KB:
        values["resolution_action"] = ResolutionAction.NEEDS_HUMAN_ESCALATION
        overrides.append("C3: no evidence, answer_from_kb -> needs_human_escalation")
    if values["issue_type"] in (IssueType.BILLING, IssueType.ACCOUNT_ACCESS) and not values["customer_sensitive"]:
        values["customer_sensitive"] = True
        overrides.append(f"C4: issue_type {values['issue_type'].value} -> customer_sensitive=true")
    if any(entry.type == PIIType.CREDENTIAL for entry in ticket.pii_summary) and not values["customer_sensitive"]:
        values["customer_sensitive"] = True
        overrides.append("C5: credential disclosed in ticket -> customer_sensitive=true")
    return values, overrides


def fallback_output(ticket: NormalisedTicket) -> ClassificationOutput:
    return ClassificationOutput(
        ticket_id=ticket.ticket_id,
        issue_type=IssueType.OTHER,
        urgency=Urgency.MEDIUM,
        resolution_action=ResolutionAction.NEEDS_HUMAN_ESCALATION,
        customer_sensitive=True,
        requires_refund_caution=bool(REFUND_RE.search(f"{ticket.subject} {ticket.message}")),
        rationale=FALLBACK_RATIONALE,
    )


def classify_ticket(
    client: LLMClient, ticket: NormalisedTicket, evidence: list[KBArticle], input_artifacts: list[str]
) -> Classification:
    messages = classify_messages(ticket, evidence)
    schema = classification_json_schema()
    output: ClassificationOutput | None = None
    attempts = 0
    for attempt in range(1, MAX_ATTEMPTS + 1):
        attempts = attempt
        result = client.call(LLMStage.CLASSIFICATION, messages, CLASSIFY_VERSION, schema)
        outcome = _check(result, ticket.ticket_id)
        client.log(
            llm_stage=LLMStage.CLASSIFICATION, ticket_id=ticket.ticket_id, result=result, prompt_version=CLASSIFY_VERSION,
            input_artifacts=input_artifacts, output_artifact=OUTPUT_ARTIFACT, attempt=attempt, status=outcome.status,
        )
        if outcome.output is not None:
            output = outcome.output
            break
        if outcome.status != "transport_error":  # a transport failure retries the same prompt
            messages = [*messages, {"role": "assistant", "content": echo_for_retry(result.text)}, {"role": "user", "content": retry_feedback(outcome.errors)}]

    fallback = output is None
    values, overrides = apply_overrides(output or fallback_output(ticket), ticket, evidence)
    return Classification(
        **values,
        meta=ClassificationMeta(
            fallback=fallback, attempts=attempts, overrides=overrides, evidence_ids=[a.article_id for a in evidence]
        ),
    )
