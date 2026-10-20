"""Run summary: per-stage cache report (R5) and the console lines printed by ``run_pipeline.py`` (SPEC §2.1)."""

from typing import Any

STAGE_KEYS = {"classification": "classification", "drafting": "drafting"}


def cache_report(retrieval: dict[str, int] | None, llm_records: list[dict[str, Any]]) -> dict[str, dict[str, int]]:
    """Hits and misses per stage. A ticket counts as a hit for an LLM stage when every attempt came from the cache."""
    report: dict[str, dict[str, int]] = {}
    if retrieval is not None:
        report["retrieval"] = {"hits": retrieval.get("hits", 0), "misses": retrieval.get("misses", 0)}
    for stage in STAGE_KEYS:
        by_ticket: dict[str, list[bool]] = {}
        for record in llm_records:
            if record.get("stage") == stage:
                by_ticket.setdefault(record["ticket_id"], []).append(bool(record.get("cached")))
        hits = sum(all(flags) for flags in by_ticket.values())
        report[stage] = {"hits": hits, "misses": len(by_ticket) - hits}
    return report


def console_summary(manifest: dict[str, Any], error: str | None, exit_code: int) -> list[str]:
    counts = manifest.get("counts", {})
    lines = [
        f"final stage: {manifest['final_stage']}  exit code: {exit_code}",
        f"tickets: {counts.get('tickets_accepted', 0)} accepted, {counts.get('tickets_rejected', 0)} rejected, "
        f"{counts.get('tickets_duplicate', 0)} duplicate · PII detections: {counts.get('pii_detections', {})}",
    ]
    if "escalated" in counts:
        lines.append(f"escalated: {counts['escalated']} · queues: {counts.get('queues', {})}")
    validation = manifest.get("validation")
    if validation:
        s = validation["summary"]
        lines.append(f"validation: {validation['status']} ({s['passed']} passed, {s['failed']} failed, {s['warnings']} warnings)")
    cache = manifest.get("cache")
    if cache:
        lines.append("cache: " + ", ".join(f"{stage} {c['hits']}/{c['hits'] + c['misses']}" for stage, c in cache.items()))
    if error:
        lines.append(f"error: {error}")
    return lines
