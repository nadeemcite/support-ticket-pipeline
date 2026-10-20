# Stage 5 — validation summary

`validation_report.json` rendered for the two real runs. Raw files: see `evals/raw/` (git-ignored) and the stub-run examples in the tests.

## Root inputs, real run (`glm-5.2`, embeddings)

**PASS** — 13 passed, 0 failed, 1 warnings, 3 tickets

| Check | Name | Status | Details |
|---|---|---|---|
| V01 | required_artifacts_exist | pass | — |
| V02 | json_parses | pass | — |
| V03 | schemas_match | pass | — |
| V04 | ticket_coverage | pass | — |
| V05 | classification_in_taxonomy | pass | — |
| V06 | retrieval_contract | pass | — |
| V07 | citations_subset_of_retrieved | pass | — |
| V08 | escalation_invariant | pass | — |
| V09 | draft_language_matches_ticket | pass | — |
| V10 | no_credential_requests_or_refund_promises | pass | — |
| V11 | escalation_consistency | pass | — |
| V12 | grounding_flags_and_llm_log_coverage | warn | T-1003 unsupported claim (G1): three months |
| V13 | no_pii_leakage | pass | — |
| V14 | no_placeholder_leakage | pass | — |

## Eval set, real run (`gpt-6.1-sol`, embeddings)

**PASS** — 14 passed, 0 failed, 0 warnings, 23 tickets

| Check | Name | Status | Details |
|---|---|---|---|
| V01 | required_artifacts_exist | pass | — |
| V02 | json_parses | pass | — |
| V03 | schemas_match | pass | — |
| V04 | ticket_coverage | pass | — |
| V05 | classification_in_taxonomy | pass | — |
| V06 | retrieval_contract | pass | — |
| V07 | citations_subset_of_retrieved | pass | — |
| V08 | escalation_invariant | pass | — |
| V09 | draft_language_matches_ticket | pass | — |
| V10 | no_credential_requests_or_refund_promises | pass | — |
| V11 | escalation_consistency | pass | — |
| V12 | grounding_flags_and_llm_log_coverage | pass | — |
| V13 | no_pii_leakage | pass | — |
| V14 | no_placeholder_leakage | pass | — |

