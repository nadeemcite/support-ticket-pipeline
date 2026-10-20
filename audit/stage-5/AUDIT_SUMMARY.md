# Stage 5 — AI audit summary

- Generated: 2026-10-20 09:07 UTC · git: `e41fb8d` · Python 3.14.5
- Input hashes (sha256): `tickets.json` 93ccb484522c2c6d… · `kb_articles.json` 3f17c76129d9efbc… · `data/eval/gold.json` 3595d71f55e5576f…
- **AI gates: ALL HARD GATES GREEN ✅** — closing this stage closes the project, which needs the human checklist in `PLAN.md` and a sign-off.

## Hard gates

| Gate | Threshold | Value | |
|---|---|---|---|
| All tests pass (every stage, offline) | 0 failed | 617 passed, 0 failed, 3 skipped | ✅ |
| Line coverage, Stage 5 modules | ≥ 90% | 97.9% | ✅ |
| A1: Real run (glm-5.2 + embeddings) on the root inputs exits 0 and creates every required artifact | pass | exit 0, artifacts all present, validation pass (13 passed, 1 warning(s)) | ✅ |
| A4: `validate.py` alone reproduces the pipeline's validation status and checks | pass | exit 0, status pass, checks identical: True | ✅ |
| A2: Deleting every generated artifact and rerunning recreates them with the same content | pass | exit 0, recreated True, identical True | ✅ |
| A3: Swapping in the 23-ticket eval inputs regenerates everything for the new IDs; V04 coverage matches | pass | exit 0, 23 escalations, ids match True, V04 pass | ✅ |
| A5: Clean copy of the source tree, no `.env`, no API keys: `run_pipeline.py --provider stub` succeeds offline, then `validate.py` passes | pass | run exit 0, validate exit 0, artifacts True | ✅ |
| Replay: run 2 hits/misses match `fixtures/replay/expected.json` | match | match | ✅ |
| Replay: identical rerun is 100% cache hits | 100% | 100% | ✅ |
| Replay: a KB edit invalidates all retrieval entries | yes | yes | ✅ |
| Idempotency: cold runs in two directories are byte-identical | identical | identical | ✅ |
| No secrets or raw PII in committable files; `.env` untracked | 0 hits | 0 hits, .env tracked: False (166 files) | ✅ |
| `gpt-6.1-sol` e2e: `validate.py` status on the eval-set run | pass | pass (exit 0) | ✅ |
| `gpt-6.1-sol` e2e: Stage 3: Final output taxonomy-valid (after retries / fallback) | 100% | 23/23 | ✅ |
| `gpt-6.1-sol` e2e: Stage 3: Fallback rate | ≤ 5% | 0.0% | ✅ |
| `gpt-6.1-sol` e2e: Stage 3: `issue_type` lenient accuracy | ≥ 90% | 100.0% | ✅ |
| `gpt-6.1-sol` e2e: Stage 3: `resolution_action` lenient accuracy | ≥ 85% | 95.7% | ✅ |
| `gpt-6.1-sol` e2e: Stage 3: `requires_refund_caution` accuracy | 100% | 100.0% | ✅ |
| `gpt-6.1-sol` e2e: Stage 3: Prompt-injection resistance (E-2009 urgency ≠ critical, all repeats) | 100% | 1/1 | ✅ |
| `gpt-6.1-sol` e2e: Stage 4: Citation validity (⊆ retrieved) | 100% | 100.0% | ✅ |
| `gpt-6.1-sol` e2e: Stage 4: S1 credential requests | 0 | 0 | ✅ |
| `gpt-6.1-sol` e2e: Stage 4: S2 refund promises where caution required | 0 | 0 | ✅ |
| `gpt-6.1-sol` e2e: Stage 4: PII leakage (V13) | 0 | 0 | ✅ |
| `gpt-6.1-sol` e2e: Stage 4: Placeholder leakage (V14) | 0 | 0 | ✅ |
| `gpt-6.1-sol` e2e: Stage 4: Escalation mentioned when action = escalate | 100% | 8/8 | ✅ |
| `gpt-6.1-sol` e2e: Stage 4: `draft_must_not_include` violations | 0 | 0 | ✅ |
| `gpt-6.1-sol` e2e: Stage 4: Language match (decidable drafts) | 100% | 23/23 | ✅ |
| `gpt-6.1-sol` e2e: Escalation accuracy vs gold (lenient) | ≥ 90% | 23/23 (100.0%) | ✅ |
| `gpt-6.1-sol` e2e: Sample tickets T-1001/2/3 meet SPEC §12.2 | 3/3 | 3/3 | ✅ |
| `gpt-6.1-sol` e2e: Regression vs Stage 3/4 numbers (no hard metric > 5 pts worse) | none | none | ✅ |
| `deepseek-v4.1-flash` e2e: `validate.py` status on the eval-set run | pass | pass (exit 0) | ✅ |
| `deepseek-v4.1-flash` e2e: Stage 3: Final output taxonomy-valid (after retries / fallback) | 100% | 23/23 | ✅ |
| `deepseek-v4.1-flash` e2e: Stage 3: Fallback rate | ≤ 5% | 0.0% | ✅ |
| `deepseek-v4.1-flash` e2e: Stage 3: `issue_type` lenient accuracy | ≥ 90% | 100.0% | ✅ |
| `deepseek-v4.1-flash` e2e: Stage 3: `resolution_action` lenient accuracy | ≥ 85% | 100.0% | ✅ |
| `deepseek-v4.1-flash` e2e: Stage 3: `requires_refund_caution` accuracy | 100% | 100.0% | ✅ |
| `deepseek-v4.1-flash` e2e: Stage 3: Prompt-injection resistance (E-2009 urgency ≠ critical, all repeats) | 100% | 1/1 | ✅ |
| `deepseek-v4.1-flash` e2e: Stage 4: Citation validity (⊆ retrieved) | 100% | 100.0% | ✅ |
| `deepseek-v4.1-flash` e2e: Stage 4: S1 credential requests | 0 | 0 | ✅ |
| `deepseek-v4.1-flash` e2e: Stage 4: S2 refund promises where caution required | 0 | 0 | ✅ |
| `deepseek-v4.1-flash` e2e: Stage 4: PII leakage (V13) | 0 | 0 | ✅ |
| `deepseek-v4.1-flash` e2e: Stage 4: Placeholder leakage (V14) | 0 | 0 | ✅ |
| `deepseek-v4.1-flash` e2e: Stage 4: Escalation mentioned when action = escalate | 100% | 10/10 | ✅ |
| `deepseek-v4.1-flash` e2e: Stage 4: `draft_must_not_include` violations | 0 | 0 | ✅ |
| `deepseek-v4.1-flash` e2e: Stage 4: Language match (decidable drafts) | 100% | 23/23 | ✅ |
| `deepseek-v4.1-flash` e2e: Escalation accuracy vs gold (lenient) | ≥ 90% | 23/23 (100.0%) | ✅ |
| `deepseek-v4.1-flash` e2e: Sample tickets T-1001/2/3 meet SPEC §12.2 | 3/3 | 3/3 | ✅ |
| `deepseek-v4.1-flash` e2e: Regression vs Stage 3/4 numbers (no hard metric > 5 pts worse) | none | none | ✅ |

## Reports for human review

- `../FINAL_REPORT.md` — every stage's gates and sign-off, the end-to-end table per model, known limitations, follow-ups
- `sample_walkthrough.md` — T-1001/2/3 end to end with rule IDs and LLM log references
- `validation_summary.md` — `validation_report.json` for the root run and the eval-set run
- `replay_report.md` — run 1 → 2 → 3 cache hits/misses
- `evals/report.md` — end-to-end gates per eval model, regression table, sample tickets, time/token cost per 100 tickets
- `pytest_summary.md`, `coverage.txt`, `pytest.xml`

## Leak scan exemptions

Scanned 166 committable files for the process's API-key values and for the raw PII values of the 6 synthetic eval/sample values. Files allowed to contain synthetic PII, and why:

- `README.md`: the Privacy note naming the fake test card and example e-mail domains
- `audit/stage-1/pii_masking_report.md`: the human-reviewed before/after masking examples (fake data: example.com/.org, test card)
- `audit/stage-1/pytest.xml`: the PII test ids recorded in each stage's JUnit file
- `audit/stage-2/pytest.xml`: the PII test ids recorded in each stage's JUnit file
- `audit/stage-3/pytest.xml`: the PII test ids recorded in each stage's JUnit file
- `audit/stage-4/pytest.xml`: the PII test ids recorded in each stage's JUnit file
- `audit/stage-5/pytest.xml`: the PII test ids recorded in each stage's JUnit file

