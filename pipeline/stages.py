"""Stage implementations and the stage registry.

Each function takes the ``RunContext``, reads typed inputs from ``ctx.data`` (put there by earlier
stages), writes its artifact atomically, and records facts for the manifest.
"""

from collections import Counter

from pipeline.io_utils import atomic_write_json, atomic_write_text
from pipeline.loader import load_inputs
from pipeline.normalise import normalise_tickets
from pipeline.orchestrator import RunContext, Stage, StageSpec

NORMALISED_TICKETS = "artifacts/normalised_tickets.json"
LLM_CALLS = "llm_calls.jsonl"


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


def build_specs() -> list[StageSpec]:
    return [
        StageSpec(Stage.INIT, init, plan_stage=1),
        StageSpec(Stage.INPUTS_LOADED, inputs_loaded, plan_stage=1),
        StageSpec(Stage.KB_INDEXED, None, plan_stage=2),
        StageSpec(Stage.TICKETS_NORMALISED, tickets_normalised, plan_stage=1),
        StageSpec(Stage.EVIDENCE_RETRIEVED, None, requires=(NORMALISED_TICKETS,), plan_stage=2),
        StageSpec(Stage.TICKETS_CLASSIFIED, None, plan_stage=3),
        StageSpec(Stage.RESPONSES_DRAFTED, None, plan_stage=4),
        StageSpec(Stage.ESCALATIONS_DECIDED, None, plan_stage=4),
        StageSpec(Stage.OUTPUTS_VALIDATED, None, plan_stage=5),
        StageSpec(Stage.RESULTS_FINALISED, None, plan_stage=5),
    ]
