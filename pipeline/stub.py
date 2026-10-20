"""Deterministic offline LLM provider (rule L7): keyword rules over the masked ticket in the prompt.

It exists so the full pipeline (prompting, parsing, validation, logging, overrides) runs without a
network. It is not a quality baseline and is never used by the evals.
"""

import json
import re
from typing import Any

from pipeline.llm import ChatResponse

_TICKET_RE = re.compile(r"<ticket>\s*(\{.*?\})\s*</ticket>", re.DOTALL)
_EVIDENCE_RE = re.compile(r"<evidence>\s*(.*?)\s*</evidence>", re.DOTALL)
_CLASSIFICATION_RE = re.compile(r"<classification>\s*(\{.*?\})\s*</classification>", re.DOTALL)

_RULES = [
    ("account_access", r"log ?in|password|passwort|contraseña|senha|2fa|two-factor|authenticat|locked out|logged into"),
    ("billing", r"refund|charg|invoice|factur|billing|subscription|abonnement|money|payment|iban"),
    ("technical_problem", r"crash|error|\b50\d\b|not load|fails?|failing|fecha sozinho|doesn't work|broken"),
    ("how_to", r"how (do|can) i|where (can|do) i|how to|export|où|wie kann"),
]


class StubProvider:
    name = "stub"
    model = "stub"

    def params(self, max_tokens: int, temperature: float) -> dict[str, Any]:
        return {"max_tokens": max_tokens, "temperature": temperature}

    def complete(self, messages: list[dict[str, str]], params: dict[str, Any], json_schema: dict | None) -> ChatResponse:
        prompt = next(m["content"] for m in messages if m["role"] == "user")
        if "<classification>" in prompt:
            return self._draft(prompt)
        ticket = json.loads(_TICKET_RE.search(prompt).group(1))
        evidence = _EVIDENCE_RE.search(prompt).group(1)
        has_evidence = not evidence.startswith("No relevant KB articles")
        text = f"{ticket['subject']} {ticket['message']}".lower()

        issue = next((label for label, pattern in _RULES if re.search(pattern, text)), "other")
        if re.search(r"someone|did not do|not me|unauthori", text) and issue == "account_access":
            urgency = "critical"
        elif issue == "how_to" or not text.strip():
            urgency = "low"
        elif ticket["customer_tier"] == "vip" or issue in ("account_access", "billing"):
            urgency = "high"
        else:
            urgency = "medium"
        if not text.strip() or (issue == "other" and has_evidence is False and len(text.split()) < 6):
            action = "request_more_info"
        elif issue == "account_access" or "settled" in text or "missing" in text:
            action = "needs_human_escalation"
        else:
            action = "answer_from_kb"
        cited = re.findall(r"^\[(KB-[^\]]+)\]", evidence, re.MULTILINE)
        output = {
            "ticket_id": ticket["ticket_id"],
            "issue_type": issue,
            "urgency": urgency,
            "resolution_action": action,
            "customer_sensitive": issue in ("billing", "account_access"),
            "requires_refund_caution": bool(re.search(r"refund|charg", text)),
            "rationale": f"Stub rules: matched {issue}" + (f"; evidence {', '.join(cited)}" if cited else "; no evidence"),
        }
        return ChatResponse(text=json.dumps(output), usage={"prompt_tokens": 0, "completion_tokens": 0})

    def _draft(self, prompt: str) -> ChatResponse:
        """Offline drafting: the top evidence article's first sentence plus whatever the rules require."""
        from pipeline.draft import TEMPLATES, template_language

        ticket = json.loads(_TICKET_RE.search(prompt).group(1))
        classification = json.loads(_CLASSIFICATION_RE.search(prompt).group(1))
        evidence = _EVIDENCE_RE.search(prompt).group(1)
        ids = re.findall(r"^\[(KB-[^\]]+)\]", evidence, re.MULTILINE)
        t = TEMPLATES[template_language(ticket["language"])]
        parts = [t["ack"]]
        if ids and classification["resolution_action"] == "answer_from_kb":
            body = evidence.split("\n", 1)[1].split("\n\n", 1)[0]
            parts.append(re.split(r"(?<=[.!?])\s+", body.strip())[0])
        if classification["resolution_action"] == "needs_human_escalation":
            parts.append(t["escalation"])
        if classification["resolution_action"] == "request_more_info":
            parts.append(t["more_info"])
        if classification["credential_disclosed"]:
            parts.append(t["password"])
        parts.append(t["followup"])
        output = {
            "ticket_id": ticket["ticket_id"],
            "draft_response": " ".join(parts),
            "citations": ids[:1] if classification["resolution_action"] == "answer_from_kb" else [],
        }
        return ChatResponse(text=json.dumps(output, ensure_ascii=False), usage={"prompt_tokens": 0, "completion_tokens": 0})
