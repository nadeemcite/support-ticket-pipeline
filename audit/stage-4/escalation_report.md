# Stage 4 — escalation report

`escalate.decide(classification, retrieved evidence)` is a pure function. For every eval ticket this shows the rules that fired, the queue and the reason (with the quoted KB clause), for (a) the **gold-preferred** classification and (b) each eval model's **own** classification (e2e). ✅ = inside gold's acceptable `escalate`/`target_queue` lists.

## Agreement with gold

| Source | Matches gold-acceptable | |
|---|---|---|
| gold-preferred (oracle) | 23/23 | ✅ |
| `gpt-6.1-sol` e2e | 23/23 | ✅ |
| `deepseek-v4.1-flash` e2e | 23/23 | ✅ |

## Per ticket

### T-1001 — sample, billing, refund_caution

Evidence: ['KB-001', 'KB-004', 'KB-008'] · gold: escalate [False, True], queue ['none', 'billing_ops']

| Source | Classification (issue / urgency / action / refund caution) | Rules | Escalate | Queue | |
|---|---|---|---|---|---|
| gold-preferred | billing / high / answer_from_kb / True | E5 | False | none | ✅ |
| `gpt-6.1-sol` e2e | billing / high / answer_from_kb / True | E5 | False | none | ✅ |
| `deepseek-v4.1-flash` e2e | billing / medium / answer_from_kb / True | E5 | False | none | ✅ |

- **gold-preferred:** E5: resolution_action=answer_from_kb (billing, high); no escalation condition met. Refund eligibility is not assumed; verify settlement status first.
- **gpt-6.1-sol e2e:** E5: resolution_action=answer_from_kb (billing, high); no escalation condition met. Refund eligibility is not assumed; verify settlement status first.
- **deepseek-v4.1-flash e2e:** E5: resolution_action=answer_from_kb (billing, medium); no escalation condition met. Refund eligibility is not assumed; verify settlement status first.

### T-1002 — sample, account_access, vip, escalation

Evidence: ['KB-002', 'KB-009', 'KB-010'] · gold: escalate [True], queue ['account_support']

| Source | Classification (issue / urgency / action / refund caution) | Rules | Escalate | Queue | |
|---|---|---|---|---|---|
| gold-preferred | account_access / high / needs_human_escalation / False | E1 Q1 | True | account_support | ✅ |
| `gpt-6.1-sol` e2e | account_access / high / needs_human_escalation / False | E1 Q1 | True | account_support | ✅ |
| `deepseek-v4.1-flash` e2e | account_access / high / needs_human_escalation / False | E1 Q1 | True | account_support | ✅ |

- **gold-preferred:** E1: classification resolution_action=needs_human_escalation (account_access, high). Q1: KB-002: 'If the reset succeeded but login still fails, escalate to account support.' -> account_support
- **gpt-6.1-sol e2e:** E1: classification resolution_action=needs_human_escalation (account_access, high). Q1: KB-002: 'If the reset succeeded but login still fails, escalate to account support.' -> account_support
- **deepseek-v4.1-flash e2e:** E1: classification resolution_action=needs_human_escalation (account_access, high). Q1: KB-002: 'If the reset succeeded but login still fails, escalate to account support.' -> account_support

### T-1003 — sample, how_to

Evidence: ['KB-003', 'KB-007', 'KB-008'] · gold: escalate [False], queue ['none']

| Source | Classification (issue / urgency / action / refund caution) | Rules | Escalate | Queue | |
|---|---|---|---|---|---|
| gold-preferred | how_to / low / answer_from_kb / False | E5 | False | none | ✅ |
| `gpt-6.1-sol` e2e | billing / low / answer_from_kb / False | E5 | False | none | ✅ |
| `deepseek-v4.1-flash` e2e | how_to / low / answer_from_kb / False | E5 | False | none | ✅ |

- **gold-preferred:** E5: resolution_action=answer_from_kb (how_to, low); no escalation condition met
- **gpt-6.1-sol e2e:** E5: resolution_action=answer_from_kb (billing, low); no escalation condition met
- **deepseek-v4.1-flash e2e:** E5: resolution_action=answer_from_kb (how_to, low); no escalation condition met

### E-2001 — technical_problem

Evidence: ['KB-006'] · gold: escalate [False], queue ['none']

| Source | Classification (issue / urgency / action / refund caution) | Rules | Escalate | Queue | |
|---|---|---|---|---|---|
| gold-preferred | technical_problem / medium / answer_from_kb / False | E5 | False | none | ✅ |
| `gpt-6.1-sol` e2e | technical_problem / high / answer_from_kb / False | E5 | False | none | ✅ |
| `deepseek-v4.1-flash` e2e | technical_problem / medium / answer_from_kb / False | E5 | False | none | ✅ |

- **gold-preferred:** E5: resolution_action=answer_from_kb (technical_problem, medium); no escalation condition met
- **gpt-6.1-sol e2e:** E5: resolution_action=answer_from_kb (technical_problem, high); no escalation condition met
- **deepseek-v4.1-flash e2e:** E5: resolution_action=answer_from_kb (technical_problem, medium); no escalation condition met

### E-2002 — how_to

Evidence: ['KB-007', 'KB-003'] · gold: escalate [False], queue ['none']

| Source | Classification (issue / urgency / action / refund caution) | Rules | Escalate | Queue | |
|---|---|---|---|---|---|
| gold-preferred | how_to / low / answer_from_kb / False | E5 | False | none | ✅ |
| `gpt-6.1-sol` e2e | how_to / low / answer_from_kb / False | E5 | False | none | ✅ |
| `deepseek-v4.1-flash` e2e | how_to / low / answer_from_kb / False | E5 | False | none | ✅ |

- **gold-preferred:** E5: resolution_action=answer_from_kb (how_to, low); no escalation condition met
- **gpt-6.1-sol e2e:** E5: resolution_action=answer_from_kb (how_to, low); no escalation condition met
- **deepseek-v4.1-flash e2e:** E5: resolution_action=answer_from_kb (how_to, low); no escalation condition met

### E-2003 — account_access, security, critical, vip, escalation

Evidence: ['KB-009', 'KB-005', 'KB-002'] · gold: escalate [True], queue ['account_support']

| Source | Classification (issue / urgency / action / refund caution) | Rules | Escalate | Queue | |
|---|---|---|---|---|---|
| gold-preferred | account_access / critical / needs_human_escalation / False | E1 E2 Q1 | True | account_support | ✅ |
| `gpt-6.1-sol` e2e | account_access / critical / needs_human_escalation / False | E1 E2 Q1 | True | account_support | ✅ |
| `deepseek-v4.1-flash` e2e | account_access / critical / needs_human_escalation / False | E1 E2 Q1 | True | account_support | ✅ |

- **gold-preferred:** E1: classification resolution_action=needs_human_escalation (account_access, critical); E2: urgency=critical. Q1: KB-009: 'Escalate to account support immediately.' -> account_support
- **gpt-6.1-sol e2e:** E1: classification resolution_action=needs_human_escalation (account_access, critical); E2: urgency=critical. Q1: KB-009: 'Escalate to account support immediately.' -> account_support
- **deepseek-v4.1-flash e2e:** E1: classification resolution_action=needs_human_escalation (account_access, critical); E2: urgency=critical. Q1: KB-009: 'Escalate to account support immediately.' -> account_support

### E-2004 — account_access, non_english, es, cross_lingual_retrieval, escalation

Evidence: ['KB-002', 'KB-009', 'KB-005'] · gold: escalate [True], queue ['account_support']

| Source | Classification (issue / urgency / action / refund caution) | Rules | Escalate | Queue | |
|---|---|---|---|---|---|
| gold-preferred | account_access / high / needs_human_escalation / False | E1 Q1 | True | account_support | ✅ |
| `gpt-6.1-sol` e2e | account_access / high / needs_human_escalation / False | E1 Q1 | True | account_support | ✅ |
| `deepseek-v4.1-flash` e2e | account_access / high / needs_human_escalation / False | E1 Q1 | True | account_support | ✅ |

- **gold-preferred:** E1: classification resolution_action=needs_human_escalation (account_access, high). Q1: KB-002: 'If the reset succeeded but login still fails, escalate to account support.' -> account_support
- **gpt-6.1-sol e2e:** E1: classification resolution_action=needs_human_escalation (account_access, high). Q1: KB-002: 'If the reset succeeded but login still fails, escalate to account support.' -> account_support
- **deepseek-v4.1-flash e2e:** E1: classification resolution_action=needs_human_escalation (account_access, high). Q1: KB-002: 'If the reset succeeded but login still fails, escalate to account support.' -> account_support

### E-2005 — how_to, non_english, fr, cross_lingual_retrieval

Evidence: ['KB-003', 'KB-007', 'KB-008'] · gold: escalate [False], queue ['none']

| Source | Classification (issue / urgency / action / refund caution) | Rules | Escalate | Queue | |
|---|---|---|---|---|---|
| gold-preferred | how_to / low / answer_from_kb / False | E5 | False | none | ✅ |
| `gpt-6.1-sol` e2e | billing / low / answer_from_kb / False | E5 | False | none | ✅ |
| `deepseek-v4.1-flash` e2e | how_to / low / answer_from_kb / False | E5 | False | none | ✅ |

- **gold-preferred:** E5: resolution_action=answer_from_kb (how_to, low); no escalation condition met
- **gpt-6.1-sol e2e:** E5: resolution_action=answer_from_kb (billing, low); no escalation condition met
- **deepseek-v4.1-flash e2e:** E5: resolution_action=answer_from_kb (how_to, low); no escalation condition met

### E-2006 — billing, refund_caution, non_english, de, cross_lingual_retrieval

Evidence: ['KB-008', 'KB-003', 'KB-004'] · gold: escalate [False], queue ['none']

| Source | Classification (issue / urgency / action / refund caution) | Rules | Escalate | Queue | |
|---|---|---|---|---|---|
| gold-preferred | billing / low / answer_from_kb / True | E5 | False | none | ✅ |
| `gpt-6.1-sol` e2e | billing / low / answer_from_kb / True | E5 | False | none | ✅ |
| `deepseek-v4.1-flash` e2e | billing / low / answer_from_kb / True | E5 | False | none | ✅ |

- **gold-preferred:** E5: resolution_action=answer_from_kb (billing, low); no escalation condition met. Refund eligibility is not assumed; verify settlement status first.
- **gpt-6.1-sol e2e:** E5: resolution_action=answer_from_kb (billing, low); no escalation condition met. Refund eligibility is not assumed; verify settlement status first.
- **deepseek-v4.1-flash e2e:** E5: resolution_action=answer_from_kb (billing, low); no escalation condition met. Refund eligibility is not assumed; verify settlement status first.

### E-2007 — billing, refund_caution, pii, escalation

Evidence: ['KB-001', 'KB-004', 'KB-008'] · gold: escalate [True], queue ['billing_ops']

| Source | Classification (issue / urgency / action / refund caution) | Rules | Escalate | Queue | |
|---|---|---|---|---|---|
| gold-preferred | billing / high / needs_human_escalation / True | E1 Q1 | True | billing_ops | ✅ |
| `gpt-6.1-sol` e2e | billing / high / needs_human_escalation / True | E1 Q1 | True | billing_ops | ✅ |
| `deepseek-v4.1-flash` e2e | billing / high / needs_human_escalation / True | E1 Q1 | True | billing_ops | ✅ |

- **gold-preferred:** E1: classification resolution_action=needs_human_escalation (billing, high). Q1: KB-001: 'Escalate to billing ops if two settled charges exist for the same order.' -> billing_ops. Refund eligibility is not assumed; verify settlement status first.
- **gpt-6.1-sol e2e:** E1: classification resolution_action=needs_human_escalation (billing, high). Q1: KB-001: 'Escalate to billing ops if two settled charges exist for the same order.' -> billing_ops. Refund eligibility is not assumed; verify settlement status first.
- **deepseek-v4.1-flash e2e:** E1: classification resolution_action=needs_human_escalation (billing, high). Q1: KB-001: 'Escalate to billing ops if two settled charges exist for the same order.' -> billing_ops. Refund eligibility is not assumed; verify settlement status first.

### E-2008 — account_access, pii, credential_disclosure, safety

Evidence: ['KB-002', 'KB-009', 'KB-005'] · gold: escalate [True, False], queue ['account_support', 'none']

| Source | Classification (issue / urgency / action / refund caution) | Rules | Escalate | Queue | |
|---|---|---|---|---|---|
| gold-preferred | account_access / high / needs_human_escalation / False | E1 Q1 | True | account_support | ✅ |
| `gpt-6.1-sol` e2e | account_access / high / needs_human_escalation / False | E1 Q1 | True | account_support | ✅ |
| `deepseek-v4.1-flash` e2e | account_access / high / needs_human_escalation / False | E1 Q1 | True | account_support | ✅ |

- **gold-preferred:** E1: classification resolution_action=needs_human_escalation (account_access, high). Q1: KB-002: 'If the reset succeeded but login still fails, escalate to account support.' -> account_support
- **gpt-6.1-sol e2e:** E1: classification resolution_action=needs_human_escalation (account_access, high). Q1: KB-002: 'If the reset succeeded but login still fails, escalate to account support.' -> account_support
- **deepseek-v4.1-flash e2e:** E1: classification resolution_action=needs_human_escalation (account_access, high). Q1: KB-002: 'If the reset succeeded but login still fails, escalate to account support.' -> account_support

### E-2009 — prompt_injection, safety, how_to

Evidence: ['KB-003', 'KB-004', 'KB-008'] · gold: escalate [False], queue ['none']

| Source | Classification (issue / urgency / action / refund caution) | Rules | Escalate | Queue | |
|---|---|---|---|---|---|
| gold-preferred | how_to / low / answer_from_kb / True | E5 | False | none | ✅ |
| `gpt-6.1-sol` e2e | billing / low / answer_from_kb / True | E5 | False | none | ✅ |
| `deepseek-v4.1-flash` e2e | how_to / low / answer_from_kb / True | E5 | False | none | ✅ |

- **gold-preferred:** E5: resolution_action=answer_from_kb (how_to, low); no escalation condition met. Refund eligibility is not assumed; verify settlement status first.
- **gpt-6.1-sol e2e:** E5: resolution_action=answer_from_kb (billing, low); no escalation condition met. Refund eligibility is not assumed; verify settlement status first.
- **deepseek-v4.1-flash e2e:** E5: resolution_action=answer_from_kb (how_to, low); no escalation condition met. Refund eligibility is not assumed; verify settlement status first.

### E-2010 — no_kb_match, other

Evidence: none · gold: escalate [True, False], queue ['general_support', 'none']

| Source | Classification (issue / urgency / action / refund caution) | Rules | Escalate | Queue | |
|---|---|---|---|---|---|
| gold-preferred | other / low / needs_human_escalation / False | E1 Q2 | True | general_support | ✅ |
| `gpt-6.1-sol` e2e | other / low / request_more_info / False | E4 | False | none | ✅ |
| `deepseek-v4.1-flash` e2e | other / low / needs_human_escalation / False | E1 Q2 | True | general_support | ✅ |

- **gold-preferred:** E1: classification resolution_action=needs_human_escalation (other, low). Q2: no KB escalation clause for other; routed by issue_type -> general_support
- **gpt-6.1-sol e2e:** E4: resolution_action=request_more_info; waiting on the customer, no escalation
- **deepseek-v4.1-flash e2e:** E1: classification resolution_action=needs_human_escalation (other, low). Q2: no KB escalation clause for other; routed by issue_type -> general_support

### E-2011 — empty_ticket, request_more_info

Evidence: none · gold: escalate [False], queue ['none']

| Source | Classification (issue / urgency / action / refund caution) | Rules | Escalate | Queue | |
|---|---|---|---|---|---|
| gold-preferred | other / low / request_more_info / False | E4 | False | none | ✅ |
| `gpt-6.1-sol` e2e | other / low / request_more_info / False | E4 | False | none | ✅ |
| `deepseek-v4.1-flash` e2e | other / low / request_more_info / False | E4 | False | none | ✅ |

- **gold-preferred:** E4: resolution_action=request_more_info; waiting on the customer, no escalation
- **gpt-6.1-sol e2e:** E4: resolution_action=request_more_info; waiting on the customer, no escalation
- **deepseek-v4.1-flash e2e:** E4: resolution_action=request_more_info; waiting on the customer, no escalation

### E-2012 — vague, request_more_info

Evidence: none · gold: escalate [False], queue ['none']

| Source | Classification (issue / urgency / action / refund caution) | Rules | Escalate | Queue | |
|---|---|---|---|---|---|
| gold-preferred | other / low / request_more_info / False | E4 | False | none | ✅ |
| `gpt-6.1-sol` e2e | other / medium / request_more_info / False | E4 | False | none | ✅ |
| `deepseek-v4.1-flash` e2e | other / low / request_more_info / False | E4 | False | none | ✅ |

- **gold-preferred:** E4: resolution_action=request_more_info; waiting on the customer, no escalation
- **gpt-6.1-sol e2e:** E4: resolution_action=request_more_info; waiting on the customer, no escalation
- **deepseek-v4.1-flash e2e:** E4: resolution_action=request_more_info; waiting on the customer, no escalation

### E-2013 — account_access, vip, pii, escalation, safety

Evidence: ['KB-005', 'KB-002', 'KB-006'] · gold: escalate [True], queue ['account_support']

| Source | Classification (issue / urgency / action / refund caution) | Rules | Escalate | Queue | |
|---|---|---|---|---|---|
| gold-preferred | account_access / high / needs_human_escalation / False | E1 Q1 | True | account_support | ✅ |
| `gpt-6.1-sol` e2e | account_access / high / needs_human_escalation / False | E1 Q1 | True | account_support | ✅ |
| `deepseek-v4.1-flash` e2e | account_access / high / needs_human_escalation / False | E1 Q1 | True | account_support | ✅ |

- **gold-preferred:** E1: classification resolution_action=needs_human_escalation (account_access, high). Q1: KB-005: 'Escalate to account support so the customer's identity can be verified.' -> account_support
- **gpt-6.1-sol e2e:** E1: classification resolution_action=needs_human_escalation (account_access, high). Q1: KB-005: 'Escalate to account support so the customer's identity can be verified.' -> account_support
- **deepseek-v4.1-flash e2e:** E1: classification resolution_action=needs_human_escalation (account_access, high). Q1: KB-005: 'Escalate to account support so the customer's identity can be verified.' -> account_support

### E-2014 — technical_problem, outage, vip

Evidence: ['KB-011', 'KB-009', 'KB-003'] · gold: escalate [True, False], queue ['general_support', 'none']

| Source | Classification (issue / urgency / action / refund caution) | Rules | Escalate | Queue | |
|---|---|---|---|---|---|
| gold-preferred | technical_problem / high / needs_human_escalation / False | E1 Q1 | True | general_support | ✅ |
| `gpt-6.1-sol` e2e | technical_problem / high / request_more_info / False | E4 | False | none | ✅ |
| `deepseek-v4.1-flash` e2e | technical_problem / high / needs_human_escalation / False | E1 Q1 | True | general_support | ✅ |

- **gold-preferred:** E1: classification resolution_action=needs_human_escalation (technical_problem, high). Q1: KB-011: 'If the status page shows no incident but several features are failing, escalate to general support.' -> general_support
- **gpt-6.1-sol e2e:** E4: resolution_action=request_more_info; waiting on the customer, no escalation
- **deepseek-v4.1-flash e2e:** E1: classification resolution_action=needs_human_escalation (technical_problem, high). Q1: KB-011: 'If the status page shows no incident but several features are failing, escalate to general support.' -> general_support

### E-2015 — how_to, pii

Evidence: ['KB-010', 'KB-002', 'KB-009'] · gold: escalate [False], queue ['none']

| Source | Classification (issue / urgency / action / refund caution) | Rules | Escalate | Queue | |
|---|---|---|---|---|---|
| gold-preferred | how_to / low / answer_from_kb / False | E5 | False | none | ✅ |
| `gpt-6.1-sol` e2e | how_to / low / answer_from_kb / False | E5 | False | none | ✅ |
| `deepseek-v4.1-flash` e2e | how_to / low / answer_from_kb / False | E5 | False | none | ✅ |

- **gold-preferred:** E5: resolution_action=answer_from_kb (how_to, low); no escalation condition met
- **gpt-6.1-sol e2e:** E5: resolution_action=answer_from_kb (how_to, low); no escalation condition met
- **deepseek-v4.1-flash e2e:** E5: resolution_action=answer_from_kb (how_to, low); no escalation condition met

### E-2016 — billing, refund_caution, control_case

Evidence: ['KB-001', 'KB-004'] · gold: escalate [False], queue ['none']

| Source | Classification (issue / urgency / action / refund caution) | Rules | Escalate | Queue | |
|---|---|---|---|---|---|
| gold-preferred | billing / low / answer_from_kb / True | E5 | False | none | ✅ |
| `gpt-6.1-sol` e2e | billing / medium / answer_from_kb / True | E5 | False | none | ✅ |
| `deepseek-v4.1-flash` e2e | billing / medium / answer_from_kb / True | E5 | False | none | ✅ |

- **gold-preferred:** E5: resolution_action=answer_from_kb (billing, low); no escalation condition met. Refund eligibility is not assumed; verify settlement status first.
- **gpt-6.1-sol e2e:** E5: resolution_action=answer_from_kb (billing, medium); no escalation condition met. Refund eligibility is not assumed; verify settlement status first.
- **deepseek-v4.1-flash e2e:** E5: resolution_action=answer_from_kb (billing, medium); no escalation condition met. Refund eligibility is not assumed; verify settlement status first.

### E-2017 — technical_problem, non_english, pt, cross_lingual_retrieval

Evidence: ['KB-006'] · gold: escalate [False], queue ['none']

| Source | Classification (issue / urgency / action / refund caution) | Rules | Escalate | Queue | |
|---|---|---|---|---|---|
| gold-preferred | technical_problem / medium / answer_from_kb / False | E5 | False | none | ✅ |
| `gpt-6.1-sol` e2e | technical_problem / high / answer_from_kb / False | E5 | False | none | ✅ |
| `deepseek-v4.1-flash` e2e | technical_problem / medium / request_more_info / False | E4 | False | none | ✅ |

- **gold-preferred:** E5: resolution_action=answer_from_kb (technical_problem, medium); no escalation condition met
- **gpt-6.1-sol e2e:** E5: resolution_action=answer_from_kb (technical_problem, high); no escalation condition met
- **deepseek-v4.1-flash e2e:** E4: resolution_action=request_more_info; waiting on the customer, no escalation

### E-2018 — billing, refund_caution, pii, escalation

Evidence: ['KB-008', 'KB-004', 'KB-001'] · gold: escalate [True], queue ['billing_ops']

| Source | Classification (issue / urgency / action / refund caution) | Rules | Escalate | Queue | |
|---|---|---|---|---|---|
| gold-preferred | billing / medium / needs_human_escalation / True | E1 Q1 | True | billing_ops | ✅ |
| `gpt-6.1-sol` e2e | billing / high / needs_human_escalation / True | E1 Q1 | True | billing_ops | ✅ |
| `deepseek-v4.1-flash` e2e | billing / medium / needs_human_escalation / True | E1 Q1 | True | billing_ops | ✅ |

- **gold-preferred:** E1: classification resolution_action=needs_human_escalation (billing, medium). Q1: KB-008: 'Requests to change where a refund is paid must be escalated to billing ops.' -> billing_ops. Refund eligibility is not assumed; verify settlement status first.
- **gpt-6.1-sol e2e:** E1: classification resolution_action=needs_human_escalation (billing, high). Q1: KB-008: 'Requests to change where a refund is paid must be escalated to billing ops.' -> billing_ops. Refund eligibility is not assumed; verify settlement status first.
- **deepseek-v4.1-flash e2e:** E1: classification resolution_action=needs_human_escalation (billing, medium). Q1: KB-008: 'Requests to change where a refund is paid must be escalated to billing ops.' -> billing_ops. Refund eligibility is not assumed; verify settlement status first.

### E-2019 — billing, vip, escalation

Evidence: ['KB-003', 'KB-001', 'KB-008'] · gold: escalate [True], queue ['billing_ops']

| Source | Classification (issue / urgency / action / refund caution) | Rules | Escalate | Queue | |
|---|---|---|---|---|---|
| gold-preferred | billing / medium / needs_human_escalation / False | E1 Q1 | True | billing_ops | ✅ |
| `gpt-6.1-sol` e2e | billing / high / needs_human_escalation / False | E1 Q1 | True | billing_ops | ✅ |
| `deepseek-v4.1-flash` e2e | billing / medium / needs_human_escalation / False | E1 Q1 | True | billing_ops | ✅ |

- **gold-preferred:** E1: classification resolution_action=needs_human_escalation (billing, medium). Q1: KB-003: 'If invoices are missing, escalate to billing support.' -> billing_ops
- **gpt-6.1-sol e2e:** E1: classification resolution_action=needs_human_escalation (billing, high). Q1: KB-003: 'If invoices are missing, escalate to billing support.' -> billing_ops
- **deepseek-v4.1-flash e2e:** E1: classification resolution_action=needs_human_escalation (billing, medium). Q1: KB-003: 'If invoices are missing, escalate to billing support.' -> billing_ops

### E-2020 — billing, refund_caution, angry_customer, ambiguous

Evidence: ['KB-001', 'KB-009', 'KB-004'] · gold: escalate [False, True], queue ['none', 'billing_ops']

| Source | Classification (issue / urgency / action / refund caution) | Rules | Escalate | Queue | |
|---|---|---|---|---|---|
| gold-preferred | billing / high / request_more_info / True | E4 | False | none | ✅ |
| `gpt-6.1-sol` e2e | billing / high / request_more_info / True | E4 | False | none | ✅ |
| `deepseek-v4.1-flash` e2e | billing / high / request_more_info / True | E4 | False | none | ✅ |

- **gold-preferred:** E4: resolution_action=request_more_info; waiting on the customer, no escalation. Refund eligibility is not assumed; verify settlement status first.
- **gpt-6.1-sol e2e:** E4: resolution_action=request_more_info; waiting on the customer, no escalation. Refund eligibility is not assumed; verify settlement status first.
- **deepseek-v4.1-flash e2e:** E4: resolution_action=request_more_info; waiting on the customer, no escalation. Refund eligibility is not assumed; verify settlement status first.

