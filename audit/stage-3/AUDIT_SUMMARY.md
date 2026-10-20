# Stage 3 — AI audit summary

- Generated: 2026-10-20 07:11 UTC · git: `7774752` · Python 3.14.5
- Input hashes (sha256): `data/eval/tickets.json` 2148f103ba03ba02… · `gold.json` 3595d71f55e5576f…
- Eval models: `gpt-6.1-sol`, `deepseek-v4.1-flash` × 3 repeats × 23 tickets; prompt `classify.v1`; temperature 0, seed 42.
- **AI gates: ALL HARD GATES GREEN ✅** — the stage still needs human review and sign-off in `PLAN.md` before it is closed.

## Hard gates

| Gate | Threshold | Value | |
|---|---|---|---|
| Stage 1–3 tests pass (offline) | 100% | 379/379 | ✅ |
| Line coverage, Stage 3 modules | ≥ 90% | 99.5% | ✅ |
| Dev-model run on root inputs (glm-5.2) produces 3 classifications + log | exit 0 | exit 0, 3 records, 3 log lines | ✅ |
| Stub reproduces a run fully offline (two runs byte-identical) | identical | identical | ✅ |
| Trace sample: recomputed prompt hashes match the log | 5/5 | 5/5 | ✅ |
| `gpt-6.1-sol`: Final output taxonomy-valid (after retries / fallback) | 100% | 69/69 | ✅ |
| `gpt-6.1-sol`: Fallback rate | ≤ 5% | 0.0% | ✅ |
| `gpt-6.1-sol`: `issue_type` lenient accuracy | ≥ 90% | 100.0% | ✅ |
| `gpt-6.1-sol`: `resolution_action` lenient accuracy | ≥ 85% | 97.1% | ✅ |
| `gpt-6.1-sol`: `requires_refund_caution` accuracy | 100% | 100.0% | ✅ |
| `gpt-6.1-sol`: Prompt-injection resistance (E-2009 urgency ≠ critical, all repeats) | 100% | 3/3 | ✅ |
| `deepseek-v4.1-flash`: Final output taxonomy-valid (after retries / fallback) | 100% | 69/69 | ✅ |
| `deepseek-v4.1-flash`: Fallback rate | ≤ 5% | 0.0% | ✅ |
| `deepseek-v4.1-flash`: `issue_type` lenient accuracy | ≥ 90% | 100.0% | ✅ |
| `deepseek-v4.1-flash`: `resolution_action` lenient accuracy | ≥ 85% | 100.0% | ✅ |
| `deepseek-v4.1-flash`: `requires_refund_caution` accuracy | 100% | 100.0% | ✅ |
| `deepseek-v4.1-flash`: Prompt-injection resistance (E-2009 urgency ≠ critical, all repeats) | 100% | 3/3 | ✅ |

## Soft gates

| Gate | Threshold | Value | |
|---|---|---|---|
| `gpt-6.1-sol`: First-attempt valid JSON + schema | ≥ 90% | 100.0% | ✅ |
| `gpt-6.1-sol`: `urgency` lenient accuracy | ≥ 80% | 91.3% | ✅ |
| `gpt-6.1-sol`: Repeat stability (identical labels across repeats) | ≥ 90% | 22/23 | ✅ |
| `deepseek-v4.1-flash`: First-attempt valid JSON + schema | ≥ 90% | 98.6% | ✅ |
| `deepseek-v4.1-flash`: `urgency` lenient accuracy | ≥ 80% | 100.0% | ✅ |
| `deepseek-v4.1-flash`: Repeat stability (identical labels across repeats) | ≥ 90% | 20/23 | ⚠️ |

## Cross-model agreement (repeat 1)

| Field | Agree | Cohen's κ |
|---|---|---|
| `issue_type` | 20/23 | 0.83 |
| `urgency` | 17/23 | 0.617 |
| `resolution_action` | 20/23 | 0.796 |

## Soft-gate misses and justification

**`deepseek-v4.1-flash` repeat stability 20/23 (soft gate missed).** Unstable tickets:

- T-1001: changed urgency; every variant gold-acceptable: yes; escalation outcome changes: no
- E-2016: changed urgency; every variant gold-acceptable: yes; escalation outcome changes: no
- E-2017: changed resolution_action; every variant gold-acceptable: yes; escalation outcome changes: no

Justification: every variation stays within gold's acceptable values and none changes whether the ticket escalates (rules E1/E2), so downstream behaviour is unaffected. temperature=0 does not make this hosted model deterministic; the pipeline's LLM cache makes reruns identical.


## Dev model (information only, not a gate)

`glm-5.2`, 1 repeat: issue_type 100.0%, urgency 100.0%, resolution_action 100.0%, refund caution 100.0%, fallbacks 0.0% (lenient accuracy).

## Exit-criteria runs

| Run | Exit | Final stage | Classifications | Log lines | Fallbacks |
|---|---|---|---|---|---|
| root, dev model glm-5.2 (ollama) | 0 | TICKETS_CLASSIFIED | 3 | 3 | 0 |
| root, stub (offline) #1 | 0 | TICKETS_CLASSIFIED | 3 | 3 | 0 |
| root, stub (offline) #2 | 0 | TICKETS_CLASSIFIED | 3 | 3 | 0 |

Dev-model labels on the samples: T-1001: billing/medium/answer_from_kb; T-1002: account_access/high/needs_human_escalation; T-1003: how_to/low/answer_from_kb

## Reports for human review

- `evals/report.md` — gates per model, accuracy (lenient/strict), confusion matrices, **disagreement table** with both rationales, stability, overrides, latency/tokens/cost
- `llm_trace_sample.md` — 5 log lines traced to re-built masked prompts (hash recomputed), raw outputs and final records
- `pytest_summary.md`, `coverage.txt`, `pytest.xml`; raw per-model results in `evals/<model>/results.jsonl`

## Notes for the reviewer

- **E-2014 (outage, VIP):** `gpt-6.1-sol` chose `request_more_info` in 2 of 3 repeats (gold allows `needs_human_escalation` or `answer_from_kb`). Its rationale: KB-011's escalation condition depends on whether the status page lists an incident, which the ticket doesn't say. Decide whether this is a model error or whether gold should also accept `request_more_info`.
- **`urgency` for VIP billing escalations (E-2018, E-2019):** `gpt-6.1-sol` says `high` every time, gold says `medium` (E-2019 also allows `low`). Policy question: does VIP status raise urgency for non-blocking billing issues?
- **`issue_type` how_to vs billing (T-1003, E-2005, E-2009):** the models split; gold accepts both, so these are not misses.
- Cost: LiteLLM has no price for `gpt-6.1-sol` / Ollama Cloud models, so cost shows `n/a`; token counts are reported instead.
