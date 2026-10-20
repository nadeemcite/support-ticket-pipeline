# Stage 5 — sample walkthrough

T-1001, T-1002 and T-1003 through every stage of one real run (`glm-5.2` + `text-embedding-3-small`, root inputs). Each decision lists the rule that made it. Run it yourself: `python run_pipeline.py` (the artifacts are regenerated; `--log-prompts` also dumps the masked prompts under `artifacts/prompts/`, keyed by the hashes below).

## T-1001

**1. Ticket (normalised, PII masked)**

- tier `standard`, language `en`, PII entries: 0
- subject: I was charged twice for one order
- message: I placed one order yesterday but my card shows two charges. One is completed and the other is pending. Please refund me now.

**2. Retrieval** (`retrieval_results.json`, why in `retrieval_debug.json`)

| Rank | Article | Score | Kept | Best matching sentence |
|---|---|---|---|---|
| 1 | KB-001 | 0.5553 | ✅ | Escalate to billing ops if two settled charges exist for the same order. |
| 2 | KB-004 | 0.2895 | ✅ | Refunds depend on settlement status, product type, and fraud checks. |
| 3 | KB-003 | 0.1642 |  | If invoices are missing, escalate to billing support. |
| 4 | KB-002 | 0.1439 |  | If the reset succeeded but login still fails, escalate to account support. |

Kept (top 2, score ≥ min_score): ['KB-001', 'KB-004']

**3. Classification** (`classify.v1`, validated; overrides C1–C5 applied after the model)

- issue_type `billing` · urgency `medium` · action `answer_from_kb` · customer_sensitive `True` · requires_refund_caution `True`
- model rationale: KB-001 explains that a completed charge plus a pending authorization is normal and the pending charge typically drops off in 3-5 days; no refund should be promised unless two settled charges are confirmed. KB-004 reinforces not guaranteeing same-day refunds.
- overrides: none · attempts 1 · fallback False · evidence ['KB-001', 'KB-004']

**4. Draft** (`draft.v1`; hard rules D3–D11 checked before acceptance, grounding G1–G3 after)

- citations ['KB-001', 'KB-004'] · attempts 1 · fallback False · rules hit before acceptance none
- grounding flags: none

> Hello,
> 
> Thank you for reaching out about the duplicate charges you noticed on your card.
> 
> It is common to see both a completed charge and a temporary pending authorization for the same order. Pending authorizations typically disappear on their own within 3-5 business days, as they are not settled charges.
> 
> If two fully settled charges are confirmed for the same order, our billing team will review whether a refund applies. I have noted your case for review, and if a duplicate settled charge is found, the billing team will follow up with you.
> 
> If the pending authorization does not disappear after 5 business days, please reply to this ticket and we will investigate further.
> 
> Thank you for your patience.
> 
> Best regards,
> Customer Support

**5. Escalation** (pure rules, no LLM)

- escalate `False` → queue `none` · rules fired ['E5'] · evidence []
- reason: E5: resolution_action=answer_from_kb (billing, medium); no escalation condition met. Refund eligibility is not assumed; verify settlement status first.

**6. LLM log lines** (`llm_calls.jsonl`; prompts are never stored, only hashes)

| Stage | Attempt | Status | Cached | Prompt hash | Prompt version |
|---|---|---|---|---|---|
| classification | 1 | ok | True | `sha256:9c27cf0e3df9ef57…` | classify.v1 |
| drafting | 1 | ok | True | `sha256:99f6441c5c7b7217…` | draft.v1 |

## T-1002

**1. Ticket (normalised, PII masked)**

- tier `vip`, language `en`, PII entries: 0
- subject: Cannot log in after resetting password
- message: I changed my password this morning. Now every login attempt says invalid credentials although the reset link worked.

**2. Retrieval** (`retrieval_results.json`, why in `retrieval_debug.json`)

| Rank | Article | Score | Kept | Best matching sentence |
|---|---|---|---|---|
| 1 | KB-002 | 0.5529 | ✅ | If the reset succeeded but login still fails, escalate to account support. |
| 2 | KB-001 | 0.1342 |  | Customers may see both a completed charge and a temporary pending authorization. |
| 3 | KB-003 | 0.1123 |  | If invoices are missing, escalate to billing support. |
| 4 | KB-004 | 0.0738 |  | Refunds depend on settlement status, product type, and fraud checks. |

Kept (top 1, score ≥ min_score): ['KB-002']

**3. Classification** (`classify.v1`, validated; overrides C1–C5 applied after the model)

- issue_type `account_access` · urgency `high` · action `needs_human_escalation` · customer_sensitive `True` · requires_refund_caution `False`
- model rationale: KB-002 states that if a password reset succeeded but login still fails, escalate to account support. The customer confirms the reset link worked yet login still fails, meeting the escalation condition. VIP is blocked from core use, so urgency is high.
- overrides: none · attempts 1 · fallback False · evidence ['KB-002']

**4. Draft** (`draft.v1`; hard rules D3–D11 checked before acceptance, grounding G1–G3 after)

- citations ['KB-002'] · attempts 1 · fallback False · rules hit before acceptance none
- grounding flags: none

> Hello,
> 
> Thank you for reaching out about being unable to log in after resetting your password. I'm sorry for the inconvenience this is causing.
> 
> Before we proceed, please try the following steps:
> 
> 1. Make sure you are using the most recent password you set during the reset.
> 2. Clear your browser's cached sessions and cookies.
> 3. Retry logging in using an incognito or private browsing window.
> 
> If the issue persists after these steps, I have escalated your case to our account support specialist team. They will review your account and follow up with you directly to resolve the login problem.
> 
> Please never share your password or any security codes with anyone, including our support staff.
> 
> Thank you for your patience.
> 
> Best regards,
> Customer Support

**5. Escalation** (pure rules, no LLM)

- escalate `True` → queue `account_support` · rules fired ['E1', 'Q1'] · evidence ['KB-002']
- reason: E1: classification resolution_action=needs_human_escalation (account_access, high). Q1: KB-002: 'If the reset succeeded but login still fails, escalate to account support.' -> account_support

**6. LLM log lines** (`llm_calls.jsonl`; prompts are never stored, only hashes)

| Stage | Attempt | Status | Cached | Prompt hash | Prompt version |
|---|---|---|---|---|---|
| classification | 1 | ok | True | `sha256:193688c4bd3827db…` | classify.v1 |
| drafting | 1 | ok | True | `sha256:81bfa3ed4ecf13a1…` | draft.v1 |

## T-1003

**1. Ticket (normalised, PII masked)**

- tier `standard`, language `en`, PII entries: 0
- subject: Where can I download invoice PDFs?
- message: I need invoices for the last three months for accounting. I cannot find the download option in the dashboard.

**2. Retrieval** (`retrieval_results.json`, why in `retrieval_debug.json`)

| Rank | Article | Score | Kept | Best matching sentence |
|---|---|---|---|---|
| 1 | KB-003 | 0.7572 | ✅ | Customers can filter by month and download each invoice as PDF. |
| 2 | KB-002 | 0.2311 |  | Ask the user to verify they are using the most recent password, clear cached sessions, and retry in an incognito window. |
| 3 | KB-004 | 0.1646 |  | Refunds depend on settlement status, product type, and fraud checks. |
| 4 | KB-001 | 0.163 |  | Pending authorizations usually disappear within 3-5 business days. |

Kept (top 1, score ≥ min_score): ['KB-003']

**3. Classification** (`classify.v1`, validated; overrides C1–C5 applied after the model)

- issue_type `how_to` · urgency `low` · action `answer_from_kb` · customer_sensitive `True` · requires_refund_caution `False`
- model rationale: KB-003 directly answers where to download invoice PDFs (Billing > Documents). No missing invoices are reported, so no escalation condition applies.
- overrides: none · attempts 1 · fallback False · evidence ['KB-003']

**4. Draft** (`draft.v1`; hard rules D3–D11 checked before acceptance, grounding G1–G3 after)

- citations ['KB-003'] · attempts 1 · fallback False · rules hit before acceptance none
- grounding flags: G1 ['three months']

> Hello,
> 
> Thank you for reaching out. Invoice PDFs can be downloaded from the dashboard by navigating to Billing > Documents. From there, you can filter by month and download each invoice as a PDF.
> 
> If any invoices for the last three months are missing from that section, please let us know and we will escalate the matter to our billing support team for further assistance.
> 
> Best regards,
> Customer Support

**5. Escalation** (pure rules, no LLM)

- escalate `False` → queue `none` · rules fired ['E5'] · evidence []
- reason: E5: resolution_action=answer_from_kb (how_to, low); no escalation condition met

**6. LLM log lines** (`llm_calls.jsonl`; prompts are never stored, only hashes)

| Stage | Attempt | Status | Cached | Prompt hash | Prompt version |
|---|---|---|---|---|---|
| classification | 1 | ok | True | `sha256:b00d3100bfc509f7…` | classify.v1 |
| drafting | 1 | ok | True | `sha256:844e0378ecd29ad9…` | draft.v1 |

## Validation (whole run)

**PASS**: 13 of 14 checks passed, 1 warnings: V01 pass, V02 pass, V03 pass, V04 pass, V05 pass, V06 pass, V07 pass, V08 pass, V09 pass, V10 pass, V11 pass, V12 warn, V13 pass, V14 pass.
