# Stage 5 — replay report

Offline (`stub` provider, TF-IDF) so it is free and exact. The cache lives in `<out-dir>/.cache`; artifacts are always fully rewritten and the cache only skips computation (R3).

| Run | Exit | Retrieval hit/miss | Classification hit/miss | Drafting hit/miss |
|---|---|---|---|---|
| 1: root tickets (cold) | 0 | 0/3 | 0/3 | 0/3 |
| 2: T-1002 changed, T-1004 added | 0 | 2/2 | 2/2 | 2/2 |
| 3: identical rerun of 2 | 0 | 4/0 | 4/0 | 4/0 |

- Run 2 vs `data/fixtures/replay/expected.json`: unchanged ['T-1001', 'T-1003'] hit, changed ['T-1002'] and added ['T-1004'] miss in every stage → **match** (expected hits 2, misses 2).
- Run 3 is 100% hits in every stage; per-ticket artifacts after run 3 are byte-identical to a further rerun: True.
- Editing one KB article invalidates every retrieval entry (kb hash is part of the key, R1): yes (first run misses 3/3 as expected; the edited-KB run recomputed).
- Two cold runs on the 23-ticket eval set in different directories produce byte-identical `retrieval_results.json`, `ticket_classification.json`, `draft_responses.json`, `escalations.json`, `grounding_flags.json`: True.

With a real model the same holds for retrieval and for the LLM cache (keyed by prompt hash, which includes provider, model, params and prompt version); only a first call to a hosted model can differ from a previous first call, and the cache pins the answer thereafter.
