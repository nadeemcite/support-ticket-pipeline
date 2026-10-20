# Final report — support ticket triage pipeline

Generated 2026-10-20 from `audit/stage-*/`. The stage reports remain the evidence; this page rolls them up.

## 1. What was built

A replayable batch pipeline: `tickets.json` + `kb_articles.json` → PII masking → top-3 KB retrieval → LLM classification → grounded LLM draft → rule-based escalation → V01–V14 validation. Only classification and drafting call an LLM; everything else is deterministic Python. Re-running regenerates every artifact; the cache only skips computation.

## 2. Stage status

| Stage | Name | Status |
|---|---|---|
| 0 | Plan approval (this document + data files) | ☑ Closed (2026-10-20) · `stage-0-closed` |
| 1 | Foundations: config, schemas, loading, normalisation, **PII**, stage machine | ☑ Closed (2026-10-20) · `stage-1-closed` |
| 2 | Retrieval & evidence | ☑ Closed (2026-10-20) · `stage-2-closed` |
| 3 | LLM layer & classification | ☑ Closed (2026-10-20) · `stage-3-closed` |
| 4 | Drafting, guards, grounding & escalation | ☑ Closed (2026-10-20) · `stage-4-closed` |
| 5 | Validation, orchestration, replay & **project closure** | ☑ Closed (2026-10-20) |

Stage 5 was closed on 2026-10-20 on the reviewer's instruction; the agent completed the checklist (see the sign-off notes in `PLAN.md`).

## 3. Gates by stage (AI audit)

| Stage | Result | Source |
|---|---|---|
| 1 | ALL GREEN ✅ | `audit/stage-1/AUDIT_SUMMARY.md` |
| 2 | ALL HARD GATES GREEN ✅ | `audit/stage-2/AUDIT_SUMMARY.md` |
| 3 | ALL HARD GATES GREEN ✅ | `audit/stage-3/AUDIT_SUMMARY.md` |
| 4 | ALL HARD GATES GREEN ✅ | `audit/stage-4/AUDIT_SUMMARY.md` |
| 5 | ALL HARD GATES GREEN ✅ | `audit/stage-5/AUDIT_SUMMARY.md` |

## 4. Acceptance criteria (SPEC §12.1)

| | Criterion | Result |
|---|---|---|
| A1 | Real run (glm-5.2 + embeddings) on the root inputs exits 0 and creates every required artifact | ✅ exit 0, artifacts all present, validation pass (13 passed, 1 warning(s)) |
| A2 | Deleting every generated artifact and rerunning recreates them with the same content | ✅ exit 0, recreated True, identical True |
| A3 | Swapping in the 23-ticket eval inputs regenerates everything for the new IDs; V04 coverage matches | ✅ exit 0, 23 escalations, ids match True, V04 pass |
| A4 | `validate.py` alone reproduces the pipeline's validation status and checks | ✅ exit 0, status pass, checks identical: True |
| A5 | Clean copy of the source tree, no `.env`, no API keys: `run_pipeline.py --provider stub` succeeds offline, then `validate.py` passes | ✅ run exit 0, validate exit 0, artifacts True |

## 5. End-to-end results on the eval set (23 tickets, real pipeline, both eval models)

| Metric | `gpt-6.1-sol` | `deepseek-v4.1-flash` |
|---|---|---|
| Validation | pass (14 passed, 0 warning(s)) | pass (13 passed, 1 warning(s)) |
| `issue_type` / `resolution_action` / `urgency` (lenient) | 100% / 96% / 91% | 100% / 100% / 100% |
| Escalation vs gold | 23/23 | 23/23 |
| Sample tickets T-1001/2/3 (SPEC §12.2) | 3/3 | 3/3 |
| Classification / draft fallbacks | 0 / 0 | 0 / 0 |
| Grounding flags | 0 | 6 |
| Time per 100 tickets (uncached) | 942.2 s | 547.4 s |
| Tokens per 100 tickets (prompt / completion) | 212817 / 25296 | 191483 / 54135 |
| Cost per 100 tickets | n/a — LiteLLM has no price for these models |

Full tables: `audit/stage-5/evals/report.md`.

## 6. Known limitations (please read before accepting)

1. **Small evaluation set.** 23 tickets and an 11-article KB. Percentages move by 4 points per ticket; the gates show the pipeline behaves on these cases, not that it generalises. Thresholds such as the retrieval `min_score` were tuned on this same set, so those numbers are optimistic.
2. **The LLM judge was never calibrated against a human.** Stage 4 closed without the human calibration sheet. The sheet that exists (`audit/stage-4/calibration_sheet.md`) was scored by an AI agent and says so at the top; its 100% agreement is AI-vs-AI and is not human calibration, even though `calibration_result.json` labels the judge "authoritative" mechanically. Treat every judge score as advisory. The judge was also lenient on `gpt-6.1-sol` drafts (near-5 on every criterion). Deterministic checks and the escalation rules do not depend on it.
3. **Heuristic guards.** S1/S2/S3, the grounding guard (G1–G3) and the language check are regexes and word lists. They cover English with es/fr/de/pt equivalents; other languages rely on the LLM instruction plus the English patterns. Each had false positives found and fixed during the project (see Stage 4 notes), so more will exist.
4. **Grounding flags never block.** A draft can contain an unsupported claim and still ship; the flag appears in `grounding_flags.json` and as a V12 warning. The 8 Stage 4 flags were not individually triaged as true/false positives.
5. **Open gold-policy questions** from Stage 3: whether `request_more_info` is acceptable for an outage ticket (E-2014) and whether VIP status raises urgency for non-blocking billing issues (E-2018/E-2019). Gold was not changed.
6. **PII coverage is five types** (email, phone, Luhn-valid card, mod-97 IBAN, pasted credentials). Names, postal addresses, order or account numbers are not treated as PII. The default hash salt should be overridden (`PII_HASH_SALT`) in any real deployment.
7. **LLM non-determinism.** `temperature=0` does not make hosted models deterministic (`deepseek-v4.1-flash` repeat stability was 20/23 in Stage 3, all variants gold-acceptable). Reproducibility comes from the prompt-hash cache, so a cold run against a different model version can differ.
8. **Stage deviations disclosed in `PLAN.md`:** edits to closed stages (Stage 1 `pii.py` and Stage 3 `llm.py`/`classify.py` during Stage 4; Stage 4 `guards.py` S2 negation window made clause-aware, and Stage 4's `test_drafting_stage.py` pinned to its own stage, during Stage 5, after the e2e run showed a correct "I'm not able to confirm or promise a refund" draft being rejected; the 92 stored Stage 4 drafts and all safety fixtures still pass), the `judge.v1` → `judge.v2` rubric correction, and the negation-aware `draft_must_not_include` scoring. `gold.json` and `data/` fixtures were not changed to make anything pass.
9. **Cost is not measured.** The models are not in LiteLLM's price list; token counts per 100 tickets are reported instead. Throughput is sequential (one ticket at a time), which is fine for a batch of this size but not tuned.
10. **Secret/PII scan** covered 166 committable files with 0 hits; it compares file contents against the process's API-key values without printing them, and against the raw PII values in the synthetic tickets.

## 7. Follow-ups worth doing

- Run the Stage 4 calibration sheet (`python -m evals.calibration build|score`) so judge scores can be trusted or discarded.
- Triage the grounding flags and decide on the two gold-policy questions.
- Grow the eval set (more languages, longer tickets, multi-issue tickets, adversarial injections) before relying on the thresholds.
- Add concurrency to the two LLM stages if batches grow; the per-ticket structure and the thread-safe client already allow it.

## 8. How to reproduce

```bash
pip install -r requirements.txt && pip install -r requirements-dev.txt
pytest -q                                   # offline, no keys
python run_pipeline.py --provider stub    # offline end to end
python run_pipeline.py && python validate.py   # real run (needs .env)
python -m evals.e2e_eval run --model gpt-6.1-sol && python -m evals.e2e_eval report
python scripts/audit_stage5.py             # regenerates audit/stage-5 and this report
```
