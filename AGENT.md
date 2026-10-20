# AGENT.md — guide for coding agents

Read this first, then [README.md](README.md) (overview), [PLAN.md](PLAN.md) (what to build now), [SPEC.md](SPEC.md) (exact behaviour), [DESIGN.md](DESIGN.md) (why). `CLAUDE.md` simply points here.

## What this repo is

A batch pipeline that triages support tickets: load → normalise + mask PII → embedding retrieval (OpenAI, cached; TF-IDF offline) → LLM classify → LLM draft → rule-based escalation → validation. Only classification and drafting use an LLM. Retrieval calls the OpenAI embeddings API with masked text only (vectors cached, so reruns are byte-identical). Everything else is deterministic Python.

## First things to do each session

1. Find the current stage: the status table at the top of `PLAN.md`. Work **only** on that stage's deliverables. Never start stage N+1 while N is not `Closed`.
2. `git status` and `git log --oneline`. Check which `stage-*-closed` tags exist.
3. Read the stage's section in `PLAN.md`: deliverables, pytest files, gates, reports.

## Commands

```bash
source .venv/bin/activate
pytest -q                      # all tests (offline)
pytest -m stageN               # one stage (also run earlier markers as regression)
pytest -m "not live"           # skip real-model tests
python run_pipeline.py --provider stub    # offline run (TF-IDF retrieval); runs the stages built so far (--until <STAGE>, --out-dir <dir>)
python run_pipeline.py                    # real run: embeddings need OPENAI_API_KEY in .env
python validate.py                        # validate artifacts on disk (Stage 5+)
python -m evals.<name>                    # offline evals (need keys), Stages 2-5
```

Commands marked with a stage don't exist until that stage is built. Check before assuming.

## Hard rules

| Rule | Why |
|---|---|
| **Never tick human audit boxes, fill a sign-off, or mark a stage `Closed`.** Only the human does. After they have, make the closure commit + tag as `PLAN.md` §1 step 6 says | Stages are closed by humans |
| **Never push, force-push, or move/delete a tag unless asked.** Pushing needs a human ask each time | Outward-facing and hard to undo |
| **Commit identity:** this repo uses `nadeem.sajjad.1991@gmail.com` (repo-local config) and the remote alias `github.com-nadeemcite`. Don't use the `nadyth` identity | A previous commit had the wrong author |
| **Never read, print, log or commit `.env`** or any key | Secrets |
| **No raw PII anywhere downstream of `TICKETS_NORMALISED`**: prompts, artifacts, logs, drafts, reasons. Only `[TYPE_n]` placeholders | PII rules P-*, V13/V14 |
| **Labels come from `pipeline/taxonomy.py` only.** Prompts, schemas and validators render from the enums. Never hard-code a label list | Single source of truth |
| **Keep deterministic stages deterministic**: sorted iteration, fixed tie-breaks, canonical JSON, no clocks or randomness in artifacts (except `timestamp`, `run_id`, `latency_ms`) | Byte-identical reruns are tested |
| **Writes are atomic** (`io_utils`), and artifacts are fully rewritten each run | Idempotency |
| **No LLM call outside classification/drafting**, none before `EVIDENCE_RETRIEVED` | Stage guard O3 |
| **Only masked text goes to the embeddings API**, through `CachedEmbedder` (never call LiteLLM directly from a stage). Tests use the `fake_embedder` fixture; the autouse `offline` fixture blocks real network | P-EXT, offline tests |
| **Don't edit `data/` fixtures or `gold.json` to make a test pass.** A fixture change is a reviewed change, noted in the stage sign-off | They are the answer key |
| **Evals are never part of `run_pipeline.py`** | Keeps the run cheap and deterministic |
| **Don't grade a model with the model it was tuned on.** Dev model is `glm-5.2`; eval models are `gpt-6.1-sol` and `deepseek-v4.1-flash` | Avoid self-preference |

## Conventions

- Python 3.11+, type hints, Pydantic v2 with `extra="forbid"` on outputs.
- Match the surrounding code's style, naming and comment density. Small, single-purpose modules, one per stage (see DESIGN §10 for the layout).
- Rule IDs (`C*`, `D*`, `E*`, `Q*`, `S*`, `G*`, `P*`, `X*`, `V*`) appear in code, reasons and tests. Reuse them, and don't invent new ones without updating `SPEC.md`.
- Prompt templates are versioned (`classify.v1`, `draft.v1`). Changing a template means bumping the version.
- OpenAI reasoning models need `max_completion_tokens`, Ollama uses `max_tokens`. A `:cloud` suffix on model IDs is stripped.
- Tests: deterministic, offline by default, use the `stub` provider. Mark real-model tests `@pytest.mark.live`. Markers: `stage1`…`stage5`, `live`.
- Test data lives in `data/` (see `data/README.md`). Never use real personal data.

## Definition of done for any change

1. Relevant `pytest -m stageN` and all earlier markers pass.
2. No new raw PII or secrets in any file (`git diff` check).
3. `SPEC.md` / `DESIGN.md` / `PLAN.md` updated if behaviour or decisions changed. They must not contradict each other or the code.
4. Reports required by the stage are in `audit/stage-N/`.
5. You report honestly: failing tests, skipped gates and known issues are stated, not hidden.

## Layout

```text
pipeline/    code, one module per stage      tests/    pytest suites
data/        eval set, gold labels, fixtures evals/    offline model evals
audit/       per-stage reports (committed)   scripts/  helpers (e.g. generate_banner.py)
artifacts/   intermediate outputs (generated)   .cache/ replay cache (ignored)
```

Generated root artifacts (`retrieval_results.json`, `ticket_classification.json`, `draft_responses.json`, `escalations.json`, `validation_report.json`, `llm_calls.jsonl`) are outputs, not source: never hand-edit them. Regenerate by running the pipeline.

## When unsure

Ask the human rather than guessing on: policy (what should escalate), gold-label changes, anything that sends data to an external service, and anything destructive in git.
