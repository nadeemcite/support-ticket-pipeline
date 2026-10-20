## BUILD

Build a small, replayable AI pipeline that reads a batch of support tickets and a knowledge base, retrieves grounded evidence for each ticket, classifies the ticket, drafts a response, and decides whether the ticket should be escalated.

This is not a one-shot prompt demo. The evaluator will run your solution from a clean checkout and may replace the input files with equivalent fixtures. Your pipeline should regenerate outputs from disk inputs, preserve intermediate artifacts, validate structured outputs, and make it easy to inspect what happened.

Focus on practical AI engineering: retrieval quality, stage control, structured outputs, validation, and production-minded handling of edge cases.

---

## INPUT FILES

Your pipeline must read these files from disk:

- `tickets.json`
- `kb_articles.json`

The evaluator may replace them with equivalent files using the same structure.

---

## SAMPLE `tickets.json`

```json
{
  "tickets": [
    {
      "ticket_id": "T-1001",
      "customer_tier": "standard",
      "language": "en",
      "subject": "I was charged twice for one order",
      "message": "I placed one order yesterday but my card shows two charges. One is completed and the other is pending. Please refund me now.",
      "created_at": "2026-05-20T10:15:00Z"
    },
    {
      "ticket_id": "T-1002",
      "customer_tier": "vip",
      "language": "en",
      "subject": "Cannot log in after resetting password",
      "message": "I changed my password this morning. Now every login attempt says invalid credentials although the reset link worked.",
      "created_at": "2026-05-20T11:05:00Z"
    },
    {
      "ticket_id": "T-1003",
      "customer_tier": "standard",
      "language": "en",
      "subject": "Where can I download invoice PDFs?",
      "message": "I need invoices for the last three months for accounting. I cannot find the download option in the dashboard.",
      "created_at": "2026-05-20T12:40:00Z"
    }
  ]
}
```

---

## SAMPLE `kb_articles.json`

```json
{
  "articles": [
    {
      "article_id": "KB-001",
      "title": "Duplicate card charges and pending authorizations",
      "category": "billing",
      "updated_at": "2026-05-01T09:00:00Z",
      "content": "Customers may see both a completed charge and a temporary pending authorization. Pending authorizations usually disappear within 3-5 business days. Refunds should not be promised unless two settled charges are confirmed. Escalate to billing ops if two settled charges exist for the same order."
    },
    {
      "article_id": "KB-002",
      "title": "Login issues after password reset",
      "category": "account_access",
      "updated_at": "2026-05-10T09:00:00Z",
      "content": "Ask the user to verify they are using the most recent password, clear cached sessions, and retry in an incognito window. If the reset succeeded but login still fails, escalate to account support. Never ask the customer to send their password."
    },
    {
      "article_id": "KB-003",
      "title": "Downloading invoices from the dashboard",
      "category": "billing",
      "updated_at": "2026-04-15T09:00:00Z",
      "content": "Invoice PDFs are available under Billing > Documents. Customers can filter by month and download each invoice as PDF. If invoices are missing, escalate to billing support."
    },
    {
      "article_id": "KB-004",
      "title": "Refund policy overview",
      "category": "billing",
      "updated_at": "2026-03-22T09:00:00Z",
      "content": "Refunds depend on settlement status, product type, and fraud checks. Agents should not guarantee same-day refunds unless policy explicitly allows it."
    }
  ]
}
```

---

## CONTROLLED TAXONOMY

Define the classification taxonomy in code and validate model outputs against it.

Allowed issue types:

```text
billing
account_access
technical_problem
how_to
other
```

Allowed urgency levels:

```text
critical
high
medium
low
```

Allowed resolution actions:

```text
answer_from_kb
needs_human_escalation
request_more_info
```

Structured classification output:

```json
{
  "ticket_id": "string",
  "issue_type": "billing | account_access | technical_problem | how_to | other",
  "urgency": "critical | high | medium | low",
  "resolution_action": "answer_from_kb | needs_human_escalation | request_more_info",
  "customer_sensitive": true,
  "requires_refund_caution": true,
  "rationale": "string"
}
```

---

## PIPELINE STAGES

Your implementation must enforce these stages in code:

```text
INIT
 -> INPUTS_LOADED
 -> KB_INDEXED
 -> TICKETS_NORMALISED
 -> EVIDENCE_RETRIEVED
 -> TICKETS_CLASSIFIED
 -> RESPONSES_DRAFTED
 -> ESCALATIONS_DECIDED
 -> OUTPUTS_VALIDATED
 -> RESULTS_FINALISED
```

Response drafting must not run before retrieval and classification.

Escalation decisions must be grounded in the classification output and retrieved evidence.

---

## MUST COMPLETE

### 1. Knowledge Base Indexing and Retrieval

Build a deterministic retrieval step over `kb_articles.json`.

This can use embeddings, keyword scoring, TF-IDF, or another reasonable local approach.

For each ticket, retrieve the top 3 supporting articles before any LLM drafting step.

Save retrieval results to:

```text
retrieval_results.json
```

Each result must include:

```json
{
  "ticket_id": "T-1001",
  "retrieved_articles": [
    {
      "article_id": "KB-001",
      "score": 0.91,
      "title": "Duplicate card charges and pending authorizations"
    }
  ]
}
```

If retrieval finds no useful match, return an empty list and continue safely.

---

### 2. Ticket Classification

Make one structured LLM call per ticket, or one structured batch call if your code still preserves per-ticket validation and traceability.

The classification prompt must include:

- the ticket content
- the retrieved article snippets or summaries
- the controlled taxonomy
- an instruction not to invent categories

Save output to `ticket_classification.json`.

---

### 3. Grounded Response Drafting

Generate one customer-facing draft reply per ticket.

The draft must be grounded only in the retrieved articles and the classification result.

The draft must:

- answer in the ticket language
- avoid promising refunds or actions not supported by the KB
- avoid asking for passwords or other unsafe information
- mention escalation when the classification says escalation is needed

Save output to `draft_responses.json`.

Each draft must include:

```json
{
  "ticket_id": "T-1001",
  "draft_response": "string",
  "citations": ["KB-001", "KB-004"]
}
```

---

### 4. Escalation Decision

Produce an escalation artifact for all tickets.

Each record must include:

```json
{
  "ticket_id": "T-1001",
  "escalate": true,
  "target_queue": "billing_ops | account_support | general_support | none",
  "reason": "string"
}
```

Rules:

- `target_queue` must be `none` when `escalate` is false
- billing refund or duplicate-charge cases should be careful not to assume a refund is due
- login issues after successful password reset should usually escalate to account support

Save output to `escalations.json`.

---

### 5. Output Validation

Include a validation command, for example:

```bash
python validate.py
```

The validator must check:

- required artifacts exist
- JSON files are valid
- every ticket appears in each artifact
- classification values use only the allowed taxonomy
- each drafted response cites only retrieved article IDs
- escalations obey the `target_queue` rule
- no response contains obviously unsafe phrases such as asking for the user's password

Save a summary to `validation_report.json`.

---

## SHOULD ATTEMPT

### 6. Retrieval Diagnostics

Add a simple retrieval diagnostic artifact showing why each article ranked highly.

This can be top matching terms, chunk text, or similarity details.

Save to `retrieval_debug.json`.

---

### 7. Hallucination Guard

Add a deterministic check that flags a draft if it contains a concrete promise or instruction that is not supported by cited KB text.

A simple heuristic is enough.

Save flagged cases to `grounding_flags.json`.

---

## STRETCH

### 8. Replayability with Changed Inputs

Support rerunning the pipeline when `tickets.json` changes and avoid recomputing unchanged retrieval results if you choose.

If implemented, document your approach briefly in `README.md`.

---

## REQUIRED ARTIFACTS

Your repository must produce:

- `tickets.json`
- `kb_articles.json`
- `retrieval_results.json`
- `ticket_classification.json`
- `draft_responses.json`
- `escalations.json`
- `validation_report.json`
- `llm_calls.jsonl`

If attempted:

- `retrieval_debug.json`
- `grounding_flags.json`
- `README.md`

---

## `llm_calls.jsonl` REQUIREMENTS

Log one JSON object per LLM call.

Each record must include:

```json
{
  "stage": "classification | drafting",
  "ticket_id": "string",
  "timestamp": "ISO-8601 timestamp",
  "provider": "string",
  "model": "string",
  "prompt_hash": "string",
  "input_artifacts": ["path"],
  "output_artifact": "path"
}
```

If you use batch classification or drafting, the log must still make it clear which tickets were processed.

---

## EXECUTION REQUIREMENTS

The evaluator will run the pipeline from a clean checkout.

Generated artifacts may be deleted before evaluation.

The evaluator may replace `tickets.json` and `kb_articles.json` with equivalent inputs.

Static precomputed outputs are not sufficient.

Your solution must rerun the pipeline and regenerate outputs.

---

## TOOLS

Python is preferred.

Any LLM provider or local model tooling may be used.

---

## TECHNICAL CONSTRAINTS

- Retrieval must happen before drafting.
- Classification and drafting outputs must be structured and validated.
- The taxonomy must be enforced in code.
- Responses must be grounded in retrieved KB content.
- Unsafe requests such as asking for passwords must be blocked.
- Static precomputed outputs are not sufficient.
