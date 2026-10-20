# Stage 4 — pytest summary

- Command: `pytest -m "(stage1 or stage2 or stage3 or stage4) and not live" --cov=pipeline --cov=run_pipeline` (earlier stages re-run as regression)
- Result: **561/561 passed**, 0 failed, 0 errors, 0 skipped
- Line coverage, Stage 4 modules (`pipeline/guards.py`, `pipeline/grounding.py`, `pipeline/escalate.py`, `pipeline/draft.py`, `pipeline/language.py`, `pipeline/prompts.py`, `pipeline/stages.py`): **98.1%** (gate ≥ 90%)

| Test module | Passed | Failed |
|---|---|---|
| `test_classification_stage.py` | 9 | 0 |
| `test_classify_overrides.py` | 21 | 0 |
| `test_classify_validation.py` | 15 | 0 |
| `test_cli.py` | 4 | 0 |
| `test_config.py` | 15 | 0 |
| `test_draft_checks.py` | 16 | 0 |
| `test_drafting_stage.py` | 11 | 0 |
| `test_embedding_retriever.py` | 10 | 0 |
| `test_escalation_gold.py` | 1 | 0 |
| `test_escalation_rules.py` | 24 | 0 |
| `test_eval_helpers.py` | 17 | 0 |
| `test_fallback_templates.py` | 32 | 0 |
| `test_grounding.py` | 25 | 0 |
| `test_io.py` | 6 | 0 |
| `test_llm_client.py` | 22 | 0 |
| `test_loader.py` | 16 | 0 |
| `test_manifest.py` | 10 | 0 |
| `test_normalise.py` | 29 | 0 |
| `test_pii.py` | 79 | 0 |
| `test_pii_eval_set.py` | 47 | 0 |
| `test_prompt_classify.py` | 10 | 0 |
| `test_reason_safety.py` | 1 | 0 |
| `test_retrieval_cache.py` | 7 | 0 |
| `test_retrieval_contract.py` | 15 | 0 |
| `test_retrieval_debug.py` | 7 | 0 |
| `test_retrieval_determinism.py` | 8 | 0 |
| `test_retrieval_samples.py` | 2 | 0 |
| `test_safety_patterns.py` | 54 | 0 |
| `test_stage_machine.py` | 17 | 0 |
| `test_taxonomy.py` | 18 | 0 |
| `test_text_processing.py` | 13 | 0 |
