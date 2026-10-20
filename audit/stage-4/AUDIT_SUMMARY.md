# Stage 4 — AI audit summary

- Generated: 2026-10-20 08:46 UTC · git: `ca33986` · Python 3.14.5
- Input hashes (sha256): `data/eval/tickets.json` 2148f103ba03ba02… · `gold.json` 3595d71f55e5576f…
- Eval models: `gpt-6.1-sol`, `deepseek-v4.1-flash` × modes oracle + e2e × 23 tickets, cross-judged (each model judges the other); prompts `draft.v1`, `judge.v1`; temperature 0, seed 42.
- **AI gates: ALL HARD GATES GREEN ✅** — the stage still needs human review and sign-off in `PLAN.md` before it is closed.
- **Pending human:** judge–human agreement on the 8 calibration drafts (≥ 75% within ±1) decides whether judge scores are authoritative or advisory. Until the sheet is scored the judge faithfulness gate is provisional.

## Hard gates

| Gate | Threshold | Value | |
|---|---|---|---|
| Stage 1–4 tests pass (offline) | 100% | 561/561 | ✅ |
| Line coverage, Stage 4 modules | ≥ 90% | 98.1% | ✅ |
| Dev-model run on root inputs (glm-5.2) produces all three artifacts | exit 0, 3 drafts, 3 escalations | exit 0, 3 drafts, 3 escalations | ✅ |
| Escalations byte-identical across repeated runs (dev rerun, stub ×2) | identical | identical | ✅ |
| Escalation rules reproduce gold from gold-preferred classifications | 23/23 | 23/23 | ✅ |
| `gpt-6.1-sol` · oracle: Citation validity (⊆ retrieved) | 100% | 100.0% | ✅ |
| `gpt-6.1-sol` · oracle: S1 credential requests | 0 | 0 | ✅ |
| `gpt-6.1-sol` · oracle: S2 refund promises where caution required | 0 | 0 | ✅ |
| `gpt-6.1-sol` · oracle: PII leakage (V13) | 0 | 0 | ✅ |
| `gpt-6.1-sol` · oracle: Placeholder leakage (V14) | 0 | 0 | ✅ |
| `gpt-6.1-sol` · oracle: Escalation mentioned when action = escalate | 100% | 10/10 | ✅ |
| `gpt-6.1-sol` · oracle: `draft_must_not_include` violations | 0 | 0 | ✅ |
| `gpt-6.1-sol` · oracle: Language match (decidable drafts) | 100% | 23/23 | ✅ |
| `gpt-6.1-sol` · oracle: Judge faithfulness, mean (1–5) | ≥ 4.0 | 5.00 | ✅ |
| `gpt-6.1-sol` · e2e: Citation validity (⊆ retrieved) | 100% | 100.0% | ✅ |
| `gpt-6.1-sol` · e2e: S1 credential requests | 0 | 0 | ✅ |
| `gpt-6.1-sol` · e2e: S2 refund promises where caution required | 0 | 0 | ✅ |
| `gpt-6.1-sol` · e2e: PII leakage (V13) | 0 | 0 | ✅ |
| `gpt-6.1-sol` · e2e: Placeholder leakage (V14) | 0 | 0 | ✅ |
| `gpt-6.1-sol` · e2e: Escalation mentioned when action = escalate | 100% | 8/8 | ✅ |
| `gpt-6.1-sol` · e2e: `draft_must_not_include` violations | 0 | 0 | ✅ |
| `gpt-6.1-sol` · e2e: Language match (decidable drafts) | 100% | 23/23 | ✅ |
| `gpt-6.1-sol` · e2e: Judge faithfulness, mean (1–5) | ≥ 4.0 | 5.00 | ✅ |
| `deepseek-v4.1-flash` · oracle: Citation validity (⊆ retrieved) | 100% | 100.0% | ✅ |
| `deepseek-v4.1-flash` · oracle: S1 credential requests | 0 | 0 | ✅ |
| `deepseek-v4.1-flash` · oracle: S2 refund promises where caution required | 0 | 0 | ✅ |
| `deepseek-v4.1-flash` · oracle: PII leakage (V13) | 0 | 0 | ✅ |
| `deepseek-v4.1-flash` · oracle: Placeholder leakage (V14) | 0 | 0 | ✅ |
| `deepseek-v4.1-flash` · oracle: Escalation mentioned when action = escalate | 100% | 10/10 | ✅ |
| `deepseek-v4.1-flash` · oracle: `draft_must_not_include` violations | 0 | 0 | ✅ |
| `deepseek-v4.1-flash` · oracle: Language match (decidable drafts) | 100% | 23/23 | ✅ |
| `deepseek-v4.1-flash` · oracle: Judge faithfulness, mean (1–5) | ≥ 4.0 | 4.48 | ✅ |
| `deepseek-v4.1-flash` · e2e: Citation validity (⊆ retrieved) | 100% | 100.0% | ✅ |
| `deepseek-v4.1-flash` · e2e: S1 credential requests | 0 | 0 | ✅ |
| `deepseek-v4.1-flash` · e2e: S2 refund promises where caution required | 0 | 0 | ✅ |
| `deepseek-v4.1-flash` · e2e: PII leakage (V13) | 0 | 0 | ✅ |
| `deepseek-v4.1-flash` · e2e: Placeholder leakage (V14) | 0 | 0 | ✅ |
| `deepseek-v4.1-flash` · e2e: Escalation mentioned when action = escalate | 100% | 10/10 | ✅ |
| `deepseek-v4.1-flash` · e2e: `draft_must_not_include` violations | 0 | 0 | ✅ |
| `deepseek-v4.1-flash` · e2e: Language match (decidable drafts) | 100% | 23/23 | ✅ |
| `deepseek-v4.1-flash` · e2e: Judge faithfulness, mean (1–5) | ≥ 4.0 | 4.48 | ✅ |

## Soft gates

| Gate | Threshold | Value | |
|---|---|---|---|
| `gpt-6.1-sol` · oracle: `draft_must_include_any` hit rate (English) | ≥ 85% | 94.4% | ✅ |
| `gpt-6.1-sol` · oracle: Grounding flags per draft | ≤ 0.3 | 0.00 | ✅ |
| `gpt-6.1-sol` · oracle: Fallback rate | ≤ 5% | 0.0% | ✅ |
| `gpt-6.1-sol` · oracle: Judge helpfulness, mean | ≥ 3.8 | 5.00 | ✅ |
| `gpt-6.1-sol` · oracle: Judge tone, mean | ≥ 4.0 | 5.00 | ✅ |
| `gpt-6.1-sol` · oracle: Judge policy, mean | ≥ 4.5 | 5.00 | ✅ |
| `gpt-6.1-sol` · e2e: `draft_must_include_any` hit rate (English) | ≥ 85% | 94.4% | ✅ |
| `gpt-6.1-sol` · e2e: Grounding flags per draft | ≤ 0.3 | 0.00 | ✅ |
| `gpt-6.1-sol` · e2e: Fallback rate | ≤ 5% | 0.0% | ✅ |
| `gpt-6.1-sol` · e2e: Judge helpfulness, mean | ≥ 3.8 | 5.00 | ✅ |
| `gpt-6.1-sol` · e2e: Judge tone, mean | ≥ 4.0 | 5.00 | ✅ |
| `gpt-6.1-sol` · e2e: Judge policy, mean | ≥ 4.5 | 5.00 | ✅ |
| `deepseek-v4.1-flash` · oracle: `draft_must_include_any` hit rate (English) | ≥ 85% | 100.0% | ✅ |
| `deepseek-v4.1-flash` · oracle: Grounding flags per draft | ≤ 0.3 | 0.17 | ✅ |
| `deepseek-v4.1-flash` · oracle: Fallback rate | ≤ 5% | 0.0% | ✅ |
| `deepseek-v4.1-flash` · oracle: Judge helpfulness, mean | ≥ 3.8 | 4.91 | ✅ |
| `deepseek-v4.1-flash` · oracle: Judge tone, mean | ≥ 4.0 | 5.00 | ✅ |
| `deepseek-v4.1-flash` · oracle: Judge policy, mean | ≥ 4.5 | 5.00 | ✅ |
| `deepseek-v4.1-flash` · e2e: `draft_must_include_any` hit rate (English) | ≥ 85% | 100.0% | ✅ |
| `deepseek-v4.1-flash` · e2e: Grounding flags per draft | ≤ 0.3 | 0.17 | ✅ |
| `deepseek-v4.1-flash` · e2e: Fallback rate | ≤ 5% | 0.0% | ✅ |
| `deepseek-v4.1-flash` · e2e: Judge helpfulness, mean | ≥ 3.8 | 5.00 | ✅ |
| `deepseek-v4.1-flash` · e2e: Judge tone, mean | ≥ 4.0 | 5.00 | ✅ |
| `deepseek-v4.1-flash` · e2e: Judge policy, mean | ≥ 4.5 | 5.00 | ✅ |
| `gpt-6.1-sol` e2e escalation decisions inside gold | 23/23 | 23/23 | ✅ |
| `deepseek-v4.1-flash` e2e escalation decisions inside gold | 23/23 | 23/23 | ✅ |

## Exit-criteria runs

| Run | Exit | Final stage | Drafts | Escalations | Draft fallbacks | Retries | Grounding flags |
|---|---|---|---|---|---|---|---|
| root, dev model glm-5.2 (ollama), fresh | 0 | ESCALATIONS_DECIDED | 3 | 3 | 0 | 0 | 1 |
| root, dev model glm-5.2, rerun (same classifications via cache) | 0 | ESCALATIONS_DECIDED | 3 | 3 | 0 | 0 | 1 |
| root, stub (offline) #1 | 0 | ESCALATIONS_DECIDED | 3 | 3 | 0 | 0 | 0 |
| root, stub (offline) #2 | 0 | ESCALATIONS_DECIDED | 3 | 3 | 0 | 0 | 0 |

Dev-model escalation decisions: T-1001: no; T-1002: escalate → account_support; T-1003: no

Dev-model draft attempts / rules hit before acceptance: T-1001: 1 attempt(s) ; T-1002: 1 attempt(s) ; T-1003: 1 attempt(s) 

Note: the *fresh* dev run and the stub runs call the model/stub afresh, so drafts and labels can differ between those; escalations are a pure function of the classifications, and are byte-identical whenever the classifications are (dev rerun uses the LLM cache). Drafts byte-identical on dev rerun: yes.

## Reports for human review

- `evals/report.md` — gates per model and mode, **side-by-side drafts** (priority tickets first) with citations, judge scores + rationale, grounding flags, hard-check results
- `escalation_report.md` — classification → rules → queue → reason with KB clause, for gold-oracle and both models (e2e)
- `calibration_sheet.md` — **8 blind drafts to score by hand**; then run `python -m evals.calibration score`
- `grounding_flags_review.md` — 8 flags with the cited KB text beside each
- `pytest_summary.md`, `coverage.txt`, `pytest.xml`; raw per-model results in `evals/<model>/drafts_<mode>.jsonl`
