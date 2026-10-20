"""Stage implementations and the stage registry.

Each function takes the ``RunContext``, reads typed inputs from ``ctx.data`` (put there by earlier
stages), writes its artifact atomically, and records facts for the manifest.
"""

from collections import Counter

from pipeline.cache import JsonCache
from pipeline.classify import OUTPUT_ARTIFACT as CLASSIFICATION, classify_ticket
from pipeline.config import Config
from pipeline.draft import OUTPUT_ARTIFACT as DRAFTS, draft_ticket
from pipeline.escalate import decide
from pipeline.finalise import cache_report
from pipeline.grounding import check_grounding
from pipeline.io_utils import atomic_write_json, atomic_write_text, canonical_json, sha256_canonical
from pipeline.llm import ChatProvider, LiteLLMProvider, LLMClient
from pipeline.loader import load_inputs
from pipeline.normalise import normalise_article, normalise_tickets
from pipeline.orchestrator import RunContext, Stage, StageSpec, utc_now
from pipeline.retrieval import (
    RETRIEVAL_VERSION,
    CachedEmbedder,
    Embedder,
    LiteLLMEmbedder,
    build_retriever,
    kb_hash,
    retrieve,
)
from pipeline.schemas import RetrievalResult

from pipeline.stub import StubProvider
from pipeline.validation import validate

NORMALISED_TICKETS = "artifacts/normalised_tickets.json"
KB_INDEX = "artifacts/kb_index.json"
EMBEDDING_CALLS = "artifacts/embedding_calls.jsonl"
RETRIEVAL_RESULTS = "retrieval_results.json"
RETRIEVAL_DEBUG = "retrieval_debug.json"
LLM_CALLS = "llm_calls.jsonl"
GROUNDING_FLAGS = "grounding_flags.json"
ESCALATIONS = "escalations.json"
VALIDATION_REPORT = "validation_report.json"


def make_embedder(config: Config) -> Embedder:
    """Factory for the embedding backend (tests replace it with an offline fake)."""
    return LiteLLMEmbedder(config.embedding_model, timeout_s=config.timeout_s)


def make_chat_provider(config: Config) -> ChatProvider:
    """Factory for the LLM backend (tests replace it with scripted fakes)."""
    if config.provider == "stub":
        return StubProvider()
    return LiteLLMProvider(config.provider, config.model, timeout_s=config.timeout_s)


def make_llm_client(ctx: RunContext) -> LLMClient:
    config = ctx.config
    return LLMClient(
        provider=make_chat_provider(config),
        max_tokens=config.max_tokens,
        temperature=config.temperature,
        log_path=ctx.path(LLM_CALLS),
        clock=utc_now,
        cache=JsonCache(config.cache_dir, read_enabled=not config.no_cache),
        current_stage=lambda: ctx.entering,
        prompts_dir=config.artifacts_dir / "prompts" if config.log_prompts else None,
    )


def init(ctx: RunContext) -> None:
    ctx.config.out_dir.mkdir(parents=True, exist_ok=True)
    ctx.config.artifacts_dir.mkdir(parents=True, exist_ok=True)
    # llm_calls.jsonl reflects the current run only (SPEC §6.8).
    atomic_write_text(ctx.path(LLM_CALLS), "")


def inputs_loaded(ctx: RunContext) -> None:
    loaded = load_inputs(ctx.config.tickets_path, ctx.config.kb_path)
    ctx.data["inputs"] = loaded
    ctx.manifest["inputs"] = {"tickets": loaded.tickets_file.as_dict(), "kb": loaded.kb_file.as_dict()}
    ctx.manifest["rejected_tickets"] = loaded.rejected_tickets
    ctx.manifest["duplicate_tickets"] = loaded.duplicate_tickets
    ctx.manifest["rejected_articles"] = loaded.rejected_articles
    ctx.manifest["duplicate_articles"] = loaded.duplicate_articles
    ctx.manifest["counts"] = {
        "tickets_input": loaded.tickets_input_count,
        "tickets_accepted": len(loaded.tickets),
        "tickets_rejected": len(loaded.rejected_tickets),
        "tickets_duplicate": len(loaded.duplicate_tickets),
        "articles_input": loaded.articles_input_count,
        "articles_accepted": len(loaded.articles),
    }


def kb_indexed(ctx: RunContext) -> None:
    config = ctx.config
    articles = [normalise_article(raw) for raw in ctx.data["inputs"].articles]
    embedder = None
    if config.retriever == "embedding":
        cache = JsonCache(config.cache_dir, read_enabled=not config.no_cache)
        embedder = CachedEmbedder(make_embedder(config), cache, clock=utc_now)
    retriever = build_retriever(config.retriever, articles, embedder)
    description = retriever.describe()
    settings = {
        "retrieval_version": RETRIEVAL_VERSION,
        **{k: v for k, v in description.items() if k != "vocabulary_size"},
        "top_k": config.top_k,
        "min_score": config.effective_min_score,
    }
    ctx.data.update(articles=articles, retriever=retriever, embedder=embedder)
    ctx.data["kb_hash"] = kb_hash(articles)
    ctx.data["retrieval_config_hash"] = "sha256:" + sha256_canonical(settings)
    ctx.data["retrieval_settings"] = settings
    atomic_write_json(
        ctx.path(KB_INDEX),
        {
            "schema_version": 1,
            "kb_hash": ctx.data["kb_hash"],
            "config_hash": ctx.data["retrieval_config_hash"],
            **description,
            "top_k": config.top_k,
            "min_score": config.effective_min_score,
            "retrieval_version": RETRIEVAL_VERSION,
            "articles": [
                {"article_id": a.article_id, "category": a.category, "title": a.title} for a in articles
            ],
        },
    )
    ctx.manifest["counts"]["articles_indexed"] = len(articles)


def tickets_normalised(ctx: RunContext) -> None:
    loaded = ctx.data["inputs"]
    tickets = normalise_tickets(loaded.tickets, ctx.config.max_ticket_chars, ctx.config.pii_salt)
    ctx.data["tickets"] = tickets
    atomic_write_json(
        ctx.path(NORMALISED_TICKETS),
        {"schema_version": 1, "tickets": [t.model_dump(mode="json") for t in tickets]},
    )
    pii_types: Counter[str] = Counter(entry.type.value for t in tickets for entry in t.pii_summary)
    ctx.manifest["counts"].update(
        {
            "tickets_insufficient_content": sum(t.insufficient_content for t in tickets),
            "tickets_truncated": sum(t.truncated for t in tickets),
            "tickets_with_pii": sum(bool(t.pii_summary) for t in tickets),
            "pii_detections": dict(sorted(pii_types.items())),
        }
    )


def evidence_retrieved(ctx: RunContext) -> None:
    """Top-k evidence per ticket, reusing cached results for unchanged tickets (R1)."""
    config = ctx.config
    retriever = ctx.data["retriever"]
    cache = JsonCache(config.cache_dir, read_enabled=not config.no_cache)
    key_prefix = ("retrieval", ctx.data["kb_hash"], ctx.data["retrieval_config_hash"])
    cached_entries = {t.content_hash: cache.get(*key_prefix, t.content_hash) for t in ctx.data["tickets"]}
    if hasattr(retriever, "prefetch"):
        retriever.prefetch([t for t in ctx.data["tickets"] if cached_entries[t.content_hash] is None])
    results, debug_entries = [], []
    for ticket in ctx.data["tickets"]:
        cached = cached_entries[ticket.content_hash]
        if cached is None:
            result, debug = retrieve(retriever, ticket, config.top_k, config.effective_min_score)
            cached = {
                "retrieved_articles": [a.model_dump(mode="json") for a in result.retrieved_articles],
                "debug": {k: v for k, v in debug.items() if k != "ticket_id"},
            }
            cache.put(cached, *key_prefix, ticket.content_hash)
        result = RetrievalResult(ticket_id=ticket.ticket_id, retrieved_articles=cached["retrieved_articles"])
        results.append(result)
        debug_entries.append({"ticket_id": ticket.ticket_id, **cached["debug"]})

    ctx.data["retrieval"] = {r.ticket_id: r for r in results}
    atomic_write_json(ctx.path(RETRIEVAL_RESULTS), {"results": [r.model_dump(mode="json") for r in results]})
    atomic_write_json(
        ctx.path(RETRIEVAL_DEBUG),
        {"config": {**ctx.data["retrieval_settings"], "kb_hash": ctx.data["kb_hash"]}, "results": debug_entries},
    )
    embedder = ctx.data.get("embedder")
    log_lines = [canonical_json(record) for record in embedder.log] if embedder else []
    atomic_write_text(ctx.path(EMBEDDING_CALLS), "".join(line + "\n" for line in log_lines))
    ctx.manifest["counts"].update(
        {
            "tickets_without_evidence": sum(not r.retrieved_articles for r in results),
            "retrieval_cache": cache.stats(),
            "embedding_texts": len(embedder.log) if embedder else 0,
            "embedding_cache_hits": sum(r["cached"] for r in embedder.log) if embedder else 0,
            "embedding_api_calls": embedder.api_calls if embedder else 0,
        }
    )


def tickets_classified(ctx: RunContext) -> None:
    """One validated classification per ticket (SPEC §7.1), grounded in its retrieved evidence."""
    client = make_llm_client(ctx)
    articles = {a.article_id: a for a in ctx.data["articles"]}
    input_artifacts = [NORMALISED_TICKETS, RETRIEVAL_RESULTS, str(ctx.config.kb_path)]
    classifications = []
    for ticket in ctx.data["tickets"]:
        evidence = [articles[hit.article_id] for hit in ctx.data["retrieval"][ticket.ticket_id].retrieved_articles]
        classifications.append(classify_ticket(client, ticket, evidence, input_artifacts))
    ctx.data.setdefault("llm_records", []).extend(client.records)
    ctx.data["classifications"] = {c.ticket_id: c for c in classifications}
    atomic_write_json(ctx.path(CLASSIFICATION), {"classifications": [c.model_dump(mode="json") for c in classifications]})
    overrides: Counter[str] = Counter(o.split(":")[0] for c in classifications for o in c.meta.overrides)
    ctx.manifest["counts"].update(
        {
            "classification_fallbacks": sum(c.meta.fallback for c in classifications),
            "classification_retries": sum(c.meta.attempts - 1 for c in classifications),
            "overrides": dict(sorted(overrides.items())),
            "llm_calls": len(client.records),
            "llm_cache_hits": sum(r["cached"] for r in client.records),
        }
    )
    ctx.manifest["llm"] = {"provider": client.provider.name, "model": client.provider.model}


def responses_drafted(ctx: RunContext) -> None:
    """One checked draft per ticket (SPEC §7.2), then grounding flags (SPEC §7.5)."""
    client = make_llm_client(ctx)
    articles = {a.article_id: a for a in ctx.data["articles"]}
    input_artifacts = [NORMALISED_TICKETS, RETRIEVAL_RESULTS, CLASSIFICATION, str(ctx.config.kb_path)]
    drafts, flags = [], []
    for ticket in ctx.data["tickets"]:
        classification = ctx.data["classifications"][ticket.ticket_id]
        evidence = [articles[hit.article_id] for hit in ctx.data["retrieval"][ticket.ticket_id].retrieved_articles]
        draft = draft_ticket(client, ticket, classification, evidence, input_artifacts, ctx.config.max_draft_chars)
        drafts.append(draft)
        if not draft.meta.fallback:
            allowed = decide(classification, evidence, ticket.language).escalate
            flags.extend(check_grounding(ticket.ticket_id, draft.draft_response, [articles[c] for c in draft.citations], allowed, ticket.language))
    ctx.data.setdefault("llm_records", []).extend(client.records)
    ctx.data["drafts"] = {d.ticket_id: d for d in drafts}
    ctx.data["grounding_flags"] = flags
    atomic_write_json(ctx.path(DRAFTS), {"drafts": [d.model_dump(mode="json") for d in drafts]})
    atomic_write_json(
        ctx.path(GROUNDING_FLAGS),
        {
            "flags": [f.model_dump(mode="json") for f in flags],
            "summary": {
                "tickets_checked": sum(not d.meta.fallback for d in drafts),
                "tickets_flagged": len({f.ticket_id for f in flags}),
                "total_flags": len(flags),
            },
        },
    )
    ctx.manifest["counts"].update(
        {
            "draft_fallbacks": sum(d.meta.fallback for d in drafts),
            "draft_retries": sum(d.meta.attempts - 1 for d in drafts if not d.meta.fallback),
            "grounding_flags": len(flags),
            "llm_calls": ctx.manifest["counts"].get("llm_calls", 0) + len(client.records),
            "llm_cache_hits": ctx.manifest["counts"].get("llm_cache_hits", 0) + sum(r["cached"] for r in client.records),
        }
    )


def escalations_decided(ctx: RunContext) -> None:
    """Rule-based escalation and routing (SPEC §7.3). No LLM, so the same classifications always give the same file."""
    articles = {a.article_id: a for a in ctx.data["articles"]}
    escalations = []
    for ticket in ctx.data["tickets"]:
        evidence = [articles[hit.article_id] for hit in ctx.data["retrieval"][ticket.ticket_id].retrieved_articles]
        escalations.append(decide(ctx.data["classifications"][ticket.ticket_id], evidence, ticket.language))
    ctx.data["escalations"] = {e.ticket_id: e for e in escalations}
    atomic_write_json(ctx.path(ESCALATIONS), {"escalations": [e.model_dump(mode="json") for e in escalations]})
    queues: Counter[str] = Counter(e.target_queue.value for e in escalations)
    ctx.manifest["counts"].update({"escalated": sum(e.escalate for e in escalations), "queues": dict(sorted(queues.items()))})


def outputs_validated(ctx: RunContext) -> None:
    """V01-V14 against what is on disk (SPEC §8). A failed check does not raise: it sets the exit code (runner)."""
    config = ctx.config
    report = validate(config.out_dir, config.tickets_path, config.kb_path, config.top_k, config.effective_min_score)
    ctx.data["validation"] = report
    ctx.manifest["validation"] = {"status": report["status"], "summary": report["summary"], "failed_checks": [c["id"] for c in report["checks"] if c["status"] == "fail"]}


def results_finalised(ctx: RunContext) -> None:
    """Closing facts for the manifest: per-stage cache hits and misses (R5)."""
    ctx.manifest["cache"] = cache_report(ctx.manifest.get("counts", {}).get("retrieval_cache"), ctx.data.get("llm_records", []))


def build_specs() -> list[StageSpec]:
    return [
        StageSpec(Stage.INIT, init, plan_stage=1),
        StageSpec(Stage.INPUTS_LOADED, inputs_loaded, plan_stage=1),
        StageSpec(Stage.KB_INDEXED, kb_indexed, plan_stage=2),
        StageSpec(Stage.TICKETS_NORMALISED, tickets_normalised, plan_stage=1),
        StageSpec(Stage.EVIDENCE_RETRIEVED, evidence_retrieved, requires=(NORMALISED_TICKETS, KB_INDEX), plan_stage=2),
        StageSpec(Stage.TICKETS_CLASSIFIED, tickets_classified, requires=(RETRIEVAL_RESULTS,), plan_stage=3),
        StageSpec(Stage.RESPONSES_DRAFTED, responses_drafted, requires=(CLASSIFICATION, RETRIEVAL_RESULTS), plan_stage=4),
        StageSpec(Stage.ESCALATIONS_DECIDED, escalations_decided, requires=(DRAFTS,), plan_stage=4),
        StageSpec(Stage.OUTPUTS_VALIDATED, outputs_validated, requires=(ESCALATIONS,), plan_stage=5),
        StageSpec(Stage.RESULTS_FINALISED, results_finalised, requires=(VALIDATION_REPORT,), plan_stage=5),
    ]
