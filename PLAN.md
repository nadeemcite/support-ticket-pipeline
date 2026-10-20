# PLAN — Delivery in 5 audited stages

> Builds the system described in [DESIGN.md](DESIGN.md) / [SPEC.md](SPEC.md) for the brief in [PROBLEM.md](PROBLEM.md). Test and eval data is in [`data/`](data/README.md).

## TL;DR

- **Five stages**, each with a goal, deliverables, exit criteria, an **AI audit** (deterministic `pytest` + evals for anything non-deterministic) and a **human audit** (review the generated reports, then sign off).
- **A stage is closed only when a human signs it off.** The AI agent can run audits and tick AI boxes, but must never tick human boxes or mark a stage `Closed`. The next stage starts only after the previous one is closed.
- **Every stage closure ends in a git commit** (and an annotated tag) that contains the stage's code, its `audit/stage-N/` reports and the recorded sign-off. The commit is made only after the human sign-off (§1, step 6).
- **Determinism first:** only **classification** and **drafting** call an LLM in the pipeline. Loading, normalisation, PII masking, retrieval, escalation, safety, grounding and validation are pure Python and fully covered by `pytest`.
- **Every LLM component gets a 2-model eval:** `gpt-6.1-sol` (OpenAI) and `deepseek-v4.1-flash` (Ollama Cloud) both run on the same frozen inputs, are scored deterministically against `data/eval/gold.json`, and are **cross-judged** (each model judges the other's drafts) where a rubric is needed.
- **Cross-cutting guarantees** (auditability, explainability, idempotency, PII) are built into specific stages and tested there (§3).
- **Stage 5 closes the project:** clean-checkout run, swapped inputs, replay, final 2-model E2E eval, README, and the closing sign-off.

| Stage | Name | LLM? | Evals | Status |
|---|---|---|---|---|
| 0 | Plan approval (this document + data files) | — | — | ☑ Closed (2026-10-20) |
| 1 | Foundations: config, schemas, loading, normalisation, **PII**, stage machine | No | — (deterministic only) | ☑ Closed (2026-10-20) |
| 2 | Retrieval & evidence | No | Deterministic retrieval eval | ☑ Closed (2026-10-20) |
| 3 | LLM layer & classification | **Yes** | 2-model classification eval | ☑ Closed (2026-10-20) |
| 4 | Drafting, guards, grounding & escalation | **Yes** (drafting) | 2-model drafting eval + cross-judging | ☑ Closed (2026-10-20) |
| 5 | Validation, orchestration, replay & **project closure** | Yes (E2E) | 2-model full-pipeline eval | ☑ Closed (2026-10-20) |

---

## 1. Closure protocol (applies to every stage)

```mermaid
flowchart LR
    A[Implement stage deliverables] --> B[AI audit:<br/>pytest + evals]
    B --> C[Generate reports<br/>audit/stage-N/]
    C --> D{All AI gates<br/>green?}
    D -->|no| A
    D -->|yes| E[Human audit:<br/>review reports + checklist]
    E --> F{Human decision}
    F -->|changes requested| A
    F -->|approved| G[Sign-off recorded<br/>in PLAN.md]
    G --> I[Closure commit + tag<br/>stage-N-closed]
    I --> H([Stage CLOSED → next stage may start])
```

1. **Implement** only the deliverables of the current stage.
2. **AI audit:** run `pytest -m stageN` (and all earlier markers, as a regression check) plus the stage's evals. Every run writes to `audit/stage-N/`:
   - `pytest.xml` (JUnit), `coverage.txt`, `pytest_summary.md`
   - `evals/<model>/results.jsonl` + `evals/report.md` (LLM stages)
   - stage-specific human-review reports (listed per stage)
   - `AUDIT_SUMMARY.md`: gates table (metric, threshold, value, ✅/❌), known issues, and the git SHA / input hashes
3. **Gates:** **hard gates** must pass for both eval models. **Soft gates** may miss, but only with a written justification in `AUDIT_SUMMARY.md`.
4. **Human audit:** the reviewer reads the listed reports, works through the checklist, and fills in the sign-off block. Possible outcomes are `Closed` or `Changes requested` (with notes).
5. **No skipping:** stage N+1 must not start while stage N is not `Closed`. Earlier tests must stay green in every later stage.
6. **Closure commit:** once the human has filled in the sign-off block with `Closed` (and the status table in the TL;DR shows ☑ Closed), commit everything that belongs to the stage in **one commit** on `main`, then tag it.
   - Include: stage code and tests, doc updates, `audit/stage-N/` reports (reports are committed, never ignored), the updated `PLAN.md` sign-off and status table, and any `data/` change with its note (step 7).
   - Exclude: `.env`, caches, `audit/**/evals/raw/` and anything else covered by `.gitignore`. Check `git status` shows no unexpected files and no secrets or raw PII before committing.
   - Message: `Close stage N: <stage name>` with a body listing the gate results (pass/total hard gates) and the reviewer. Tag: `git tag -a stage-N-closed -m "Stage N closed"`.
   - The agent makes this commit only after the human sign-off exists in `PLAN.md`. It never commits a stage as closed on its own authority, and it pushes (`git push origin main --tags`) only when the human asks.
   - `Changes requested` produces no closure commit. Work-in-progress commits are allowed, but their messages must not say "Close stage".
   - If a later stage forces a change to a closed stage, record it in the later stage's sign-off notes. Do not rewrite or move the earlier tag.
7. **Fixture changes** (`data/`) after Stage 0 approval need a note in the sign-off of the stage that changed them.

---

## 2. Models

| Role | Model | Provider / API ID | Verified (2026-10-20) |
|---|---|---|---|
| Development (primary) | `glm-5.2:cloud` | Ollama Cloud, API id `glm-5.2` | ✅ responds |
| Development (fast) | `glm-5.2-flash:cloud` → **`glm-5.3-flash`** | Ollama Cloud, API id `glm-5.3-flash` | ⚠️ `glm-5.2-flash` **does not exist** (API: "not found, try glm-5.3-flash:cloud"). `glm-5.3-flash` used as substitute (accepted: the reviewer asked on 2026-10-20 to drop the pending note) |
| Eval model A | `gpt-6.1-sol` | OpenAI | ✅ responds (needs `max_completion_tokens`, not `max_tokens`) |
| Eval model B | `deepseek-v4.1-flash` | Ollama Cloud | ✅ responds |
| Offline / CI | `stub` | local, deterministic | n/a |

- The `:cloud` suffix is a local Ollama CLI convention. Through `OLLAMA_BASE_URL` (`/v1`, OpenAI-compatible) the IDs have no suffix. Config accepts both and strips `:cloud`.
- **Pipeline default** becomes `LLM_PROVIDER=ollama`, `LLM_MODEL=glm-5.2`. SPEC §2.2 / DESIGN §9 currently say `gpt-4o-mini` and are updated in Stage 1.
- **Development** uses the dev models for day-to-day runs. **Evals** always use both eval models, so the system is never graded by the model it was tuned on. The dev model's numbers are reported for information only.
- Eval runs pin model, `temperature=0`, seed, and `max_tokens` / `max_completion_tokens` per provider, and record them in the report header.

---

## 3. Cross-cutting guarantees

| Guarantee | How it's built | Proven by | Stage |
|---|---|---|---|
| **Determinism** | LLM limited to classification + drafting; `temperature=0`; seed; sorted iteration; fixed tie-breaks; canonical JSON | Byte-identical reruns of deterministic stages; repeat-stability metric for LLM stages | 1–5 |
| **Auditability** | One artifact per stage; `llm_calls.jsonl` (prompt hash, inputs/outputs, attempt, status); `run_manifest.json` (input hashes, stage trail, counts); rule IDs on every decision | Tests assert every output record traces to input hash + rule IDs + LLM log line | 1, 3, 5 |
| **Explainability** | `retrieval_debug.json` (top terms, snippets); classification `rationale` + `meta.overrides`; escalation `reason` quoting the rule + KB clause; `grounding_flags.json` | Human-review reports show "why" for each ticket; tests assert `reason`/`rationale` are non-empty and cite rule IDs | 2, 3, 4 |
| **Idempotency** | Normalisation is idempotent; atomic writes; full artifact rewrite each run; content-addressed caches; `llm_calls.jsonl` truncated at `INIT` | `normalise(normalise(x)) == normalise(x)`; rerun → identical artifacts (excluding timestamps/run_id); replay fixture cache hits/misses | 1, 2, 5 |
| **PII protection** | Deterministic detector (email, phone, card via Luhn, IBAN via mod-97, credential disclosures) runs in `TICKETS_NORMALISED`; **LLMs only ever see masked text** (`[EMAIL_1]`…); drafts must not contain raw PII *or* placeholders; logs store hashes, not prompts; `--log-prompts` dumps masked prompts only | `pii_cases.json` unit tests; "no raw PII in any prompt" test; validator checks V13/V14 for leakage in drafts, reasons and logs | 1, 3, 4, 5 |

### 3.1 PII additions to SPEC/DESIGN (written in Stage 1)

PII isn't yet covered by SPEC/DESIGN. Stage 1 adds:

- **P-rules:** P-DET (detect types: `email, phone, card_number, iban, credential`), P-MASK (stable placeholders `[TYPE_n]`; mask is idempotent; `unmask(mask(x)) == x`), P-LLM (prompts only use masked text), P-OUT (no raw PII or placeholders in drafts or escalation reasons; drafts refer to "the email address you provided"), P-LOG (no raw PII in any artifact except the input files; `normalised_tickets.json` stores masked text + `pii_summary` with types, counts and salted hashes).
- **Validator checks:** **V13** (PII leakage: no detector hits in drafts, reasons or `llm_calls.jsonl`) and **V14** (no `[TYPE_n]` placeholders in drafts). Both are `fail` severity.
- Classification rule **C5**: a `credential` detection forces `customer_sensitive=true`, and the draft must include the "never share your password" advice (checked by the S1-negative pattern list).

---

## 4. Eval methodology (Stages 3–5)

```mermaid
flowchart LR
    G[(data/eval/<br/>tickets + KB + gold)] --> DET[Deterministic stages<br/>normalise + PII + retrieval<br/>= frozen, identical inputs]
    DET --> A[System under test<br/>gpt-6.1-sol]
    DET --> B[System under test<br/>deepseek-v4.1-flash]
    A --> SA[Deterministic scorers<br/>vs gold]
    B --> SB[Deterministic scorers<br/>vs gold]
    A -->|drafts| JB[Judge: deepseek-v4.1-flash]
    B -->|drafts| JA[Judge: gpt-6.1-sol]
    SA & SB & JA & JB --> R[evals/report.md<br/>side-by-side + gates]
    R --> H([Human review])
```

- **Same inputs for both models.** The deterministic stages run once and their outputs are frozen, so any difference between models comes from the model alone.
- **Scoring against gold:** *strict* = matches the preferred value, *lenient* = within the acceptable list. Gates use lenient accuracy; strict is reported.
- **Stability:** classification runs **3×** per model, and we report the % of tickets with identical outputs across repeats. Drafting is checked with deterministic metrics on every repeat.
- **Cross-judging:** each model judges the *other* model's drafts, which avoids self-preference. The rubric (1–5): faithfulness to cited KB, addresses the customer's ask, policy compliance, tone, correct language. The judge sees only the masked ticket, the cited KB text and the draft, and returns structured JSON validated with Pydantic.
- **Judge calibration:** the human reviewer scores 8 sampled drafts blind. Judge–human agreement (within ±1) is reported, and if it's < 75% the judge scores are downgraded to *advisory* only.
- **Two drafting modes:** *oracle* (drafting from gold-preferred classifications, which isolates drafting quality) and *end-to-end* (drafting from the model's own classifications).
- **Budget:** ≈ 140 classification + ≈ 92 drafting + ≈ 92 judge calls per full eval. Results are cached by prompt hash, so re-generating a report is free.
- **Evals are offline tooling** (`evals/`). They are never part of `run_pipeline.py`.

---

## Stage 0 — Plan approval

**Goal:** agree on the plan, the models and the data before any code is written.

**Deliverables (done):** `PLAN.md`; `data/` (eval set, gold labels, fixtures, README); root `tickets.json` + `kb_articles.json` (PROBLEM.md samples, verbatim).

**AI audit (done):** every data file parses; the gold labels cover all 23 eval tickets in the same order, reference only existing KB IDs, use only taxonomy values, and are escalation/queue-consistent; synthetic card is Luhn-valid and the decoy is invalid; IBAN passes mod-97.

**Human audit checklist**
- [x] Gold labels in `data/eval/gold.json` reflect the intended policy (especially T-1001 no-escalate, E-2008, E-2010, E-2020)
- [x] Decision **OD-1** (fast dev model substitute) and **OD-2** (cross-lingual retrieval) recorded in §5
- [x] Eval thresholds in Stages 3–5 are acceptable

**Sign-off** — Status: ☑ Closed ☐ Changes requested · Reviewer: Nadeem Sajjad · Date: 2026-10-20 · Notes: Approved by the reviewer's instruction in-session. SPEC.md and DESIGN.md were aligned with this plan before closure. Untracked `pipeline/` (early Stage 1 files) deliberately excluded from this commit.

**Closure commit:** `Close stage 0: Plan approval` (`PLAN.md`, `.gitignore`, `PROBLEM.md`, `SPEC.md`, `DESIGN.md`, `data/`, root `tickets.json` + `kb_articles.json`) · tag `stage-0-closed` · SHA: `b8cef76`

---

## Stage 1 — Foundations (deterministic core + PII)

**Goal:** a typed, tested skeleton that loads, validates, normalises and PII-masks inputs and enforces stage order. No LLM and no network.

**Deliverables**
- `pipeline/config.py` (env + CLI precedence; model IDs with `:cloud` stripped), `taxonomy.py`, `schemas.py` (Pydantic, `extra="forbid"` on outputs), `io_utils.py` (atomic writes, canonical JSON, SHA-256), `loader.py` (I1–I9), `normalise.py`, **`pii.py`** (detect / mask / unmask), `orchestrator.py` (`Stage` IntEnum, `StageMachine`, `@stage` registry with no-op later stages), manifest writer.
- `requirements.txt`, `pytest.ini` (markers `stage1`…`stage5`, `live`), `.gitignore` additions (`.cache/`, `audit/**/evals/raw/`).
- Doc updates: SPEC/DESIGN PII section (§3.1), default model (§2), V13/V14, C5.

**Exit criteria:** artifacts `artifacts/normalised_tickets.json` + `run_manifest.json` produced for the root inputs and for every fixture; no raw PII in `normalised_tickets.json`.

**AI audit — pytest (deterministic)**

| Test file | Proves |
|---|---|
| `test_taxonomy.py` (T1) | Enums are the single source of truth; JSON schema from Pydantic lists exactly the taxonomy values |
| `test_loader.py` | I1 (both `malformed/` fixtures → exit 2), I3, I4, I7, I8, I9; extra fields preserved (I2) |
| `test_normalise.py` | Every assertion in `fixtures/edge_cases/expected.json`; **idempotency** `normalise(normalise(x)) == normalise(x)` |
| `test_pii.py` | Every case in `fixtures/pii_cases.json`: detections, exact masked output, `unmask(mask(x)) == x`, `mask(mask(x)) == mask(x)`, false-positive guards (P05, P09, P10, P12, P14) |
| `test_pii_eval_set.py` | For each eval ticket, detected types == `gold.pii_expected` |
| `test_stage_machine.py` (T3) | Skipping or out-of-order transitions raise `StageOrderError`; a stage with missing required artifacts doesn't run (O1, O2) |
| `test_io.py` | Atomic write leaves the old file on simulated crash; canonical hash is stable under key reordering |
| `test_manifest.py` | Manifest has input hashes, stage trail, rejected/duplicate lists |

Gates (hard): 100% tests pass; line coverage ≥ 90% for Stage 1 modules; 0 raw-PII hits in `normalised_tickets.json` for the eval set.

**AI audit — evals:** none. Stage 1 has no non-deterministic component (stated explicitly in `AUDIT_SUMMARY.md`).

**Reports for human review (`audit/stage-1/`)**
- `pytest_summary.md` + `coverage.txt`
- `pii_masking_report.md`: per eval ticket, original vs masked text, detected types vs expected, plus all false-positive guard results
- `normalisation_report.md`: edge-case fixture before/after, rejected/duplicate lists

**Human audit checklist**
- [x] PII masking report: no missed PII, no over-masking of order IDs/dates/amounts/error codes
- [x] Normalisation preserves meaning (spot-check 5 tickets)
- [x] Stage order cannot be bypassed (read `test_stage_machine.py`)
- [x] SPEC/DESIGN PII + model updates are acceptable

**AI audit result (recorded by the agent, 2026-10-20):** ☑ all 6 hard gates green: 239/239 tests, 98.5% coverage on Stage 1 modules, 0 raw-PII hits across 8 fixture runs, 23/23 eval tickets' PII types match gold, 8/8 expected exit codes. Re-run with `python scripts/audit_stage1.py`; details in `audit/stage-1/AUDIT_SUMMARY.md`. Doc corrections made during the stage: SPEC §6.10 example now shows the real artifact; placeholder for cards is `[CARD_NUMBER_n]` (matching the approved `pii_cases.json`, not `[CARD_n]`); P-DET documents the credential-keyword limitation; DESIGN §10 lists `stages.py`, `runner.py`, `scripts/`.

**Sign-off** — Status: ☑ Closed ☐ Changes requested · Reviewer: Nadeem Sajjad · Date: 2026-10-20 · Reports reviewed: ☑ pytest ☑ PII ☑ normalisation · Notes: Approved by the reviewer's instruction in-session ("I saw the reports and it looks fine to me"); checklist ticked on that basis. No `data/` fixture changes in this stage.

**Closure commit:** `Close stage 1: Foundations` (code, tests, `audit/stage-1/`, this sign-off) · tag `stage-1-closed` · SHA: `08fe731`

---

## Stage 2 — Retrieval & evidence (embeddings, cached)

**Goal:** explainable top-3 retrieval that works across languages, reproducible on rerun, with diagnostics and a retrieval cache.

**Deliverables**
- `pipeline/retrieval.py`: OpenAI `text-embedding-3-small` via LiteLLM (decision **OD-2**), with a content-addressed vector cache and a PII guard (P-EXT); pure-Python TF-IDF as the offline mode; tie-break; threshold; diagnostics (lexical top terms + most similar KB sentence).
- `pipeline/cache.py` (vector cache + per-ticket retrieval cache, R1); `KB_INDEXED` and `EVIDENCE_RETRIEVED` stages; `retrieval_results.json`, `retrieval_debug.json`, `artifacts/kb_index.json`, `artifacts/embedding_calls.jsonl`; `--retriever` flag.
- `evals/retrieval_eval.py`: deterministic scorer against `gold.relevant_articles` for both retrievers, threshold sweep, fresh re-embedding stability check. `scripts/audit_stage2.py` writes `audit/stage-2/`.
- Doc updates: SPEC §2, §5, §6.1–6.2a, §7.7 (`X*` = retrieval rules), §10 R1; DESIGN §6.2, D2, D10, risks; AGENT.md.

**Exit criteria:** both retrieval artifacts are produced for the root and eval inputs (embedding and TF-IDF); `empty_kb` produces `[]` for every ticket without errors.

**AI audit — pytest (deterministic, offline; the real embedder is replaced by a fake)**

| Test file | Proves |
|---|---|
| `test_retrieval_determinism.py` (T2) | Two runs produce byte-identical `retrieval_results.json` / `retrieval_debug.json` / `kb_index.json` (TF-IDF and embedding); tie-break by `article_id` |
| `test_retrieval_samples.py` | T-1001→KB-001, T-1002→KB-002, T-1003→KB-003 as top 1 (TF-IDF, fake embedding; plus one `live` test with real OpenAI embeddings) |
| `test_retrieval_contract.py` | ≤ 3 hits, sorted, scores in `[min_score, 1]`, IDs exist in the KB (V06); empty KB / empty tickets → `[]`; no-match and empty tickets → `[]` |
| `test_retrieval_debug.py` | Every candidate ranked; kept flags match results; every kept hit has a snippet (TF-IDF: and top terms); dropped candidates listed; `kb_index.json` contents |
| `test_retrieval_cache.py` | Rerun → 100% hits with identical output; changed/added tickets miss only (replay fixture); KB edit or settings change invalidates all; `--no-cache`; corrupt entry = miss; embedding cache → no API calls on rerun |
| `test_embedding_retriever.py` | Only masked text reaches the embedder; raw PII refused (P-EXT); batching + memo; embedding log artifact; missing key and API failure are fatal (exit 2) with clear messages |
| `test_text_processing.py` | Stemming, accent folding, placeholder stripping, bigrams, sentence split |

**AI audit — retrieval eval (deterministic scoring against gold; real embeddings, cached)**

| Metric | Gate |
|---|---|
| Recall@3, English tickets with relevant articles | ≥ 0.95 (hard) |
| No-match precision (E-2010/11/12 → `[]`) | 3/3 (hard) |
| Same top 3 after a fresh re-embedding (empty cache) | 23/23 (hard) |
| No LLM calls in this stage (`llm_calls.jsonl` empty) | 0 (hard) |
| Recall@3, non-English tickets (E-2004/5/6/17) | ≥ 0.75 (soft) |
| MRR, all tickets with relevant articles | ≥ 0.85 (soft) |
| Threshold sweep (embedding 0–0.4, TF-IDF 0–0.2), TF-IDF comparison, max score drift | reported; chosen value justified |

**Reports for human review (`audit/stage-2/`)**
- `retrieval_eval_report.md`: per ticket: kept top 3 with scores, snippet, top terms, gold relevance ✅/❌; per-language slice; threshold sweep; stability; TF-IDF vs embedding disagreements
- `AUDIT_SUMMARY.md`, `pytest_summary.md`, `coverage.txt`, `evals/retrieval_eval.json`

**Human audit checklist**
- [x] Rankings make sense for every eval ticket (snippets and terms explain them)
- [x] The `min_score` choice (0.25) is justified by the sweep
- [x] Non-English handling (OD-2, embeddings) is acceptable; reproducibility via the cache is acceptable given the measured drift
- [x] No LLM calls in this stage; only masked text sent to the embeddings API

**AI audit result (recorded by the agent, 2026-10-20):** ☑ all 9 hard gates and both soft gates green: 302/302 offline tests (Stage 1 regression included) + 1 live test, 98.5% coverage on Stage 2 modules, recall@3 16/16 English and 4/4 non-English, MRR 1.0, no-match 3/3, same top 3 after re-embedding 23/23 (max score drift 0.0011), 5/5 exit-criteria runs, 0 LLM calls. Re-run with `python scripts/audit_stage2.py`. **Changes to closed Stage 1 (for the sign-off notes):** five Stage 1 test assertions that expected retrieval to be unbuilt now expect `EVIDENCE_RETRIEVED`, and a synthetic test keeps placeholder pass-through covered; `Config` gained `retriever`/`embedding_model` and `min_score` became retriever-dependent. No `data/` fixture changes.

**Sign-off** — Status: ☑ Closed ☐ Changes requested · Reviewer: Nadeem Sajjad · Date: 2026-10-20 · Reports reviewed: ☑ retrieval eval ☑ pytest · Notes: Approved by the reviewer's instruction in-session ("close stage 2, mark it done"); checklist ticked on that basis. Accepted changes to closed Stage 1: five test assertions updated for implemented retrieval, `Config` gained `retriever`/`embedding_model`, `min_score` is retriever-dependent. No `data/` fixture changes. Generated root artifacts (`retrieval_*.json`, `llm_calls.jsonl`) left out of the commit pending a decision on tracking them.

**Closure commit:** `Close stage 2: Retrieval & evidence` (code, tests, `audit/stage-2/`, this sign-off) · tag `stage-2-closed` · SHA: `4b23b2a`

---

## Stage 3 — LLM layer & classification

**Goal:** a provider-agnostic, logged, cached LLM client, and taxonomy-safe classification that holds up across two different models.

**Deliverables**
- `pipeline/llm.py`: one provider layer through **LiteLLM** (Ollama Cloud via `ollama_chat/`, OpenAI via `openai/`), parameter adapter (`max_completion_tokens` for OpenAI), transport errors as attempt results, stage guard O3, raw-PII guard (P-LLM), prompt hash (L4), LLM cache by prompt hash (R2), thread-safe `llm_calls.jsonl` logging (§6.8 + `cached`, `attempt`, `status`). `pipeline/stub.py` (offline provider), `pipeline/prompts.py` (`classify.v1`), `pipeline/classify.py` (C0–C5, CF), `TICKETS_CLASSIFIED` stage → `ticket_classification.json`.
- `evals/classification_eval.py` (both eval models × 3 repeats + dev model for information, frozen inputs, scored against gold), `evals/report_classification.py` (report + trace sample), `scripts/audit_stage3.py`.
- Doc updates: SPEC C1 (ticket text only), §6.8 `error` field, L3/L8/L9; DESIGN §6.3 (LiteLLM) and §6.4.

**Exit criteria:** `ticket_classification.json` + `llm_calls.jsonl` produced with `glm-5.2` for the root inputs; the stub provider reproduces a run fully offline.

**AI audit — pytest (deterministic, stub/mocked, no network)**

| Test file | Proves |
|---|---|
| `test_prompt_classify.py` | Prompt contains P1–P6; the taxonomy block and JSON schema are rendered from the enums; ticket text is inside delimiters; **only masked text** appears (no raw PII from eval tickets) |
| `test_classify_validation.py` (T7) | Invalid JSON / invented category / missing or extra field / wrong `ticket_id` → retry with error feedback; transport error retries the same prompt; fenced JSON accepted; 3 failures → CF fallback with `meta.fallback=true` |
| `test_classify_overrides.py` | C1–C5 each fire on a minimal input (C1 multilingual, not fired by evidence text) and are recorded in `meta.overrides` |
| `test_llm_client.py` | Logging (required fields, one line per attempt, no prompt text); `prompt_hash` stable and sensitive to provider/model/params/version/messages; cache hit → no provider call; `--no-cache`; transport errors not cached; stage guard O3; raw-PII guard; LiteLLM routing and params (`max_completion_tokens` vs `max_tokens`, `ollama_chat/`, strict schema for OpenAI); fence stripping |
| `test_classification_stage.py` | Stub run on the eval set: artifact contract, log coverage, evidence IDs = retrieval; masked-only prompts; LLM cache on rerun; fallbacks/overrides counted; no LLM calls with `--until EVIDENCE_RETRIEVED`; missing keys fail before any stage |

**AI audit — evals (non-deterministic: 2 models × 3 repeats × 23 tickets)**

| Metric | Gate (each eval model) |
|---|---|
| Final output taxonomy-valid (after retries) | 100% (hard) |
| First-attempt valid JSON + schema | ≥ 90% (soft) |
| Fallback rate | ≤ 5% (hard) |
| `issue_type` lenient accuracy | ≥ 90% (hard) |
| `resolution_action` lenient accuracy | ≥ 85% (hard) |
| `urgency` lenient accuracy | ≥ 80% (soft) |
| `requires_refund_caution` accuracy | 100% (hard; C1 backstop) |
| Prompt-injection resistance (E-2009 urgency ≠ critical, all repeats) | 100% (hard) |
| Repeat stability (identical labels across 3 repeats) | ≥ 90% of tickets (soft) |
| Cross-model agreement (Cohen's κ, `issue_type` / `resolution_action`) | reported |
| Latency p50/p95, tokens, est. cost | reported |

**Reports for human review (`audit/stage-3/`)**
- `evals/report.md`: gate table per model; confusion matrices per field; **disagreement table** (tickets where the models disagree with each other or with gold, with both rationales); stability table; overrides fired
- `llm_trace_sample.md`: 5 random log lines, each traced to its (masked) prompt, output, and final record
- Dev-model run (`glm-5.2`) summary, for information only

**Human audit checklist**
- [x] Review every row of the disagreement table; decide for each whether it's a model error, a gold error (fix gold, note it here) or a prompt issue
- [x] Rationales are grounded in the retrieved evidence
- [x] Trace sample: each record links to an LLM log line and a prompt hash
- [x] No raw PII in any logged or dumped prompt

**AI audit result (recorded by the agent, 2026-10-20):** ☑ all 17 hard gates green (5 pipeline gates + 6 per eval model): 379/379 offline tests, 99.5% coverage on Stage 3 modules, dev-model root run OK, stub runs byte-identical, 5/5 trace hashes recomputed. Both eval models: 0% fallbacks, `issue_type` 100%, `requires_refund_caution` 100%, injection resisted 3/3; `resolution_action` 97.1% (`gpt-6.1-sol`) / 100% (`deepseek-v4.1-flash`). Soft: 5/6 green; `deepseek-v4.1-flash` repeat stability 20/23 missed, justified in `audit/stage-3/AUDIT_SUMMARY.md` (all variants gold-acceptable, no escalation change). κ: issue_type 0.83, urgency 0.62, resolution_action 0.80. Re-run: `python -m evals.classification_eval` then `python scripts/audit_stage3.py`. **Changes to closed stages (for the sign-off notes):** Stage 1/2 tests that pinned "the latest implemented stage" now derive it from the stage registry (no more edits needed per stage); `PIILeakError` moved from `retrieval.py` to `pii.py` (still importable from both); `RunContext` gained `entering` for the O3 guard. No `data/` fixture changes.

**Sign-off** — Status: ☑ Closed ☐ Changes requested · Reviewer: Nadeem Sajjad · Date: 2026-10-20 · Reports reviewed: ☑ eval report ☑ trace sample ☑ pytest · Notes: Approved by the reviewer's instruction in-session ("sign off 3"); checklist ticked on that basis. Accepted: deepseek repeat-stability soft miss (justified), changes to closed stages listed above. The two policy questions from the audit (E-2014 `request_more_info`; VIP urgency for E-2018/E-2019) were not answered, so gold is unchanged and they stay open for Stage 4/5 review. No `data/` fixture changes.

**Closure commit:** `Close stage 3: LLM layer & classification` (code, tests, `audit/stage-3/`, this sign-off) · tag `stage-3-closed` · SHA: `ca33986`

---

## Stage 4 — Drafting, guards, grounding & escalation

**Goal:** grounded, safe, correctly-languaged drafts, and deterministic, evidence-cited escalation decisions.

**Deliverables**
- `pipeline/guards.py` (S1–S3, PII-leak check, placeholder check), `grounding.py` (G1–G3), `prompts.py` (`draft.v1`), `draft.py` (D1–D9, DF templates in en/es/fr/de/pt), `escalate.py` (E1–E5, Q1–Q2, invariants), `draft_responses.json`, `grounding_flags.json`, `escalations.json`.
- `pipeline/language.py` (stopword language heuristic, reused by V09 in Stage 5).
- `evals/drafting_eval.py` (oracle + end-to-end modes, both models), `evals/judge.py` (cross-judging, rubric schema), `evals/report_drafting.py`, `evals/calibration.py` (blind sheet + agreement), `scripts/audit_stage4.py`.

**Exit criteria:** all three artifacts produced for the root inputs with `glm-5.2`; escalations are identical across repeated runs given the same classifications.

**AI audit — pytest (deterministic)**

| Test file | Proves |
|---|---|
| `test_safety_patterns.py` (T4) | Every case in `fixtures/safety_cases.json` (positives fire, negatives/negations don't) |
| `test_grounding.py` (T6) | Every case in `fixtures/grounding_cases.json`, including G-05 (negated KB sentence doesn't count as support) and G-11 (only *cited* text counts) |
| `test_escalation_rules.py` (T5) | E1–E5 and Q1/Q2 truth table; E-INV1–3; KB clause quoted in `reason`; same input → same output |
| `test_escalation_gold.py` | Feeding gold-preferred classifications + Stage 2 retrieval → `escalate`/`target_queue` equal gold-preferred for all 23 tickets |
| `test_draft_checks.py` | Stub returning a non-retrieved citation / a password request / a refund promise / no escalation mention / a placeholder / raw PII → each is blocked, retried, then DF fallback |
| `test_fallback_templates.py` | Templates exist per language, pass S1/S2/V13/V14, mention escalation when required |
| `test_reason_safety.py` | Escalation reasons never match S2 and never contain PII |

**AI audit — evals (non-deterministic: 2 models × 2 modes × 23 tickets, cross-judged)**

| Metric | Gate (each eval model) |
|---|---|
| Citation validity (⊆ retrieved) | 100% (hard) |
| S1 credential requests | 0 (hard) |
| S2 refund promises where caution required | 0 (hard) |
| PII leakage (V13) / placeholder leakage (V14) | 0 / 0 (hard) |
| Escalation mentioned when action = escalate | 100% (hard) |
| `draft_must_not_include` violations | 0 (hard) |
| `draft_must_include_any` hit rate (English) | ≥ 85% (soft) |
| Language match (ticket language) | 100% (hard) |
| Grounding flags per draft | ≤ 0.3 average (soft); every flag listed |
| Fallback rate | ≤ 5% (soft) |
| Judge faithfulness, mean (1–5) | ≥ 4.0 (hard, unless downgraded by calibration) |
| Judge helpfulness / tone / policy, mean | ≥ 3.8 / ≥ 4.0 / ≥ 4.5 (soft) |
| Judge–human agreement on 8 calibration drafts | ≥ 75% within ±1 (gates the judge's authority) |

**Reports for human review (`audit/stage-4/`)**
- `evals/report.md`: gate table per model and mode; **side-by-side drafts per ticket** (model A vs B, citations, judge scores + judge rationale, grounding flags, deterministic check results)
- `escalation_report.md`: per ticket: classification → rules fired → queue → reason with KB clause
- `calibration_sheet.md`: 8 blind drafts for the human to score (filled in during review)
- `grounding_flags_review.md`: every flag with the cited KB text next to it

**Human audit checklist**
- [x] Read all side-by-side drafts for the sample tickets and for every `pii`, `safety`, `prompt_injection` and `non_english` tagged ticket
- [ ] Complete the calibration sheet; confirm judge authority — **not done: reviewer chose to close without it (see sign-off notes); judge scores are advisory**
- [x] Review every grounding flag: true positive or false positive (tune the heuristic, note it here)
- [x] Escalation report: every decision is explainable from classification + KB evidence

**AI audit result (recorded by agent, 2026-10-20):** ☑ all hard gates green, no soft misses: 561/561 offline tests (Stages 1–3 re-run as regression), 98.1% line coverage on Stage 4 modules, dev-model (`glm-5.2`) run on the root inputs produces all three artifacts, escalations byte-identical across repeated runs, escalation rules reproduce gold for 23/23 tickets from gold-preferred classifications (and 23/23 from each eval model's own classifications). Both eval models × both modes × 23 tickets: citation validity 100%, S1/S2/PII/placeholder violations 0, escalation mentioned 100%, language match 100%, 0 template fallbacks; judge faithfulness `gpt-6.1-sol` 5.00 (judged by deepseek), `deepseek-v4.1-flash` 4.48 (judged by gpt). Re-run `python -m evals.drafting_eval && python scripts/audit_stage4.py`; details in `audit/stage-4/AUDIT_SUMMARY.md`.

**Things the reviewer should know (found while running the audit, all disclosed rather than hidden):**
- *Judge rubric corrected once* (`judge.v1` → `judge.v2`). `v1` docked "a specialist will follow up" as an unsupported claim although policy (D7, DF) requires it; deepseek's faithfulness read 3.65 / 3.83 (hard gate ≥ 4.0). `v2` states that process statements are not product claims; invented facts, steps and menu paths still lower the score (deepseek still gets 4.48, with real deductions for invented troubleshooting steps and menu paths). Draft prompts and models were not changed.
- *`draft_must_not_include` scoring is negation/hedge-aware.* A plain substring hit inside a negation or hedge in the same sentence ("never share your password", "we can't confirm whether we offer sponsorships") is advice, not a violation. Six such hits were false positives; `gold.json` is unchanged and raw hits are still reported (`must_not_include_raw_hits`).
- *The judge is lenient on `gpt-6.1-sol` drafts* (deepseek as judge gives 5 on nearly every criterion), so the human calibration sheet decides how far judge scores can be trusted.
- *Three guard false positives were fixed because they forced template fallbacks on E-2008 (credential disclosed):* S1 read "please confirm you are using the most recent password" as a credential request (clauses between verb and noun now cancel it), and the Stage 1 credential detector read the prose "your password is disclosed" as a pasted secret (`pii._NON_SECRET_VALUES`). Grounding was tuned the same way: translated menu labels outside English, empathy and courtesy sentences, KB-prescribed escalation offers, and a single number matching an end of a cited range are no longer flagged. Every tuning has a regression test.
- *A real robustness bug was fixed:* a rejected draft containing PII was echoed into the retry prompt, which the P-LLM guard refused, aborting the whole run. Output containing PII is now withheld from retry prompts (`llm.echo_for_retry`, also used by classification).
- *Changes to closed stages (for the sign-off notes):* `pipeline/pii.py` (Stage 1, `_NON_SECRET_VALUES` + test), `pipeline/llm.py` and `pipeline/classify.py` (Stage 3, `echo_for_retry`), and three Stage 3 tests in `tests/test_classification_stage.py` now stop at `TICKETS_CLASSIFIED` (`until=`) because a default run now continues through drafting. No `data/` fixture or `gold.json` changes.
- *Open policy questions carried from Stage 3* (E-2014 action, VIP billing urgency) did not affect any Stage 4 gate: escalation decisions match gold for both models.

**Sign-off** — Status: ☑ Closed ☐ Changes requested · Reviewer: Nadeem Sajjad · Date: 2026-10-20 · Reports reviewed: ☑ eval report ☑ escalation ☐ calibration (skipped) ☑ grounding · Notes: Approved by the reviewer's in-session instruction ("sign off 4", choosing to close without the calibration sheet). **The calibration sheet was not scored, so judge–human agreement was never measured and all judge scores (including the faithfulness gate) are advisory, not authoritative.** The deterministic gates do not depend on the judge and are green. The 8 grounding flags were not individually marked TP/FP; no heuristic tuning was requested. Accepted: changes to closed stages listed under the AI audit result, and the judge.v1→v2 rubric correction. Carried to Stage 5: calibration can still be run later with `python -m evals.calibration build|score`. No `data/` fixture or `gold.json` changes.

**Closure commit:** `Close stage 4: Drafting, guards, grounding & escalation` (code, tests, `audit/stage-4/`, this sign-off) · tag `stage-4-closed` · SHA: `b18557b`

---

## Stage 5 — Validation, orchestration, replay & project closure

**Goal:** a single command that regenerates and validates everything from a clean checkout with any equivalent inputs, plus final evidence that the whole system meets the brief. **Closing this stage closes the project.**

**Deliverables**
- `pipeline/validation.py` (V01–V14) + `validate.py` CLI, `run_pipeline.py` (all 10 stages wired, exit codes 0/1/2, CLI flags), `finalise.py` (per-stage cache report, console summary; the manifest itself is written by `runner.py`), replay cache across stages (R1–R6).
- `README.md`: setup, run, validate, models/providers, replay approach (stretch §8), artifact guide, and where the audit reports live.
- `evals/e2e_eval.py`: full pipeline on the eval set, with both eval models as the pipeline LLM. `scripts/audit_stage5.py` regenerates `audit/stage-5/` and `audit/FINAL_REPORT.md`.
- `audit/FINAL_REPORT.md`: roll-up of all stage gates, final E2E results, known limitations.

**Exit criteria:** every acceptance criterion A1–A5 (SPEC §12.1) and the sample-ticket expectations (SPEC §12.2) are met.

**AI audit — pytest (deterministic)**

| Test file | Proves |
|---|---|
| `test_validator_mutations.py` | For each V-check, a mutated artifact (missing ticket, bad enum, foreign citation, queue/escalate mismatch, password request, raw email, placeholder) makes exactly that check fail |
| `test_e2e_stub.py` (T8) | Stub run on the root, eval, edge-case, `empty_kb` and `empty_tickets` inputs → exit 0, V01–V14 pass |
| `test_replay.py` (T9) | `fixtures/replay/expected.json`: hits/misses per stage; identical rerun → 100% hits; KB edit → retrieval invalidated |
| `test_idempotency.py` | Two runs → per-ticket artifacts byte-identical (excluding `timestamp`, `run_id`, `latency_ms`) |
| `test_clean_checkout.py` | Copy the repo without generated files to a temp dir, run the pipeline (stub) → all required artifacts created (A1/A2) |
| `test_swapped_inputs.py` | `--tickets/--kb` pointing to the eval set → coverage matches the new IDs (A3) |
| `test_cli.py` | Exit codes 0/1/2; missing key message; `validate.py` alone reproduces the report status (A4) |
| `test_no_llm_outside_stages.py` | Only classification/drafting stages produce `llm_calls.jsonl` lines; stage tags match |

**AI audit — evals (full pipeline, both eval models, + dev model for information)**

| Metric | Gate (each eval model) |
|---|---|
| `validate.py` status on eval-set run | `pass` (hard) |
| All Stage 3 + Stage 4 hard gates, re-measured end-to-end | pass (hard) |
| Escalation accuracy vs gold (lenient) | ≥ 90% (hard) |
| Sample tickets T-1001/2/3 meet SPEC §12.2 | 3/3 (hard) |
| Regression vs Stage 3/4 numbers | no hard metric worse by > 5 pts (hard) |
| Run time + cost per 100 tickets | reported |

**Reports for human review (`audit/stage-5/` + `audit/FINAL_REPORT.md`)**
- `FINAL_REPORT.md`: every stage's gates and sign-off status, final E2E table per model, known limitations, follow-ups
- `validation_report.json` for the root run and the eval-set run, rendered as `validation_summary.md`
- `replay_report.md`: run 1 → run 2 → run 3 cache stats
- `sample_walkthrough.md`: T-1001/2/3 end to end (retrieval → classification → draft → escalation → validation), with every rule ID and LLM log reference

**Human audit checklist (project closure)**
- [x] Fresh clone + `pip install -r requirements.txt && python run_pipeline.py && python validate.py` works on the reviewer's machine *(checked by the agent on the delegated sign-off: fresh clone of `origin`, new venv, no `.env`, `--provider stub --retriever tfidf` → validate pass 14/14; real-key run covered by A1)*
- [x] Swap in a hand-written `tickets.json` (≥ 3 new tickets) → run succeeds and the outputs make sense *(4 new tickets incl. an en/es mix, a pasted password, an off-topic one; `glm-5.2` + tfidf; validate pass 14/14; billing and account tickets escalated to the KB-prescribed queues, es ticket answered in Spanish, off-topic not escalated; the pasted password and email appear in no artifact)*
- [x] `sample_walkthrough.md` reviewed: each decision is explainable and grounded *(agent read-through only, not a manual line-by-line audit)*
- [x] No secrets or raw PII in any committed file or artifact (`.env` ignored; V13 passes) *(tracked-file scan: the only detector hits are synthetic PII in `data/`, tests, docs and the Stage 1 masking report, plus digit-run false positives in two eval JSONL files)*
- [x] All earlier stages show `Closed`, each with a closure commit and tag (`git tag -l 'stage-*'` lists `stage-0-closed` … `stage-4-closed`)
- [x] `FINAL_REPORT.md` known limitations accepted

**AI audit result (recorded by agent, 2026-10-20):** ☑ all hard gates green: 617 offline tests pass (3 skips are the "stage not built yet" guards, which no longer apply), 97.9% line coverage on Stage 5 modules, acceptance criteria A1–A5 verified on real runs (A1 with `glm-5.2` + embeddings, A5 from a clean copy with no `.env` or keys), replay matches `fixtures/replay/expected.json`, an identical rerun is 100% cache hits, a KB edit invalidates all retrieval entries, cold runs are byte-identical, no secrets or raw PII in committable files. End to end on the eval set with each eval model as the pipeline LLM (cold, no cache): `validate.py` pass, escalation vs gold 23/23 for both, sample tickets T-1001/2/3 3/3 for both, no hard metric worse than Stages 3/4, 0 classification and 0 draft fallbacks. Re-run `python -m evals.e2e_eval run --model <m> --cold` (per model), then `report`, then `python scripts/audit_stage5.py`; details in `audit/stage-5/AUDIT_SUMMARY.md` and `audit/FINAL_REPORT.md`.

**Things the reviewer should know:**
- *The e2e run found a real guard bug, fixed in this stage.* `deepseek-v4.1-flash` wrote a correct reply ("I'm not able to confirm or promise a refund…") that S2 rejected three times because its negation window was 4 words, so T-1001 shipped as the template fallback with no citation and failed its SPEC §12.2 check. S2 now uses a 6-word, clause-aware window and also treats "unable" as a negation. Regression tests were added, and the 92 stored Stage 4 drafts plus all safety fixtures still pass. This edits closed Stage 4 code (`pipeline/guards.py`), as does pinning Stage 4's `test_drafting_stage.py` to its own stage, since a default run now continues through validation.
- *`audit/stage-4/` was not regenerated*, so its reports still reflect the pre-fix guard; the numbers were rechecked offline (above) rather than rewritten.
- *`glm-5.2` (dev model, information only)* ended with a template fallback on E-2008 (the ticket where the customer pasted a password) and 5 grounding flags. It is not a gate.
- *The Stage 4 calibration sheet was scored by an AI agent* (noted at its top), so judge–human agreement was never measured. `FINAL_REPORT.md` limitation 2 says so; judge scores remain advisory.
- *Leak-scan exemptions are listed* in `AUDIT_SUMMARY.md`: the Stage 1 masking report, the README privacy note and each `pytest.xml` contain synthetic PII on purpose.
- *Validation warnings:* the `deepseek-v4.1-flash` run has one V12 warning (6 grounding flags). Warnings do not fail a run.

**Project sign-off** — Status: ☑ **PROJECT CLOSED** ☐ Changes requested · Reviewer: Nadeem Sajjad · Date: 2026-10-20 · Notes: Closed on the reviewer's in-session instruction ("sign off manually fill the checklist using your judgement"). The checklist was completed by the agent, not by the reviewer: the fresh-clone and new-tickets checks were run by the agent in the agent's environment, and the walkthrough was not audited by hand. The judge was never calibrated by a human (Stage 4 sheet scored by an AI), so judge scores stay advisory. Known limitations in `audit/FINAL_REPORT.md` §6 are accepted as written. Open gold-policy questions (E-2014, VIP urgency) remain unresolved. No `data/` fixture or `gold.json` changes.

**Post-closure changes (after `v1.0.0`, from review; tags not moved).** Edits to closed stages, each its own commit: no-key default to the stub provider with a console note; S1/S2 wording (`what is your password`, `let us know`, login credentials/details, `money back`, active/passive issued/processed/reversed refund; S2 negation window 8 words); V09 is a failure and tickets in unsupported languages are escalated by the new rule E6 with no model call; the draft's escalation wording must match the final decision for every rule (D7 extended, new D12, V11 both ways, prompt `draft.v2`); TF-IDF default `min_score` 0.05 → 0.07 (largest loss-free value in the eval-set sweep); CI workflow and Dockerfile. Not redone: the `audit/stage-*` reports and the root reference run in `llm_calls.jsonl` (still `draft.v1`) predate these changes, and the two eval models were not re-run on `draft.v2`. A past `glm-5.2` draft (T-1001, `draft.v1`) now fails V11 because it says "I have escalated" when the decision was not to escalate; that is the new check working, not a regression.

**Second polish pass (same day, after the push of the first):** OpenAI-only setup (provider auto-detect order `--provider`/`LLM_PROVIDER` > `OPENAI_API_KEY` > `OLLAMA_*` > stub; `OPENAI_MODEL`, default `gpt-4o-mini`; automatic `max_tokens`/`max_completion_tokens` retry; embeddings only when `OPENAI_API_KEY` exists, else TF-IDF); retrieval relevance gate X6 (`retrieval.v2`); TF-IDF `min_score` back to 0.05 (0.07 dropped T-1001's KB-004); S2 reversal/reimbursement/credit-back wording; CI actions on Node 24; the root reference run regenerated with `draft.v2` on `gpt-4o-mini` + `text-embedding-3-small` (3 sample tickets, validate pass). Still not redone: the `audit/stage-*` reports and the two-model eval set runs (`draft.v1`).

**Closure commit:** `Close stage 5: Validation, orchestration, replay & project closure` (code, tests, `README.md`, `audit/stage-5/`, `audit/FINAL_REPORT.md`, this sign-off) · tag `stage-5-closed` (also `v1.0.0`) · SHA: `3a565b9`

---

## 5. Open decisions and spec gaps (found while creating the data)

| ID | Issue | Recommendation | Decide by |
|---|---|---|---|
| OD-1 | `glm-5.2-flash` does not exist on Ollama Cloud | Use `glm-5.3-flash` (Ollama's own suggestion) as the fast dev model | Stage 0 |
| OD-2 | TF-IDF can't match es/fr/de/pt tickets to the English KB (E-2004 shares no terms with KB-002) | **Decided (2026-10-20): OpenAI embeddings** (`text-embedding-3-small` via LiteLLM), cached by content hash, masked text only; TF-IDF kept as the offline mode. Measured in Stage 2: 4/4 non-English vs 2/4 for TF-IDF | Stage 2 ✅ |
| OD-3 | PII not covered by SPEC/DESIGN | Add P-rules, C5, V13, V14 (§3.1) | Stage 1 |
| OD-4 | Grounding G3: SPEC lists only `will`-style verbs while DESIGN also lists `can/available`; KB sentences with a negation ("should not be promised") could falsely "support" a promise (fixture G-05) | G3 detects `can be / available / will`; supporting sentences containing a negation never count as support. **Decided and implemented in Stage 4** (`grounding.py`, fixture G-05, `SPEC` §7.5) | Stage 4 ✅ |
| OD-5 | Pipeline default model in SPEC/DESIGN is `gpt-4o-mini` | Change to `ollama / glm-5.2`; keep `openai` selectable | Stage 1 |
| OD-6 | Drafts must not echo PII, but may need to refer to it | The prompt tells the model to refer generically ("the email address you provided"); V14 blocks placeholders. **Implemented in Stage 4** (`draft.v1` prompt, D11, a rejected draft containing PII is never echoed into a retry prompt) | Stage 4 ✅ |
