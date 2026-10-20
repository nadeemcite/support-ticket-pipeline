# Stage 1 — AI audit summary

- Generated: 2026-10-20 06:22 UTC · git: `b8cef76` · Python 3.14.5
- Input hashes (sha256): `tickets.json` 93ccb484522c2c6d… · `kb_articles.json` 3f17c76129d9efbc… · `data/eval/tickets.json` 2148f103ba03ba02…
- **AI gates: ALL GREEN ✅** — the stage still needs human review and sign-off in `PLAN.md` before it is closed.

## Hard gates

| Gate | Threshold | Value | |
|---|---|---|---|
| All Stage 1 tests pass | 100% | 237/237 | ✅ |
| Line coverage, Stage 1 modules | ≥ 90% | 98.4% | ✅ |
| Raw-PII hits in eval-set `normalised_tickets.json` | 0 | 0 | ✅ |
| Raw-PII hits in any fixture run's artifacts / manifest | 0 | 0 | ✅ |
| Eval PII types match gold | 23/23 | 23/23 | ✅ |
| Every fixture run ends with the expected exit code | 8/8 | 8/8 | ✅ |

## Evals

None. Stage 1 has no non-deterministic component: no LLM or network call is made (`llm_calls.jsonl` is empty in every run below), so there is nothing to evaluate with the two eval models.

## Exit criteria — pipeline runs on root inputs and every fixture

| Run | tickets | kb | Exit (expected) | Final stage | Accepted | `normalised_tickets.json` | Manifest | Raw-PII leaks |
|---|---|---|---|---|---|---|---|---|
| root | `tickets.json` | `kb_articles.json` | 0 (0) | TICKETS_NORMALISED | 3 | written | written | 0 |
| eval_set | `data/eval/tickets.json` | `data/eval/kb_articles.json` | 0 (0) | TICKETS_NORMALISED | 23 | written | written | 0 |
| edge_cases | `data/fixtures/edge_cases/tickets.json` | `kb_articles.json` | 0 (0) | TICKETS_NORMALISED | 9 | written | written | 0 |
| empty_kb | `tickets.json` | `data/fixtures/empty_kb/kb_articles.json` | 0 (0) | TICKETS_NORMALISED | 3 | written | written | 0 |
| empty_tickets | `data/fixtures/empty_tickets/tickets.json` | `kb_articles.json` | 0 (0) | TICKETS_NORMALISED | 0 | written | written | 0 |
| replay_v2 | `data/fixtures/replay/tickets_v2.json` | `kb_articles.json` | 0 (0) | TICKETS_NORMALISED | 4 | written | written | 0 |
| malformed_invalid_json | `data/fixtures/malformed/invalid_json.txt` | `kb_articles.json` | 2 (2) | FAILED | - | not written | written | 0 |
| malformed_wrong_key | `data/fixtures/malformed/wrong_top_level_key.json` | `kb_articles.json` | 2 (2) | FAILED | - | not written | written | 0 |

Malformed inputs are expected to fail fatally (rule I1, exit 2) while still writing a manifest that records the error.

## Reports for human review

- `pytest_summary.md`, `coverage.txt`, `pytest.xml`
- `pii_masking_report.md` — original vs masked text for every eval ticket, all detector fixtures incl. false-positive guards
- `normalisation_report.md` — edge-case before/after, rejected/duplicate records

## Known issues / notes for the reviewer

- `KB_INDEXED` is a registered **placeholder** in Stage 1 (marked `placeholder: true` in the manifest stage trail); retrieval stages are built in Stage 2. `--until` beyond `TICKETS_NORMALISED` is refused with exit 2.
- The PII hash salt defaults to a constant (`ticket-triage-pii-v1`) so reruns are byte-identical; set `PII_HASH_SALT` in production.
- Credential detection is pattern-based (keyword + `is`/`:`/…); a password disclosed without a keyword (e.g. "it's hunter2") is not detected. Documented as a limitation in SPEC §7.6.
