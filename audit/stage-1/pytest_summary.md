# Stage 1 — pytest summary

- Command: `pytest -m stage1 --cov=pipeline --cov=run_pipeline`
- Result: **239/239 passed**, 0 failed, 0 errors, 0 skipped
- Line coverage, Stage 1 modules: **98.5%** (gate ≥ 90%) — details in `coverage.txt`

| Test module | Passed | Failed |
|---|---|---|
| `test_cli.py` | 4 | 0 |
| `test_config.py` | 15 | 0 |
| `test_io.py` | 6 | 0 |
| `test_loader.py` | 16 | 0 |
| `test_manifest.py` | 10 | 0 |
| `test_normalise.py` | 29 | 0 |
| `test_pii.py` | 78 | 0 |
| `test_pii_eval_set.py` | 47 | 0 |
| `test_stage_machine.py` | 16 | 0 |
| `test_taxonomy.py` | 18 | 0 |
