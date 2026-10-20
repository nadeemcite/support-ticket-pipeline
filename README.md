<p align="center"><img src="docs/assets/banner.png" alt="A friendly robot sorting support tickets into mailboxes" width="100%"></p>

# Support Ticket Pipeline

> A robot helper that reads customer messages, finds the right help-article, writes a safe reply, and knows when to call a human.

**Status:** Stages 0–4 are closed. Stage 5 (validation, replay, final report) is **built and all its automatic checks pass**. Only the human project sign-off in [PLAN.md](PLAN.md) is left, and it hasn't been recorded yet, so there is no `stage-5-closed` tag. Final roll-up: [`audit/FINAL_REPORT.md`](audit/FINAL_REPORT.md). See [Where are we?](#where-are-we) and the [plan](PLAN.md).

---

## The idea, for a 10-year-old

Imagine a toy shop with a help desk. Every day, kids and parents send letters:

- *"My toy was charged twice!"*
- *"I can't open my account!"*
- *"Where do I find my receipt?"*

One helper can't read thousands of letters. So we built a **robot assistant**. For every letter it does the same steps, in the same order:

| # | What the robot does | Like in real life |
|---|---|---|
| 1 | **Hides secrets** | Puts a sticker over phone numbers and card numbers so nobody sees them |
| 2 | **Looks up the rulebook** | Flips through the shop's help-book (the *knowledge base*) for the 3 best pages, by meaning (embeddings) or by matching words (offline TF-IDF) |
| 3 | **Sorts the letter** | Is it about money, logging in, something broken, or a question? How urgent? |
| 4 | **Writes a reply** | Using **only** facts from the help-book, in the customer's own language |
| 5 | **Decides: robot or human?** | Tricky or serious letters go to a person, with the reason written down |
| 6 | **Double-checks everything** | A strict checker makes sure the robot never lied, never promised a refund, and never asked for a password |

**The golden rules of the robot**

- 🤐 It never asks for your password.
- 💸 It never promises money back unless the rulebook says so.
- 📖 It never makes up facts. If it's not in the help-book, it says so or asks a human.
- 🕵️ It shows its work, so a person can see *why* it decided something.

---

## How it works (the grown-up version)

A batch command-line pipeline. It reads two files, `tickets.json` and `kb_articles.json`, and writes JSON "artifacts" for every ticket.

```mermaid
flowchart LR
    A[Load files] --> B[Clean + hide PII]
    B --> C[Find 3 best KB articles]
    C --> D[LLM: classify]
    D --> E[LLM: draft reply]
    E --> F[Rules: escalate?]
    F --> G[Validate everything]
```

- **Computers decide the safe things, the LLM only does the language things.** Only *classification* and *drafting* call an AI model. Masking PII, searching, escalation, safety checks and validation are plain Python, so they give the same answer every time.
- **Order is enforced in code.** A stage machine refuses to run a step before the previous one finished.
- **AI output is never trusted blindly.** It is checked against allowed labels and safety rules, retried with feedback, then replaced by a safe template if it keeps failing.

Details: [SPEC.md](SPEC.md) (what it must do) · [DESIGN.md](DESIGN.md) (how and why) · [PLAN.md](PLAN.md) (how we build and audit it) · [PROBLEM.md](PROBLEM.md) (the original brief).

### What it produces

| File | What's inside |
|---|---|
| `retrieval_results.json` | The top 3 help-articles per ticket |
| `ticket_classification.json` | Category, urgency, what to do next |
| `draft_responses.json` | The reply and the articles it cites |
| `escalations.json` | Human needed? Which team? Why? |
| `validation_report.json` | The strict checker's verdict |
| `llm_calls.jsonl` | A log of every AI call (hashes, never raw customer data) |

---

## Where are we?

We build in **5 stages**. A stage is *closed* only after automatic checks pass **and** a human signs it off. Each closure is a git commit plus a tag (`stage-N-closed`).

| Stage | What | Status |
|---|---|---|
| 0 | Plan + test data | ✅ Closed (`stage-0-closed`) |
| 1 | Load, clean, hide PII, stage machine | ✅ Closed (`stage-1-closed`) |
| 2 | Retrieval | ✅ Closed (`stage-2-closed`) |
| 3 | LLM client + classification | ✅ Closed (`stage-3-closed`) |
| 4 | Drafting, safety, escalation | ✅ Closed (`stage-4-closed`) |
| 5 | Validation, replay, final report | 🚧 Built, awaiting human sign-off (closing it closes the project) |

---

## Setup

You need **Python 3.11+** and (for real model runs) API keys.

```bash
git clone git@github.com:nadeemcite/support-ticket-pipeline.git
cd support-ticket-pipeline

python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env                # if present; otherwise create .env and add the keys below
```

`.env` (never committed):

```bash
LLM_PROVIDER=ollama                 # ollama (default) | openai | stub
LLM_MODEL=glm-5.2
OLLAMA_API_KEY=...
OLLAMA_BASE_URL=...                 # OpenAI-compatible, ends with /v1
OPENAI_API_KEY=...                  # embeddings (default retriever), openai provider and evals
RETRIEVER=embedding                 # embedding (default, needs OPENAI_API_KEY) | tfidf (offline; default with stub)
```

No keys? Use `LLM_PROVIDER=stub`: a built-in fake model plus TF-IDF retrieval. It works offline and gives repeatable answers. Real runs use OpenAI `text-embedding-3-small` for retrieval, so they need `OPENAI_API_KEY` unless you pass `--retriever tfidf`.

## Run

> `run_pipeline.py` runs all 10 stages: load, PII masking, retrieval, classification, drafting, escalation, validation (V01–V14) and finalisation. Use `--until <STAGE>` to stop early.

```bash
python run_pipeline.py                      # full run on tickets.json + kb_articles.json
python run_pipeline.py --provider stub      # offline: fake model + TF-IDF retrieval, no keys
python run_pipeline.py --retriever tfidf    # keep the real LLM but skip the embeddings API
python run_pipeline.py --tickets data/eval/tickets.json --kb data/eval/kb_articles.json --out-dir /tmp/out
python validate.py                          # re-check the artifacts on disk (no LLM, no network); writes validation_report.json
```

Exit codes (both commands): `0` all good (warnings allowed) · `1` at least one failed validation check · `2` fatal error (bad inputs or config, missing key, I/O). All flags are in [SPEC §2](SPEC.md).

### Validate

`validate.py` re-reads every artifact from disk and runs 14 checks (V01–V14, [SPEC §8](SPEC.md)): artifacts exist and parse, schemas match, every ticket is covered, labels are in the taxonomy, citations were retrieved, escalation is consistent, no credential request or refund promise, no PII or `[TYPE_n]` placeholder anywhere. It uses the same code as the pipeline's validation stage, so the two always agree. A missing artifact is a failed check, never a skipped one.

```bash
python validate.py --tickets data/eval/tickets.json --kb data/eval/kb_articles.json --out-dir /tmp/out
```

### Replay and caching

Re-running is safe and cheap. Artifacts are **always fully rewritten**; a content-addressed cache in `<out-dir>/.cache/` only skips work whose inputs did not change:

- embeddings are keyed by the hash of the (masked) text and model;
- retrieval is keyed by KB hash + retrieval settings + the ticket's content hash;
- LLM answers are keyed by the prompt hash (provider, model, parameters, prompt version and messages).

Change one ticket and only that ticket is recomputed; edit a KB article and every retrieval entry is recomputed. The manifest (`artifacts/run_manifest.json`) reports hits and misses per stage, and `--no-cache` forces a full recompute. `audit/stage-5/replay_report.md` shows a run 1 → 2 → 3 example.

### Where the audit reports live

Each stage's evidence is in `audit/stage-N/` (start with `AUDIT_SUMMARY.md`). The project roll-up, with known limitations, is [`audit/FINAL_REPORT.md`](audit/FINAL_REPORT.md); a worked example of three tickets through every stage is [`audit/stage-5/sample_walkthrough.md`](audit/stage-5/sample_walkthrough.md).

## Test

```bash
pytest -q                 # everything, offline, no network
pytest -m stage1          # one stage (markers stage1 … stage5)
pytest -m "not live"      # skip tests that call real models
```

Tests use the stub provider and the fixtures in [`data/`](data/README.md), so they are free and deterministic.

## Evals (comparing real models)

Evals run **offline, outside the pipeline**. Two models, `gpt-6.1-sol` and `deepseek-v4.1-flash`, process the same frozen inputs, get scored against the answer key in `data/eval/gold.json`, and **judge each other's drafts**. The model used for day-to-day work (`glm-5.2`) is never the grader.

```bash
python -m evals.retrieval_eval        # Stage 2: retrieval vs gold (needs OPENAI_API_KEY for embeddings)
python -m evals.classification_eval   # Stage 3: 2 models x 3 repeats (--repeats, --workers, --no-dev)
python -m evals.drafting_eval         # Stage 4: drafting + cross-judging (--workers)
python -m evals.e2e_eval run --model gpt-6.1-sol   # Stage 5: the real pipeline end to end, one run per model
python -m evals.e2e_eval report                    #   score the runs against gold, write the report
```

Reports land in `audit/stage-N/` and are committed. Gates and thresholds per stage: [PLAN.md](PLAN.md).

**Judge calibration (Stage 4).** To check that the AI judge scores like a person, 8 drafts are scored blind on a 1–5 scale:

```bash
python -m evals.calibration build     # writes audit/stage-4/calibration_sheet.md (blind) + the answer key
python -m evals.calibration score     # compares the sheet with the judge's scores
```

> ⚠️ The Stage 4 sheet was filled in by an AI agent (Claude) because of time, not by a human. Its 100% agreement is AI-vs-AI, so it is not human calibration and the judge scores should be read as advisory. The note is at the top of the sheet.

## Regenerate the banner

```bash
python scripts/generate_banner.py     # needs OPENAI_API_KEY; writes docs/assets/banner.png
```

## Project map

```text
pipeline/   the code (one module per stage)      data/    test + eval data (synthetic)
tests/      pytest suites                        evals/   offline model comparison
audit/      per-stage reports (committed)        docs/    images
PLAN.md SPEC.md DESIGN.md PROBLEM.md             AGENT.md for coding agents
```

## Working with a coding agent

Read [AGENT.md](AGENT.md). It lists the commands, rules and traps for AI coding assistants (and humans in a hurry).

## Privacy

All sample personal data is fake (`example.com` emails, test card `4111 1111 1111 1111`, example IBAN). Real customer text is masked before any model sees it.
