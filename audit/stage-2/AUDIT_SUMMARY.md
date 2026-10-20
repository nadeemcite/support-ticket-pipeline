# Stage 2 — AI audit summary

- Generated: 2026-10-20 06:40 UTC · git: `08fe731` · Python 3.14.5
- Input hashes (sha256): `data/eval/tickets.json` 2148f103ba03ba02… · `data/eval/kb_articles.json` 666934400c6bf6a1… · `gold.json` 3595d71f55e5576f…
- Retrieval: OpenAI `text-embedding-3-small` embeddings (OD-2), min_score 0.25; TF-IDF (min_score 0.05) as the offline mode.
- **AI gates: ALL HARD GATES GREEN ✅** — the stage still needs human review and sign-off in `PLAN.md` before it is closed.

## Hard gates

| Gate | Threshold | Value | |
|---|---|---|---|
| Stage 1 + 2 tests pass (offline) | 100% | 302/302 | ✅ |
| Live embedding test (samples top-1) | pass | 1 passed, 302 deselected in 5.65s | ✅ |
| Line coverage, Stage 2 modules | ≥ 90% | 98.5% | ✅ |
| Recall@3, English tickets (embedding) | ≥ 0.95 | 16/16 | ✅ |
| No-match precision (E-2010/11/12 → `[]`) | 3/3 | 3/3 | ✅ |
| Same top-3 after fresh re-embedding | 23/23 | 23/23 | ✅ |
| Exit-criteria runs succeed with both artifacts | 5/5 | 5/5 | ✅ |
| `empty_kb` → `[]` for every ticket | 0 with evidence | 0, 0 | ✅ |
| No LLM calls in this stage (`llm_calls.jsonl` empty) | 0 | 0 | ✅ |

## Soft gates

| Gate | Threshold | Value | |
|---|---|---|---|
| Recall@3, non-English tickets (embedding) | ≥ 0.75 | 4/4 | ✅ |
| MRR, tickets with relevant articles (embedding) | ≥ 0.85 | 1.0 | ✅ |

## Evals

Retrieval has no generative LLM, so the 2-model LLM eval doesn't apply. The embedding model is an external API, so its behaviour is measured instead: the deterministic gold-label eval and a fresh re-embedding stability check (max score drift 0.0011, same top-3 23/23). Full detail: `retrieval_eval_report.md`, raw numbers: `evals/retrieval_eval.json`.

## Exit criteria runs

| Run | Exit | Final stage | Tickets | With evidence | Both artifacts | Embedding API calls | LLM calls |
|---|---|---|---|---|---|---|---|
| root (embedding) | 0 | EVIDENCE_RETRIEVED | 3 | 3 | yes | 0 | 0 |
| eval set (embedding) | 0 | EVIDENCE_RETRIEVED | 23 | 20 | yes | 0 | 0 |
| empty_kb (embedding) | 0 | EVIDENCE_RETRIEVED | 3 | 0 | yes | 0 | 0 |
| root (tfidf, offline) | 0 | EVIDENCE_RETRIEVED | 3 | 3 | yes | 0 | 0 |
| empty_kb (tfidf, offline) | 0 | EVIDENCE_RETRIEVED | 3 | 0 | yes | 0 | 0 |

Embedding API calls are 0 in these runs because the vectors were already cached by the eval run (content-addressed cache).

## Reports for human review

- `retrieval_eval_report.md` — per-ticket rankings with scores, snippets, top terms and gold ✅/❌; per-language slice; threshold sweep; TF-IDF vs embedding disagreements
- `pytest_summary.md`, `coverage.txt`, `pytest.xml`

## Known issues / notes for the reviewer

- **Embeddings are not bit-for-bit reproducible across fresh API calls** (drift ≤ 0.0011). Reruns are byte-identical via the cache; a clean checkout may differ in the 3rd–4th decimal of scores, never (on this set) in rankings or kept articles.
- **Embedding retrieval needs `OPENAI_API_KEY`** even when the LLM provider is Ollama. Without it the run stops with exit 2 and a message suggesting `--retriever tfidf`.
- **TF-IDF stays as the offline mode** (`--provider stub` defaults to it): 16/16 English recall but only 2/4 non-English, so it is not the default.
- **The threshold is tuned on 23 tickets.** The margin to the no-match tickets is ~0.04, so new ticket types should be re-checked with `python -m evals.retrieval_eval`.
- **Stage 1 tests changed** (closed stage): 5 assertions that expected retrieval to be unbuilt now expect `EVIDENCE_RETRIEVED`; a synthetic test keeps placeholder pass-through covered. Noted for the Stage 2 sign-off.
