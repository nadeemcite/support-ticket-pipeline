# DESIGN — Support Ticket Triage Pipeline

> How the system is built and why. For exact schemas, rules and acceptance criteria see [SPEC.md](SPEC.md).

## TL;DR

- **What it is:** a batch CLI pipeline (`python run_pipeline.py`) that reads `tickets.json` + `kb_articles.json` from disk and regenerates every artifact from scratch: retrieval → classification → drafting → escalation → validation.
- **Deterministic where it can be, LLM only where it must be.** PII masking, retrieval (TF-IDF), escalation (rules engine), safety filtering, grounding checks and validation are pure Python and reproducible. The LLM is used for exactly two stages: **classification** and **drafting**.
- **A stage machine enforces order in code.** `INIT → … → RESULTS_FINALISED`. A stage can't run unless the previous one finished and its artifact is on disk. Drafting can't run before retrieval and classification.
- **PII never reaches an LLM.** A deterministic detector masks emails, phones, cards (Luhn), IBANs (mod-97) and disclosed credentials in `TICKETS_NORMALISED`. Prompts only contain `[TYPE_n]` placeholders, and the validator checks drafts, reasons and logs for leakage.
- **Every LLM output is untrusted until validated.** The model is asked for structured JSON, the output is parsed with Pydantic models built from the code-defined taxonomy, checked against business rules (citations ⊆ retrieved, no password requests, no refund promises), and retried with error feedback or replaced with a safe fallback.
- **Easy to inspect:** one JSON artifact per stage, `llm_calls.jsonl` with a prompt hash per call, `retrieval_debug.json` explaining rankings, `grounding_flags.json` for unsupported claims, and `run_manifest.json` recording stage timings and input hashes.
- **Provider-agnostic:** one OpenAI-compatible client works with **Ollama Cloud** (`glm-5.2`, default) and **OpenAI** (`gpt-6.1-sol`), plus an offline `stub` provider for tests and CI.
- **Replayable:** content-addressed caches (retrieval keyed by ticket+KB hash, LLM keyed by prompt hash) let a rerun with a changed `tickets.json` recompute only the changed tickets.
- **Delivered and evaluated in audited stages:** [PLAN.md](PLAN.md) defines five human-signed stages, each closed with a commit and tag. Models are compared by an offline eval harness (`evals/`), outside the pipeline (§13).

---

## 1. Goals and non-goals

| Goals | Non-goals |
|---|---|
| Rerun from a clean checkout with replaced inputs | Real-time / streaming ticket intake |
| Grounded answers: only KB content, only retrieved articles cited | Sending replies to customers |
| Taxonomy enforced in code, not just in the prompt | Training or fine-tuning models |
| Stage order enforced in code | A web UI |
| Every decision traceable to inputs, evidence and prompts | Multi-tenant or distributed execution |
| Customer PII never sent to an LLM or written to artifacts/logs | Anonymisation guarantees beyond the documented PII types |
| Safe degradation: bad LLM output never reaches artifacts unvalidated | Perfect classification accuracy |

---

## 2. System context

```mermaid
flowchart LR
    subgraph Disk["Repository working dir"]
        T[tickets.json]
        K[kb_articles.json]
        ENV[.env]
        OUT[(Generated artifacts)]
        C[(.cache/)]
    end

    U([Evaluator / Operator]) -->|python run_pipeline.py| P[Ticket Triage Pipeline]
    U -->|python validate.py| V[Validator CLI]

    T --> P
    K --> P
    ENV -->|LLM_PROVIDER, keys| P
    P <--> C
    P --> OUT
    V --> OUT

    P <-->|HTTPS, OpenAI-compatible| LLM{{LLM provider<br/>OpenAI / Ollama Cloud}}
```

- The pipeline's only external dependency is the LLM provider. Everything else is local files.
- `validate.py` runs on its own, so it can check artifacts that some other process produced.

---

## 3. Architecture overview

### 3.1 Component diagram

```mermaid
flowchart TB
    CLI[run_pipeline.py<br/>CLI entrypoint] --> ORCH

    subgraph Core["pipeline/ package"]
        ORCH[orchestrator.py<br/>StageMachine + run loop]
        CFG[config.py<br/>env + defaults]
        TAX[taxonomy.py<br/>enums: IssueType, Urgency,<br/>ResolutionAction, TargetQueue]
        SCH[schemas.py<br/>Pydantic models]
        IO[io_utils.py<br/>atomic JSON writes, hashing]

        subgraph Stages["Stage implementations"]
            LOAD[loader.py]
            NORM[normalise.py]
            PII[pii.py<br/>detect + mask]
            RET[retrieval.py<br/>TF-IDF index + search]
            CLS[classify.py]
            DRF[draft.py]
            ESC[escalate.py<br/>rules engine]
            VAL[validation.py]
            FIN[finalise.py]
        end

        subgraph Support["Cross-cutting services"]
            LLM[llm.py<br/>LLMClient + providers]
            PRM[prompts.py<br/>versioned templates]
            GRD[guards.py<br/>safety filter +<br/>grounding guard]
            CACHE[cache.py<br/>content-addressed cache]
            LOG[llm_log.py<br/>llm_calls.jsonl writer]
        end
    end

    NORM --> PII
    VAL --> PII
    VCLI[validate.py<br/>CLI entrypoint] --> VAL

    ORCH --> LOAD & NORM & RET & CLS & DRF & ESC & VAL & FIN
    CLS --> LLM
    DRF --> LLM
    CLS --> PRM
    DRF --> PRM
    DRF --> GRD
    VAL --> GRD
    LLM --> LOG
    LLM --> CACHE
    RET --> CACHE
    CLS & DRF & ESC & VAL --> SCH
    SCH --> TAX
    ORCH --> CFG
    Stages --> IO
```

### 3.2 Responsibilities at a glance

| Module | Responsibility | Deterministic? |
|---|---|---|
| `orchestrator.py` | Owns the `Stage` enum, enforces transitions, runs stages, writes `run_manifest.json` | ✅ |
| `config.py` | Reads `.env` / env vars, provider + model selection, thresholds | ✅ |
| `taxonomy.py` | Single source of truth for allowed labels (Python `StrEnum`s) | ✅ |
| `schemas.py` | Pydantic models for every input and artifact; `extra="forbid"` | ✅ |
| `loader.py` | Reads and structurally validates the two input files | ✅ |
| `normalise.py` | Cleans tickets (whitespace, NFC, language default, dedupe, truncation), then calls `pii.py` | ✅ |
| `pii.py` | PII detection (email, phone, Luhn card, mod-97 IBAN, credential), stable masking, `unmask`, leakage scan used by the validator | ✅ |
| `retrieval.py` | Builds the TF-IDF index, applies the query-expansion lexicon, top-3 search, score threshold, debug terms | ✅ |
| `classify.py` | Builds the prompt, calls the LLM, validates and retries, falls back | ❌ (LLM) |
| `draft.py` | Builds the grounded prompt, calls the LLM, runs safety/citation checks, retries, falls back | ❌ (LLM) |
| `escalate.py` | Rules engine: classification + KB evidence → escalate/queue/reason | ✅ |
| `guards.py` | Unsafe-phrase detector, refund-promise detector, grounding (hallucination) guard | ✅ |
| `validation.py` | Cross-artifact checks → `validation_report.json` | ✅ |
| `llm.py` | Provider abstraction (OpenAI, Ollama, stub), per-provider parameter adapter, timeouts, retries, JSON mode | — |
| `cache.py` | Content-addressed read/write under `.cache/` | ✅ |
| `llm_log.py` | Appends one JSON line per LLM call to `llm_calls.jsonl` | ✅ |

---

## 4. Pipeline stages and control flow

### 4.1 State machine

```mermaid
stateDiagram-v2
    [*] --> INIT
    INIT --> INPUTS_LOADED: load + schema-check inputs
    INPUTS_LOADED --> KB_INDEXED: build TF-IDF index
    KB_INDEXED --> TICKETS_NORMALISED: clean + dedupe + mask PII
    TICKETS_NORMALISED --> EVIDENCE_RETRIEVED: top-3 per ticket
    EVIDENCE_RETRIEVED --> TICKETS_CLASSIFIED: LLM + taxonomy validation
    TICKETS_CLASSIFIED --> RESPONSES_DRAFTED: LLM + safety/citation checks
    RESPONSES_DRAFTED --> ESCALATIONS_DECIDED: rules engine
    ESCALATIONS_DECIDED --> OUTPUTS_VALIDATED: cross-artifact validation
    OUTPUTS_VALIDATED --> RESULTS_FINALISED: manifest + summary
    RESULTS_FINALISED --> [*]

    INIT --> FAILED: fatal error
    INPUTS_LOADED --> FAILED
    KB_INDEXED --> FAILED
    TICKETS_NORMALISED --> FAILED
    EVIDENCE_RETRIEVED --> FAILED
    TICKETS_CLASSIFIED --> FAILED
    RESPONSES_DRAFTED --> FAILED
    ESCALATIONS_DECIDED --> FAILED
    OUTPUTS_VALIDATED --> FAILED
    FAILED --> [*]
```

**How order is enforced in code**

- `Stage` is an ordered `IntEnum`. `StageMachine.advance(to)` raises `StageOrderError` unless `to == current + 1`.
- Every stage function is registered with `@stage(Stage.X, requires=[...artifacts])`. Before it runs, the orchestrator checks that the machine is at `X − 1` and that each required artifact exists and parses.
- Stages receive their inputs **as typed objects returned by earlier stages**, not as globals, so drafting physically can't run without `RetrievalResult` and `Classification` objects.
- `FAILED` covers *fatal* errors only (unreadable input, empty KB file with invalid structure, an artifact write error). Per-ticket LLM failures are **not** fatal: they fall back and get flagged.

### 4.2 End-to-end sequence

```mermaid
sequenceDiagram
    autonumber
    participant CLI as run_pipeline.py
    participant O as Orchestrator
    participant R as Retrieval
    participant C as Classifier
    participant D as Drafter
    participant L as LLMClient
    participant G as Guards
    participant E as Escalation
    participant V as Validator
    participant FS as Disk

    CLI->>O: run(config)
    O->>FS: read tickets.json, kb_articles.json
    O->>R: build_index(articles)
    O->>O: normalise(tickets) + mask PII
    loop each ticket
        O->>R: search(ticket, k=3)
        R-->>O: RetrievalResult (+ debug terms)
    end
    O->>FS: retrieval_results.json, retrieval_debug.json

    loop each ticket
        O->>C: classify(ticket, evidence)
        C->>L: chat(json_schema prompt)
        L->>FS: append llm_calls.jsonl
        L-->>C: raw JSON
        C->>C: Pydantic + taxonomy validation (retry ≤2)
        C-->>O: Classification
    end
    O->>FS: ticket_classification.json

    loop each ticket
        O->>D: draft(ticket, evidence, classification)
        D->>L: chat(grounded prompt)
        L->>FS: append llm_calls.jsonl
        L-->>D: {draft_response, citations}
        D->>G: safety + citation + grounding checks
        G-->>D: ok / violations (retry ≤2, then fallback)
        D-->>O: Draft
    end
    O->>FS: draft_responses.json, grounding_flags.json

    O->>E: decide(classification, evidence)
    E-->>O: Escalation[]
    O->>FS: escalations.json

    O->>V: validate(all artifacts)
    V->>FS: validation_report.json
    O->>FS: run_manifest.json
    O-->>CLI: exit 0 (valid) / 1 (validation errors)
```

---

## 5. Data flow and artifacts

```mermaid
flowchart LR
    T[tickets.json] --> L1[load]
    K[kb_articles.json] --> L1
    L1 --> IDX[KB index<br/>artifacts/kb_index.json]
    L1 --> N[normalise] --> NT[artifacts/normalised_tickets.json]

    NT --> RET[retrieve]
    IDX --> RET
    RET --> RR[retrieval_results.json]
    RET --> RD[retrieval_debug.json]

    NT --> CLS[classify]
    RR --> CLS
    K --> CLS
    CLS --> TC[ticket_classification.json]

    NT --> DRF[draft]
    RR --> DRF
    K --> DRF
    TC --> DRF
    DRF --> DR[draft_responses.json]
    DRF --> GF[grounding_flags.json]

    TC --> ESC[escalate]
    RR --> ESC
    K --> ESC
    ESC --> EJ[escalations.json]

    CLS -.-> LJ[llm_calls.jsonl]
    DRF -.-> LJ

    RR & TC & DR & EJ & LJ --> VAL[validate]
    VAL --> VR[validation_report.json]
    VAL --> MF[artifacts/run_manifest.json]
```

- **Required artifacts** are written to the repo root (where the evaluator looks).
- **Intermediate artifacts** (`kb_index.json`, `normalised_tickets.json`, `run_manifest.json`) go to `artifacts/`.
- All writes are **atomic** (write to `*.tmp`, then `os.replace`), so a crash never leaves half-written JSON.
- Every artifact is **ordered by input ticket order** and includes every ticket, including ones that failed and fell back.

---

## 6. Component design

### 6.1 Loading and normalisation

- `loader.py` parses JSON and validates it against `TicketsFile` / `KBFile` Pydantic models. Unknown extra fields are **kept** (forward-compatible inputs) but ignored.
- `normalise.py`, deterministically and per ticket:
  - Unicode NFC, collapse whitespace, strip control characters.
  - `language`: lowercase, BCP-47 primary subtag (`en-GB → en`). Missing → `en` with a `normalisation_note`.
  - `customer_tier`: lowercase; unknown values are kept but flagged.
  - Empty `subject` **and** `message` → marked `insufficient_content=true`, so classification is steered to `request_more_info`.
  - Message truncated to `MAX_TICKET_CHARS` (default 4000), with a note.
  - Duplicate `ticket_id`: the first occurrence wins and later ones are logged in the manifest. Output keys must be unique.
  - PII detection and masking (§6.11) runs last, so every later stage only sees masked text.
- Normalisation never changes meaning. It only exists to make the next stages robust. It is idempotent: `normalise(normalise(x)) == normalise(x)`.

### 6.2 Retrieval (deterministic)

```mermaid
flowchart LR
    A[KB article] --> F["Field text:<br/>title ×3 + category ×2 + content"]
    F --> TOK[tokenise<br/>lowercase, strip punctuation,<br/>stopwords, light stemming]
    TOK --> VEC[TF-IDF vectoriser<br/>unigrams + bigrams<br/>sublinear tf, L2 norm]
    VEC --> M[(Doc-term matrix)]

    Q[Masked ticket subject ×2 + message<br/>+ expansion terms] --> TOK2[same tokeniser] --> QV[query vector]
    QV --> COS[cosine similarity]
    M --> COS
    COS --> SORT["sort: score desc,<br/>then article_id asc (tie-break)"]
    SORT --> TH{score ≥ MIN_SCORE?}
    TH -->|yes| TOP[take top 3]
    TH -->|no| EMPTY[drop]
    TOP --> OUT[retrieved_articles]
    EMPTY --> OUT
```

- **Why TF-IDF over embeddings:** fully deterministic, no extra API calls or model downloads, transparent for the debug artifact, and strong enough on a small KB with distinctive vocabulary (`invoice`, `password`, `charge`). The retriever sits behind a `Retriever` protocol, so a BM25 or embedding retriever can be swapped in later.
- **Implementation:** `scikit-learn` `TfidfVectorizer` with a fixed vocabulary order (sorted). Same inputs → same scores, bit for bit.
- **Field weighting:** fields are repeated (title ×3, category ×2) because titles are short and highly informative.
- **Non-English tickets:** TF-IDF cannot match es/fr/de/pt text to the English KB. A small, versioned, deterministic lexicon (`pipeline/lexicon/query_expansion.v1.json`, e.g. `contraseña → password`, `factura → invoice`) appends English KB terms to the query. It needs no LLM call and no download, and the added terms are shown in `retrieval_debug.json`. Multilingual embeddings were rejected as heavier and less explainable. If expansion finds nothing, retrieval returns `[]` and C3 escalates.
- **Threshold:** `MIN_SCORE = 0.05` (configurable; the Stage 2 threshold sweep justifies the final value). Below it, an article is "no useful match". A ticket can end up with **0–3** articles; an empty list is valid and handled downstream.
- **Diagnostics:** for each hit, the top contributing terms (`q_weight × d_weight`) and a matched snippet (the KB sentence with the most query-term overlap) go to `retrieval_debug.json`.

### 6.3 LLM client

```mermaid
classDiagram
    class LLMClient {
        +provider: str
        +model: str
        +complete_json(stage, ticket_id, messages, schema, inputs, output) LLMResult
    }
    class Provider {
        <<interface>>
        +chat(messages, schema, params) str
    }
    class OpenAIProvider {
        base_url = api.openai.com/v1
        response_format = json_schema
        token param = max_completion_tokens
    }
    class OllamaProvider {
        base_url = OLLAMA_BASE_URL (/v1)
        response_format = json_object
        token param = max_tokens
    }
    class StubProvider {
        deterministic rule-based
        no network
    }
    class LLMResult {
        +raw_text: str
        +parsed: dict
        +prompt_hash: str
        +cached: bool
        +latency_ms: int
    }
    LLMClient --> Provider
    Provider <|.. OpenAIProvider
    Provider <|.. OllamaProvider
    Provider <|.. StubProvider
    LLMClient --> LLMResult
    LLMClient ..> CallLogger : logs every call
    LLMClient ..> Cache : prompt_hash lookup
```

- Both real providers use the official `openai` SDK; only `base_url`, `api_key` and `model` differ.
- **Parameters:** `temperature=0`, `seed=42` (where supported), a token limit large enough for reasoning models (default 1500), 60 s timeout. A per-provider adapter sends it as `max_completion_tokens` to OpenAI and `max_tokens` to Ollama. Model IDs accept a `:cloud` suffix (Ollama CLI convention), which is stripped before the API call.
- **Models:** the pipeline default is `ollama` / `glm-5.2`; `openai` / `gpt-6.1-sol` is selectable. Evals always use two other models (§13), so the system is never graded by the model it was tuned on.
- **Structured output:** OpenAI uses `response_format={"type":"json_schema", strict}` generated from the Pydantic model. Ollama uses `json_object`, and the schema is spelled out in the prompt. Either way, the **Pydantic validation in our code is the real gate**.
- **Transport retries:** exponential backoff on 429/5xx/timeouts (3 attempts). These are separate from *content* retries (§6.4).
- **`prompt_hash`** = `sha256(canonical_json({provider, model, params, messages, prompt_version}))`. It's used for cache keys and for the log.
- **`StubProvider`:** a keyword-rule classifier and template drafter, so the pipeline and test suite run offline. It's selected with `LLM_PROVIDER=stub`, and its log entries say `provider: "stub"`.

### 6.4 Classification

```mermaid
flowchart TD
    IN[ticket + top-3 snippets] --> P[build prompt<br/>taxonomy injected from enums<br/>'do not invent categories']
    P --> CALL[LLM call]
    CALL --> PARSE{JSON parse}
    PARSE -->|fail| RETRY
    PARSE -->|ok| PYD{Pydantic + enum validation}
    PYD -->|fail| RETRY
    PYD -->|ok| BIZ{"business checks<br/>ticket_id matches<br/>refund keywords → requires_refund_caution"}
    BIZ -->|fail| RETRY
    BIZ -->|ok| OK[Classification ✅]
    RETRY{"attempt &lt; 3?"} -->|yes| FB["re-prompt with<br/>validation errors appended"] --> CALL
    RETRY -->|no| SAFE["safe fallback:<br/>other / medium /<br/>needs_human_escalation<br/>fallback=true"]
```

- **Prompt contents (required by the brief):** ticket fields, retrieved article snippets (`article_id`, title, category, content), the allowed values for every field (rendered from `taxonomy.py`, so prompt and validator can never drift), and an explicit "use only these values; do not invent categories" instruction.
- **Prompt-injection hygiene:** ticket text goes inside clearly delimited `<ticket>` tags, with an instruction to treat it as data.
- **Masked input only:** the ticket text in the prompt is the masked text from `normalised_tickets.json` (§6.11).
- **Deterministic post-rules (code overrides the model):**
  - The refund/charge lexicon in the ticket or evidence forces `requires_refund_caution=true`.
  - `insufficient_content` forces `resolution_action=request_more_info`, unless the model escalates.
  - With zero retrieved articles, `answer_from_kb` is downgraded to `needs_human_escalation`, because nothing grounds the answer.
  - A disclosed credential (C5) forces `customer_sensitive=true`.
- Overrides are recorded in the record's `rationale` suffix and in the manifest, so they stay visible.

### 6.5 Grounded drafting

- **Inputs:** normalised ticket, the **full text of retrieved articles only**, and the validated classification. The model never sees the rest of the KB.
- **Prompt rules:** answer in `ticket.language`; use only facts from the provided articles; cite the `article_id`s used; don't promise refunds, timelines or actions the KB doesn't state; never ask for passwords, card numbers, CVV or OTP codes; never repeat personal data, and refer to it generically ("the email address you provided") because the model only sees placeholders; if `resolution_action == needs_human_escalation`, say the ticket is being escalated to the relevant team; if `request_more_info`, ask only for safe details (order ID, date, screenshot).
- **Output:** `{"draft_response": str, "citations": [article_id]}`.
- **Post-checks, run by `guards.py` after each attempt:**
  1. `citations ⊆ retrieved_ids`. Invalid IDs are a violation (they're not silently dropped).
  2. Safety filter: regex patterns for credential requests in multiple languages (§6.7).
  3. Refund-promise detector, when `requires_refund_caution` is set.
  4. Escalation mention present when required.
  5. Non-empty, length ≤ `MAX_DRAFT_CHARS`.
  6. No raw PII and no `[TYPE_n]` placeholders (V13/V14 logic from `pii.py`).
  7. When a credential disclosure was detected (C5), the "never share your password" advice is present.
- If a check fails, the drafter re-prompts with the violations (up to 2 retries). After that it uses a **deterministic fallback template** in the ticket language (en default) that acknowledges the issue, states escalation, and cites nothing beyond what was retrieved. It's marked `fallback=true`.
- The **grounding guard** (§6.8) runs on the accepted draft and writes flags. It doesn't block, because it's a heuristic, but flags appear in the validation report.

### 6.6 Escalation rules engine (deterministic)

The escalation decision is **not** an LLM call. It's a pure function of the classification and the retrieved evidence, so it's auditable and reproducible.

```mermaid
flowchart TD
    S[classification + evidence] --> E1{E1: resolution_action ==<br/>needs_human_escalation?}
    E1 -->|yes| Q[route to queue]
    E1 -->|no| E2{E2: urgency == critical?}
    E2 -->|yes| Q
    E2 -->|no| E3{E3: classification<br/>was a fallback?}
    E3 -->|yes| Q
    E3 -->|no| N["E4/E5: escalate=false<br/>target_queue=none"]

    Q --> Q1{"Q1: retrieved article with<br/>category == issue_type has<br/>'escalate to &lt;team&gt;' clause?"}
    Q1 -->|yes| KQ["map team → queue<br/>quote clause in reason"]
    Q1 -->|no| Q2{Q2: issue_type}
    Q2 -->|billing| BO[billing_ops]
    Q2 -->|account_access| AS[account_support]
    Q2 -->|technical_problem / how_to / other| GS[general_support]
```

- **Split of responsibilities:** the *whether* comes from the validated classification. Its prompt includes each retrieved article's escalation conditions, and C3 forces escalation when there's no evidence. The *where* and *why* come from the KB evidence. Word-overlap matching of KB conditions against ticket text was rejected because it's fragile: "two charges… order" falsely matches KB-001's "two *settled* charges" condition.
- **KB-driven routing (Q1):** retrieved article content is scanned for `escalate to <team>` phrases, and team names map to queues (`billing ops|billing support → billing_ops`, `account support → account_support`). The clause is quoted in `reason`, which grounds the decision in retrieved evidence.
- **Built-in rules from the brief:**
  - Login failure after a successful reset → the classifier is guided to `needs_human_escalation` by KB-002's condition, and Q1 routes it to `account_support`.
  - Duplicate charge / refund → if escalated, the reason must use non-committal wording ("verify settlement status"), never "refund due". This is enforced by the refund-promise detector on `reason` (SPEC E-INV3).
- **PII-safe reasons:** a `reason` never contains PII or placeholders (SPEC E-INV4).
- **Invariant:** `escalate=false ⇔ target_queue="none"`. It's enforced by a Pydantic `model_validator` and checked again by the validator.
- Every `reason` cites the rule ID that fired (e.g. `R1:classification_requires_escalation`, `R2:kb_escalation_condition[KB-002]`) for traceability.

### 6.7 Safety filter

- Multilingual regex lexicon (en, es, fr, de, pt plus a generic fallback) for:
  - credential requests: `(send|share|provide|tell|confirm) … (password|passcode|PIN|OTP|2FA code|CVV|card number)`
  - refund guarantees: `(we will|we'll|you will) … refund`, `refund (has been|is) (issued|processed|approved)`, `guarantee … refund`
- The same lexicon is used by `draft.py` (to block) and by `validation.py` (to verify), so there's one source of truth.
- "Never share your password" is **allowed**. Negation-aware patterns check for `never|do not|don't` before the verb, which avoids false positives on the KB's own advice.

### 6.8 Grounding (hallucination) guard

```mermaid
flowchart LR
    D[draft text] --> SPL[split into sentences]
    SPL --> CL{"is it a concrete claim?<br/>numbers/durations · UI paths 'X > Y'<br/>commitment verbs 'will / can be / available'"}
    CL -->|no| SKIP[ignore]
    CL -->|yes| SUP{"supported by cited KB text?<br/>numbers/paths must appear verbatim<br/>content-word overlap ≥ 0.5"}
    SUP -->|yes| NEG{supporting sentence<br/>contains a negation?}
    NEG -->|no| OKK[supported]
    NEG -->|yes| FLAG
    SUP -->|no| FLAG[flag → grounding_flags.json]
```

- A simple heuristic, as the brief allows. It flags rather than blocks, and every flag records the sentence, the claim type, the cited articles checked, and the overlap score.
- **Negation rule:** a KB sentence containing a negation ("should not be promised") never counts as support for a commitment, so "refunds can be issued" is not backed by "refunds should not be promised".
- Example: "Your pending charge will disappear within 24 hours" is flagged, because `24 hours` isn't in KB-001, which says "3-5 business days".

### 6.9 Validation

- `validation.py` is a library used by both the `OUTPUTS_VALIDATED` stage and the standalone `validate.py` CLI.
- It's **independent of in-memory state**: it re-reads everything from disk, so it validates what was actually written. V13 runs the PII detector over drafts, reasons and `llm_calls.jsonl`; V14 rejects placeholders in drafts and reasons.
- Each check has a stable ID (`V01`…`V14`, see SPEC §8) with a `pass`/`fail`/`warn` status and per-ticket details, so failures can be acted on.
- Exit code: `0` if there are no `fail`s, `1` otherwise. `warn`s (e.g. grounding flags) don't fail the run.

### 6.10 Caching and replayability (stretch)

```mermaid
flowchart TD
    START[rerun] --> H1["kb_hash = sha256(kb_articles.json canonical)<br/>cfg_hash = sha256(retrieval config + code version)"]
    H1 --> LOOP{for each ticket}
    LOOP --> H2["t_hash = sha256(normalised ticket)"]
    H2 --> RK{"retrieval cache hit?<br/>.cache/retrieval/kb_hash/cfg_hash/t_hash.json"}
    RK -->|hit| REUSE[reuse retrieval result]
    RK -->|miss| COMP[compute + store]
    REUSE & COMP --> LLMK{"LLM cache hit?<br/>.cache/llm/prompt_hash.json"}
    LLMK -->|hit| LREUSE[reuse LLM output<br/>log cached=true]
    LLMK -->|miss| LCALL[call provider + store]
```

- The cache is **content-addressed**: changing a ticket's text, the KB, the prompt template version or the model changes the key, so stale results can't leak.
- The KB index is rebuilt on every run because it's cheap (milliseconds). Only per-ticket results are cached.
- `--no-cache` forces a full recompute. `.cache/` is git-ignored, so a clean checkout always recomputes.
- **Artifacts are always fully rewritten**, cache or not, so outputs reflect exactly the current inputs.

### 6.11 PII protection

```mermaid
flowchart LR
    RAW[raw ticket text] --> DET["pii.py detect<br/>email · phone · card (Luhn)<br/>IBAN (mod-97) · credential"]
    DET --> MASK["mask → [EMAIL_1] [CARD_NUMBER_1] …<br/>stable, idempotent"]
    MASK --> NT[normalised_tickets.json<br/>masked text + pii_summary<br/>salted hashes]
    NT --> RET[retrieval]
    NT --> LLM[classification + drafting prompts]
    LLM --> DRAFT[draft]
    DRAFT --> LEAK{"V13/V14: any PII or<br/>placeholder in draft,<br/>reason or llm log?"}
    LEAK -->|yes| BLOCK[block + retry → fallback template]
    LEAK -->|no| OK[accepted]
```

- **Where:** inside `TICKETS_NORMALISED`, so the raw text exists only in the loaded input and in memory. Nothing downstream ever reads it.
- **Detection is deterministic** and tuned against `data/fixtures/pii_cases.json`, including false-positive guards (order IDs, dates, amounts, error codes, Luhn-/mod-97-invalid digit runs).
- **`unmask` is test-only.** The placeholder → value map is held in memory during the stage and not persisted, so `unmask(mask(x)) == x` is provable without a stored secret.
- **Credentials:** a disclosed password/PIN/OTP triggers C5 (`customer_sensitive=true`) and the drafter must include the "never share your password" advice.
- **Logs:** `llm_calls.jsonl` stores hashes, not prompts. `--log-prompts` writes masked prompts only.
- **Outputs:** drafts refer to PII generically; placeholders are blocked because they would look broken to a customer.

---

## 7. Error handling strategy

| Failure | Scope | Behaviour |
|---|---|---|
| Input file missing / invalid JSON / wrong top-level shape | Fatal | `FAILED`, clear message, exit 2 |
| Individual ticket malformed (missing `ticket_id`) | Ticket | skipped, recorded in manifest `rejected_tickets` |
| No KB articles at all | Run | allowed: every retrieval is empty → escalations follow the rules |
| Retrieval finds nothing | Ticket | `retrieved_articles: []`, draft cites nothing, `answer_from_kb` disallowed |
| LLM transport error (429/5xx/timeout) | Call | backoff retry ×3, then treated as content failure |
| LLM returns invalid JSON / taxonomy / unsafe text | Ticket | content retry ×2 with error feedback, then safe fallback `fallback=true` |
| Missing API key | Run | fatal, unless `LLM_PROVIDER=stub` |
| Artifact write error | Fatal | `FAILED` (atomic writes keep previous files intact) |

---

## 8. Observability

- **`llm_calls.jsonl`:** one line per call, with the required fields plus `attempt`, `cached`, `latency_ms`, `status`, `prompt_version` and `ticket_ids`. Prompts aren't stored inline (only the hash). With `--log-prompts`, full **masked** prompts go to `artifacts/prompts/{prompt_hash}.json` for debugging.
- **`run_manifest.json`:** run ID, start/end timestamps, per-stage duration, input file hashes, provider/model, counts (tickets, fallbacks, overrides, cache hits, flags, PII detections by type), and the final stage reached.
- **Console:** a one-line progress line per stage and a final summary table.

---

## 9. Technology choices

| Concern | Choice | Why |
|---|---|---|
| Language | Python 3.11+ (dev on 3.14) | Preferred by the brief; `StrEnum`, modern typing |
| Schemas | Pydantic v2 | Strict validation, JSON Schema generation for structured output |
| Retrieval | scikit-learn `TfidfVectorizer` | Deterministic, explainable, no network |
| LLM SDK | `openai` ≥ 1.x | One client for OpenAI and Ollama's `/v1` API |
| Default model | `glm-5.2` (Ollama Cloud) | Verified working; set by `LLM_PROVIDER=ollama` (default) |
| Fast dev model | `glm-5.3-flash` (Ollama Cloud) | Substitute for the non-existent `glm-5.2-flash` |
| Alt / eval model A | `gpt-6.1-sol` (OpenAI) | Verified working; needs `max_completion_tokens`; `LLM_PROVIDER=openai` |
| Eval model B | `deepseek-v4.1-flash` (Ollama Cloud) | Verified working; used by the eval harness |
| PII | stdlib `re` + Luhn / mod-97 checks | Deterministic, no model download |
| Config | `python-dotenv` | Reads `.env`, which isn't committed |
| Tests | `pytest` + `StubProvider` | Offline, deterministic CI |

---

## 10. Repository layout

```text
ticket-classification/
├── run_pipeline.py            # CLI: full run
├── validate.py                # CLI: standalone validation
├── pipeline/
│   ├── orchestrator.py        # Stage enum, StageMachine, Pipeline run loop, manifest builder
│   ├── stages.py              # stage functions + registry (unbuilt stages are placeholders)
│   ├── runner.py              # runs the pipeline, maps errors to exit codes, always writes the manifest
│   ├── config.py
│   ├── taxonomy.py
│   ├── schemas.py
│   ├── io_utils.py
│   ├── loader.py
│   ├── normalise.py
│   ├── pii.py
│   ├── retrieval.py
│   ├── llm.py
│   ├── llm_log.py
│   ├── prompts.py
│   ├── classify.py
│   ├── draft.py
│   ├── escalate.py
│   ├── guards.py
│   ├── validation.py
│   ├── cache.py
│   ├── finalise.py
│   └── lexicon/
│       └── query_expansion.v1.json
├── tests/                     # unit + end-to-end (stub provider), markers stage1…stage5
├── evals/                     # offline eval harness (never run by run_pipeline.py)
├── scripts/                   # audit_stage<N>.py: runs a stage's AI audit, writes audit/stage-N/
├── data/                      # eval set, gold labels, fixtures (see data/README.md)
├── audit/                     # per-stage audit reports, FINAL_REPORT.md (committed)
├── tickets.json               # input
├── kb_articles.json           # input
├── retrieval_results.json     # ┐
├── retrieval_debug.json       # │
├── ticket_classification.json # │ generated at repo root
├── draft_responses.json       # │ (required artifacts)
├── grounding_flags.json       # │
├── escalations.json           # │
├── validation_report.json     # │
├── llm_calls.jsonl            # ┘
├── artifacts/                 # intermediate artifacts + manifest
├── .cache/                    # replay cache (git-ignored)
├── requirements.txt           # runtime deps · requirements-dev.txt adds pytest/pytest-cov
├── pytest.ini
├── README.md · DESIGN.md · SPEC.md · PLAN.md · PROBLEM.md
└── .env                       # API keys (git-ignored)
```

---

## 11. Key design decisions and trade-offs

| # | Decision | Alternative | Rationale |
|---|---|---|---|
| D1 | Escalation via a deterministic rules engine | LLM decides escalation | Brief requires grounding in classification + evidence; rules are auditable and reproducible |
| D2 | TF-IDF retrieval | Embeddings | Determinism, explainability, zero setup; swappable behind a protocol |
| D3 | One LLM call per ticket per stage | Batch calls | Simple per-ticket validation, retry and traceability; ticket counts are small |
| D4 | Code-level overrides of LLM fields | Trust the model | Safety-critical flags (refund caution, no-evidence) shouldn't depend on model compliance |
| D5 | Grounding guard flags, doesn't block | Block on any flag | Heuristic has false positives; blocking would cause needless fallbacks |
| D6 | Validator re-reads from disk | Validate in-memory objects | Proves the *written* artifacts are correct; usable standalone |
| D7 | Safe fallback instead of crashing | Fail the run | Every ticket must appear in every artifact; fallbacks are explicit and counted |
| D8 | Taxonomy rendered into prompts from enums | Hard-coded prompt text | Prompt and validator can never disagree |
| D9 | Mask PII before any LLM or retrieval sees it | Redact only in outputs / trust the provider | Raw PII then exists nowhere downstream; leakage becomes checkable |
| D10 | Multilingual query-expansion lexicon for retrieval | Multilingual embeddings | Stays deterministic and explainable; no model download. Embeddings remain a swap-in behind the `Retriever` protocol |
| D11 | Evals use two models different from the dev model, cross-judged, offline | Grade with the dev model / run evals in the pipeline | Avoids self-preference and tuning on the grader; keeps the pipeline run deterministic and cheap |

---

## 12. Risks and mitigations

| Risk | Mitigation |
|---|---|
| Model ignores the taxonomy or invents a category | Strict schema + Pydantic enums + retry with errors + fallback |
| Model promises refunds or asks for passwords | Prompt rules + regex guards + retry + template fallback + validator check |
| Model cites a non-retrieved article | Citation subset check blocks the draft; validator re-checks |
| Replaced inputs with different languages | Language-aware prompts; multilingual safety lexicon; template fallback |
| Prompt injection inside ticket text | Delimited data blocks; deterministic guards run regardless of model output |
| PII sent to a provider or leaked into drafts/logs | Deterministic masking before retrieval and prompts; V13/V14 validation; hashes instead of prompts in logs |
| PII detector misses a format or over-masks (order IDs, amounts) | Fixture-driven tests incl. false-positive guards; the Stage 1 human audit reviews the masking report |
| Non-English ticket matches nothing in an English KB | Versioned expansion lexicon; C3 escalates when still empty |
| Provider outage / rate limits | Backoff retries; cache; `stub` provider for offline runs |
| Non-determinism between runs | `temperature=0`, seed, cache; deterministic stages around the LLM |

---

## 13. Evaluation and delivery

The pipeline itself never evaluates models. Evaluation is offline tooling in `evals/`, driven by the staged plan in [PLAN.md](PLAN.md).

```mermaid
flowchart LR
    G[(data/eval/<br/>tickets + KB + gold)] --> DET[Deterministic stages<br/>normalise + PII + retrieval<br/>frozen, identical inputs]
    DET --> A[gpt-6.1-sol as pipeline LLM]
    DET --> B[deepseek-v4.1-flash as pipeline LLM]
    A --> SA[Deterministic scorers vs gold]
    B --> SB[Deterministic scorers vs gold]
    A -->|drafts| JB[judge: deepseek-v4.1-flash]
    B -->|drafts| JA[judge: gpt-6.1-sol]
    SA & SB & JA & JB --> R[audit/stage-N/evals/report.md]
```

- **Same frozen inputs for both models**, so differences come from the model alone. Results are cached by prompt hash.
- **Cross-judging** avoids self-preference. Judge authority is gated on human calibration (SPEC EV6).
- **Stages 0–5** each have AI gates (`pytest -m stageN` plus evals) and a human audit. A stage is closed only by a human sign-off, followed by a commit and an annotated tag `stage-N-closed` containing the stage's code and `audit/stage-N/` reports.
- The dev model (`glm-5.2`) numbers are reported for information only.
