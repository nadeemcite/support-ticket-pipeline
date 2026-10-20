"""Escalation decision and queue routing (SPEC §7.3): a pure function of classification + KB evidence.

E1-E3 decide ``escalate = true`` (E4/E5 decide false). Routing prefers the escalation clause in a retrieved
article of the ticket's category (Q1) and falls back to the issue type (Q2). The ``reason`` names every
rule fired and quotes the KB clause (E-INV2); it never contains PII or a refund promise (E-INV3/E-INV4).
"""

import re

from pipeline import guards
from pipeline.retrieval import split_sentences
from pipeline.schemas import Classification, Escalation, EscalationMeta, KBArticle
from pipeline.taxonomy import IssueType, ResolutionAction, TargetQueue, Urgency

_CLAUSE_RE = re.compile(r"\bescalat(?:e|ed)\s+to\s+([A-Za-z ]+)", re.IGNORECASE)
_TEAM_STOP = frozenset("if so with immediately and when as for in because after then once or but to".split())
REFUND_NOTE = "Refund eligibility is not assumed; verify settlement status first."

ISSUE_QUEUE = {
    IssueType.BILLING: TargetQueue.BILLING_OPS,
    IssueType.ACCOUNT_ACCESS: TargetQueue.ACCOUNT_SUPPORT,
    IssueType.TECHNICAL_PROBLEM: TargetQueue.GENERAL_SUPPORT,
    IssueType.HOW_TO: TargetQueue.GENERAL_SUPPORT,
    IssueType.OTHER: TargetQueue.GENERAL_SUPPORT,
}


def team_queue(team: str) -> TargetQueue:
    if "billing" in team:
        return TargetQueue.BILLING_OPS
    if "account" in team:
        return TargetQueue.ACCOUNT_SUPPORT
    return TargetQueue.GENERAL_SUPPORT


def find_clause(articles: list[KBArticle], issue_type: IssueType) -> tuple[str, str, TargetQueue] | None:
    """Q1: first escalation clause (rank order) in an article whose category equals the issue type."""
    for article in articles:
        if article.category != issue_type.value:
            continue
        for sentence in split_sentences(article.content):
            match = _CLAUSE_RE.search(sentence)
            if not match:
                continue
            words: list[str] = []
            for word in match.group(1).lower().split():
                if word in _TEAM_STOP:
                    break
                words.append(word)
            return article.article_id, sentence.strip(), team_queue(" ".join(words[:3]))
    return None


def _summary(c: Classification) -> str:
    return f"{c.issue_type.value}, {c.urgency.value}"


def decide(classification: Classification, evidence: list[KBArticle]) -> Escalation:
    c = classification
    fired: list[str] = []
    reasons: list[str] = []
    if c.resolution_action == ResolutionAction.NEEDS_HUMAN_ESCALATION:
        fired.append("E1")
        reasons.append(f"E1: classification resolution_action=needs_human_escalation ({_summary(c)})")
    if c.urgency == Urgency.CRITICAL:
        fired.append("E2")
        reasons.append("E2: urgency=critical")
    if c.meta.fallback:
        fired.append("E3")
        reasons.append("E3: classification fell back after model output failed validation")

    evidence_ids: list[str] = []
    if not fired:
        if c.resolution_action == ResolutionAction.REQUEST_MORE_INFO:
            rule, text = "E4", "E4: resolution_action=request_more_info; waiting on the customer, no escalation"
        else:
            rule, text = "E5", f"E5: resolution_action={c.resolution_action.value} ({_summary(c)}); no escalation condition met"
        escalation = _build(c, False, TargetQueue.NONE, [rule], text, evidence_ids)
        return escalation

    clause = find_clause(evidence, c.issue_type)
    if clause:
        article_id, sentence, queue = clause
        fired.append("Q1")
        evidence_ids = [article_id]
        routing = f"Q1: {article_id}: '{sentence}' -> {queue.value}"
    else:
        queue = ISSUE_QUEUE[c.issue_type]
        fired.append("Q2")
        routing = f"Q2: no KB escalation clause for {c.issue_type.value}; routed by issue_type -> {queue.value}"
    return _build(c, True, queue, fired, "; ".join(reasons) + ". " + routing, evidence_ids)


def _build(c: Classification, escalate: bool, queue: TargetQueue, fired: list[str], reason: str, evidence_ids: list[str]) -> Escalation:
    if c.requires_refund_caution:
        reason = f"{reason}. {REFUND_NOTE}" if not reason.endswith(".") else f"{reason} {REFUND_NOTE}"
    if _unsafe(reason, c):  # a quoted KB clause must never break E-INV3 / E-INV4: drop the quote, keep the rule IDs
        reason = f"{' '.join(fired)}: see rule IDs; routing -> {queue.value}."
        if c.requires_refund_caution:
            reason += f" {REFUND_NOTE}"
    return Escalation(
        ticket_id=c.ticket_id, escalate=escalate, target_queue=queue, reason=reason,
        meta=EscalationMeta(rules_fired=fired, evidence_ids=evidence_ids),
    )


def _unsafe(reason: str, c: Classification) -> bool:
    return (
        guards.has_pii(reason)
        or guards.has_placeholder(reason)
        or (c.requires_refund_caution and guards.s2_refund_promise(reason))
    )
