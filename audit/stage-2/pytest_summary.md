# Stage 2 — pytest summary

- Command: `pytest -m "(stage1 or stage2) and not live" --cov=pipeline --cov=run_pipeline` (Stage 1 suite re-run as regression)
- Result: **302/302 passed**, 0 failed, 0 errors, 0 skipped
- Line coverage, Stage 2 modules (`pipeline/retrieval.py`, `pipeline/cache.py`, `pipeline/stages.py`, `pipeline/config.py`, `pipeline/runner.py`): **98.5%** (gate ≥ 90%)
- Live test (`pytest -m live`, real OpenAI embeddings on the samples): 1 passed, 302 deselected in 5.65s

| Test module | Passed | Failed |
|---|---|---|
| `test_cli.py` | 4 | 0 |
| `test_config.py` | 15 | 0 |
| `test_embedding_retriever.py` | 10 | 0 |
| `test_io.py` | 6 | 0 |
| `test_loader.py` | 16 | 0 |
| `test_manifest.py` | 10 | 0 |
| `test_normalise.py` | 29 | 0 |
| `test_pii.py` | 78 | 0 |
| `test_pii_eval_set.py` | 47 | 0 |
| `test_retrieval_cache.py` | 7 | 0 |
| `test_retrieval_contract.py` | 15 | 0 |
| `test_retrieval_debug.py` | 7 | 0 |
| `test_retrieval_determinism.py` | 8 | 0 |
| `test_retrieval_samples.py` | 2 | 0 |
| `test_stage_machine.py` | 17 | 0 |
| `test_taxonomy.py` | 18 | 0 |
| `test_text_processing.py` | 13 | 0 |
