# Stage 3 — LLM trace sample

Five first-attempt log lines from `gpt-6.1-sol`, repeat 1 (seeded sample). For each: the `llm_calls.jsonl` line, the prompt re-built from the frozen inputs with its hash **recomputed** and compared to the logged one, the raw model output (from the prompt-hash cache), and the final record. This shows every classification can be traced to an exact prompt without storing prompt text in the log.

## E-2011

**Log line**
```json
{
  "attempt": 1,
  "cached": false,
  "input_artifacts": [
    "data/eval/tickets.json (normalised)",
    "retrieval (embedding, min_score 0.25)",
    "data/eval/kb_articles.json"
  ],
  "latency_ms": 4026.9,
  "model": "gpt-6.1-sol",
  "output_artifact": "ticket_classification.json",
  "prompt_hash": "sha256:5f9c818792a565babdedc4a7fdef0e4b0d675650bc4392a5f1eb75eb24f1394c",
  "prompt_version": "classify.v1",
  "provider": "openai",
  "stage": "classification",
  "status": "ok",
  "ticket_id": "E-2011",
  "ticket_ids": [
    "E-2011"
  ],
  "timestamp": "2026-10-20T07:07:41.642Z",
  "usage": {
    "completion_tokens": 74,
    "prompt_tokens": 977
  }
}
```
**Recomputed prompt hash:** `sha256:5f9c818792a565babdedc4a7fdef0e4b0d675650bc4392a5f1eb75eb24f1394c` — ✅ matches the log

**User message (masked; the system message is the shared `classify.v1` template)**
```text
<ticket>
{
  "ticket_id": "E-2011",
  "customer_tier": "standard",
  "language": "en",
  "subject": "",
  "message": ""
}
</ticket>

<evidence>
No relevant KB articles were found.
</evidence>

Classify this ticket. The "ticket_id" in your answer must be "E-2011".
```
**Raw model output**
```json
{"ticket_id":"E-2011","issue_type":"other","urgency":"low","resolution_action":"request_more_info","customer_sensitive":false,"requires_refund_caution":false,"rationale":"The ticket has no subject or message, so more information is needed to identify the issue. No relevant KB articles were provided."}
```
**Final record in `ticket_classification.json` form**
```json
{
  "ticket_id": "E-2011",
  "issue_type": "other",
  "urgency": "low",
  "resolution_action": "request_more_info",
  "customer_sensitive": false,
  "requires_refund_caution": false,
  "rationale": "The ticket has no subject or message, so more information is needed to identify the issue. No relevant KB articles were provided.",
  "meta": {
    "fallback": false,
    "attempts": 1,
    "overrides": [],
    "evidence_ids": []
  }
}
```

## E-2005

**Log line**
```json
{
  "attempt": 1,
  "cached": false,
  "input_artifacts": [
    "data/eval/tickets.json (normalised)",
    "retrieval (embedding, min_score 0.25)",
    "data/eval/kb_articles.json"
  ],
  "latency_ms": 5292.6,
  "model": "gpt-6.1-sol",
  "output_artifact": "ticket_classification.json",
  "prompt_hash": "sha256:96b7ca0130c397193f6adecffd2c73aef595a548a764c17ae48122408522a1ef",
  "prompt_version": "classify.v1",
  "provider": "openai",
  "stage": "classification",
  "status": "ok",
  "ticket_id": "E-2005",
  "ticket_ids": [
    "E-2005"
  ],
  "timestamp": "2026-10-20T07:07:38.349Z",
  "usage": {
    "completion_tokens": 136,
    "prompt_tokens": 1182
  }
}
```
**Recomputed prompt hash:** `sha256:96b7ca0130c397193f6adecffd2c73aef595a548a764c17ae48122408522a1ef` — ✅ matches the log

**User message (masked; the system message is the shared `classify.v1` template)**
```text
<ticket>
{
  "ticket_id": "E-2005",
  "customer_tier": "standard",
  "language": "fr",
  "subject": "Où puis-je télécharger mes factures ?",
  "message": "J'ai besoin des factures PDF des trois derniers mois pour ma comptabilité, mais je ne trouve pas l'option de téléchargement."
}
</ticket>

<evidence>
[KB-003] Downloading invoices from the dashboard (category: billing)
Invoice PDFs are available under Billing > Documents. Customers can filter by month and download each invoice as PDF. If invoices are missing, escalate to billing support.

[KB-007] Exporting reports to CSV (category: how_to)
Reports can be exported under Reports > Export. Choose CSV as the format, select the date range, and click Download. Exports larger than 100,000 rows are sent by email as a download link within 30 minutes.

[KB-008] Cancelling a subscription (category: billing)
Subscriptions can be cancelled under Billing > Plan > Cancel subscription. Access continues until the end of the current billing period. Cancelling does not trigger an automatic refund for the current period. Requests to change where a refund is paid must be escalated to billing ops.
</evidence>

Classify this ticket. The "ticket_id" in your answer must be "E-2005".
```
**Raw model output**
```json
{
  "ticket_id": "E-2005",
  "issue_type": "billing",
  "urgency": "low",
  "resolution_action": "answer_from_kb",
  "customer_sensitive": true,
  "requires_refund_caution": false,
  "rationale": "KB-003 explains how to filter invoices by month and download PDFs under Billing > Documents. The customer cannot find the download option but does not report missing invoices, so the escalation condition is not met."
}
```
**Final record in `ticket_classification.json` form**
```json
{
  "ticket_id": "E-2005",
  "issue_type": "billing",
  "urgency": "low",
  "resolution_action": "answer_from_kb",
  "customer_sensitive": true,
  "requires_refund_caution": false,
  "rationale": "KB-003 explains how to filter invoices by month and download PDFs under Billing > Documents. The customer cannot find the download option but does not report missing invoices, so the escalation condition is not met.",
  "meta": {
    "fallback": false,
    "attempts": 1,
    "overrides": [],
    "evidence_ids": [
      "KB-003",
      "KB-007",
      "KB-008"
    ]
  }
}
```

## E-2013

**Log line**
```json
{
  "attempt": 1,
  "cached": false,
  "input_artifacts": [
    "data/eval/tickets.json (normalised)",
    "retrieval (embedding, min_score 0.25)",
    "data/eval/kb_articles.json"
  ],
  "latency_ms": 4854.0,
  "model": "gpt-6.1-sol",
  "output_artifact": "ticket_classification.json",
  "prompt_hash": "sha256:5ac515d7c2816992366f36f823294b685407d77d46703f519e1d1280c5546e1c",
  "prompt_version": "classify.v1",
  "provider": "openai",
  "stage": "classification",
  "status": "ok",
  "ticket_id": "E-2013",
  "ticket_ids": [
    "E-2013"
  ],
  "timestamp": "2026-10-20T07:07:43.727Z",
  "usage": {
    "completion_tokens": 110,
    "prompt_tokens": 1220
  }
}
```
**Recomputed prompt hash:** `sha256:5ac515d7c2816992366f36f823294b685407d77d46703f519e1d1280c5546e1c` — ✅ matches the log

**User message (masked; the system message is the shared `classify.v1` template)**
```text
<ticket>
{
  "ticket_id": "E-2013",
  "customer_tier": "vip",
  "language": "en",
  "subject": "Lost my phone with the authenticator app",
  "message": "I got a new phone and can no longer get my two-factor codes. Can you turn off 2FA for me? You can reach me on [PHONE_1]."
}
</ticket>

<evidence>
[KB-005] Lost access to two-factor authentication device (category: account_access)
If a customer has lost access to their two-factor authentication (2FA) device, support agents must not disable 2FA from chat or email. Escalate to account support so the customer's identity can be verified. Never ask the customer for one-time codes or recovery codes.

[KB-002] Login issues after password reset (category: account_access)
Ask the user to verify they are using the most recent password, clear cached sessions, and retry in an incognito window. If the reset succeeded but login still fails, escalate to account support. Never ask the customer to send their password.

[KB-006] Mobile app crashes on launch (category: technical_problem)
Ask the customer to update the app to the latest version, restart the device, and reinstall the app. Collect the device model, operating system version and app version. If the app still crashes after reinstalling, escalate to general support with the collected details.
</evidence>

Classify this ticket. The "ticket_id" in your answer must be "E-2013".
```
**Raw model output**
```json
{
  "ticket_id": "E-2013",
  "issue_type": "account_access",
  "urgency": "high",
  "resolution_action": "needs_human_escalation",
  "customer_sensitive": true,
  "requires_refund_caution": false,
  "rationale": "The VIP customer is blocked by loss of access to their 2FA device. KB-005 requires escalation to account support for identity verification and prohibits disabling 2FA through chat or email."
}
```
**Final record in `ticket_classification.json` form**
```json
{
  "ticket_id": "E-2013",
  "issue_type": "account_access",
  "urgency": "high",
  "resolution_action": "needs_human_escalation",
  "customer_sensitive": true,
  "requires_refund_caution": false,
  "rationale": "The VIP customer is blocked by loss of access to their 2FA device. KB-005 requires escalation to account support for identity verification and prohibits disabling 2FA through chat or email.",
  "meta": {
    "fallback": false,
    "attempts": 1,
    "overrides": [],
    "evidence_ids": [
      "KB-005",
      "KB-002",
      "KB-006"
    ]
  }
}
```

## T-1001

**Log line**
```json
{
  "attempt": 1,
  "cached": false,
  "input_artifacts": [
    "data/eval/tickets.json (normalised)",
    "retrieval (embedding, min_score 0.25)",
    "data/eval/kb_articles.json"
  ],
  "latency_ms": 9411.7,
  "model": "gpt-6.1-sol",
  "output_artifact": "ticket_classification.json",
  "prompt_hash": "sha256:620606b695d2877c2cf8b6cdd8b11b16b3c42d24bb52e2e3306bafcd1dda3604",
  "prompt_version": "classify.v1",
  "provider": "openai",
  "stage": "classification",
  "status": "ok",
  "ticket_id": "T-1001",
  "ticket_ids": [
    "T-1001"
  ],
  "timestamp": "2026-10-20T07:07:34.722Z",
  "usage": {
    "completion_tokens": 162,
    "prompt_tokens": 1182
  }
}
```
**Recomputed prompt hash:** `sha256:620606b695d2877c2cf8b6cdd8b11b16b3c42d24bb52e2e3306bafcd1dda3604` — ✅ matches the log

**User message (masked; the system message is the shared `classify.v1` template)**
```text
<ticket>
{
  "ticket_id": "T-1001",
  "customer_tier": "standard",
  "language": "en",
  "subject": "I was charged twice for one order",
  "message": "I placed one order yesterday but my card shows two charges. One is completed and the other is pending. Please refund me now."
}
</ticket>

<evidence>
[KB-001] Duplicate card charges and pending authorizations (category: billing)
Customers may see both a completed charge and a temporary pending authorization. Pending authorizations usually disappear within 3-5 business days. Refunds should not be promised unless two settled charges are confirmed. Escalate to billing ops if two settled charges exist for the same order.

[KB-004] Refund policy overview (category: billing)
Refunds depend on settlement status, product type, and fraud checks. Agents should not guarantee same-day refunds unless policy explicitly allows it.

[KB-008] Cancelling a subscription (category: billing)
Subscriptions can be cancelled under Billing > Plan > Cancel subscription. Access continues until the end of the current billing period. Cancelling does not trigger an automatic refund for the current period. Requests to change where a refund is paid must be escalated to billing ops.
</evidence>

Classify this ticket. The "ticket_id" in your answer must be "T-1001".
```
**Raw model output**
```json
{
  "ticket_id": "T-1001",
  "issue_type": "billing",
  "urgency": "high",
  "resolution_action": "answer_from_kb",
  "customer_sensitive": true,
  "requires_refund_caution": true,
  "rationale": "KB-001 explains that a pending authorization alongside one completed charge usually disappears within 3–5 business days; escalation requires two settled charges, which are not reported here. Money is in dispute, but refunds must not be promised under KB-001 and KB-004."
}
```
**Final record in `ticket_classification.json` form**
```json
{
  "ticket_id": "T-1001",
  "issue_type": "billing",
  "urgency": "high",
  "resolution_action": "answer_from_kb",
  "customer_sensitive": true,
  "requires_refund_caution": true,
  "rationale": "KB-001 explains that a pending authorization alongside one completed charge usually disappears within 3–5 business days; escalation requires two settled charges, which are not reported here. Money is in dispute, but refunds must not be promised under KB-001 and KB-004.",
  "meta": {
    "fallback": false,
    "attempts": 1,
    "overrides": [],
    "evidence_ids": [
      "KB-001",
      "KB-004",
      "KB-008"
    ]
  }
}
```

## E-2002

**Log line**
```json
{
  "attempt": 1,
  "cached": false,
  "input_artifacts": [
    "data/eval/tickets.json (normalised)",
    "retrieval (embedding, min_score 0.25)",
    "data/eval/kb_articles.json"
  ],
  "latency_ms": 9213.8,
  "model": "gpt-6.1-sol",
  "output_artifact": "ticket_classification.json",
  "prompt_hash": "sha256:df494ebd232acb1d82c0da36be2e490396f082834481e90df7c2dd7ea54c165f",
  "prompt_version": "classify.v1",
  "provider": "openai",
  "stage": "classification",
  "status": "ok",
  "ticket_id": "E-2002",
  "ticket_ids": [
    "E-2002"
  ],
  "timestamp": "2026-10-20T07:07:34.525Z",
  "usage": {
    "completion_tokens": 99,
    "prompt_tokens": 1104
  }
}
```
**Recomputed prompt hash:** `sha256:df494ebd232acb1d82c0da36be2e490396f082834481e90df7c2dd7ea54c165f` — ✅ matches the log

**User message (masked; the system message is the shared `classify.v1` template)**
```text
<ticket>
{
  "ticket_id": "E-2002",
  "customer_tier": "standard",
  "language": "en",
  "subject": "Export monthly report as CSV",
  "message": "How do I export my monthly report as a CSV file? I need it for a spreadsheet."
}
</ticket>

<evidence>
[KB-007] Exporting reports to CSV (category: how_to)
Reports can be exported under Reports > Export. Choose CSV as the format, select the date range, and click Download. Exports larger than 100,000 rows are sent by email as a download link within 30 minutes.

[KB-003] Downloading invoices from the dashboard (category: billing)
Invoice PDFs are available under Billing > Documents. Customers can filter by month and download each invoice as PDF. If invoices are missing, escalate to billing support.
</evidence>

Classify this ticket. The "ticket_id" in your answer must be "E-2002".
```
**Raw model output**
```json
{
  "ticket_id": "E-2002",
  "issue_type": "how_to",
  "urgency": "low",
  "resolution_action": "answer_from_kb",
  "customer_sensitive": false,
  "requires_refund_caution": false,
  "rationale": "KB-007 fully explains how to export a report as CSV using Reports > Export, selecting the date range and downloading. No escalation condition applies."
}
```
**Final record in `ticket_classification.json` form**
```json
{
  "ticket_id": "E-2002",
  "issue_type": "how_to",
  "urgency": "low",
  "resolution_action": "answer_from_kb",
  "customer_sensitive": false,
  "requires_refund_caution": false,
  "rationale": "KB-007 fully explains how to export a report as CSV using Reports > Export, selecting the date range and downloading. No escalation condition applies.",
  "meta": {
    "fallback": false,
    "attempts": 1,
    "overrides": [],
    "evidence_ids": [
      "KB-007",
      "KB-003"
    ]
  }
}
```

