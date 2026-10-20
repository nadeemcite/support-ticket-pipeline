"""End-to-end eval (PLAN Stage 5): the real pipeline (``pipeline.runner.run``, all 10 stages) on the eval set with
each eval model as the pipeline's LLM, then scored against gold.

Every number comes from the artifacts the pipeline wrote, so this measures the shipped system rather than a
re-implementation. Classification and drafting hard gates from Stages 3 and 4 are re-measured end to end (the judge
is advisory since the Stage 4 calibration was skipped, and was measured in Stage 4, so it is not re-run here).

Usage:
    python -m evals.e2e_eval run --model gpt-6.1-sol --cold   # one pipeline run (repeat per model; can run in parallel)
    python -m evals.e2e_eval report                       # score every finished run, write the report
"""

import argparse
import json
import shutil
import sys
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from evals.classification_eval import DEV_MODEL, EVAL_MODELS, FIELDS, score_model
from evals.drafting_eval import deterministic_checks
from evals.report_drafting import gates as drafting_gates
from evals.retrieval_eval import EVAL as EVAL_DIR
from pipeline.config import Config
from pipeline.io_utils import atomic_write_json, atomic_write_text
from pipeline.loader import load_inputs
from pipeline.normalise import normalise_article
from pipeline.runner import run
from pipeline.schemas import Classification, NormalisedTicket

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "audit" / "stage-5" / "evals"
RAW = OUT / "raw"
MODELS = [*EVAL_MODELS, DEV_MODEL]
REGRESSION_POINTS = 5.0
ESCALATION_GATE = 0.90

# SPEC §12.2: expected outcomes for the three sample tickets.
SAMPLES = {
    "T-1001": dict(top1="KB-001", issue=("billing",), urgency=("high", "medium"), action=("answer_from_kb", "needs_human_escalation"), caution=True, escalate=(False, True), cites="KB-001", mentions=("pending", "authoriz")),
    "T-1002": dict(top1="KB-002", issue=("account_access",), urgency=("high",), action=("needs_human_escalation",), caution=False, escalate=(True,), queue="account_support", cites="KB-002", mentions=("incognito", "cache")),
    "T-1003": dict(top1="KB-003", issue=("how_to", "billing"), urgency=("low",), action=("answer_from_kb",), caution=False, escalate=(False,), cites="KB-003", mentions=("billing", "documents")),
}


def pipeline_config(provider: str, model: str, out_dir: Path, no_cache: bool = False) -> Config:
    return Config(no_cache=no_cache, 
        provider=provider, model=model, retriever="embedding", tickets_path=EVAL_DIR / "tickets.json",
        kb_path=EVAL_DIR / "kb_articles.json", out_dir=out_dir, max_tokens=3000, timeout_s=180,
    )


def run_model(provider: str, model: str, cold: bool = False) -> int:
    out_dir = RAW / model
    if cold:  # a clean directory and no cache reads: every call is a real call, so latency and cost are measured
        shutil.rmtree(out_dir, ignore_errors=True)
    out_dir.mkdir(parents=True, exist_ok=True)
    cache_link = out_dir / ".cache"
    if not cache_link.exists():
        cache_link.symlink_to(ROOT / ".cache", target_is_directory=True)  # shared embedding + LLM cache
    outcome = run(pipeline_config(provider, model, out_dir, no_cache=cold))
    print(f"{model}: exit {outcome.exit_code} final {outcome.manifest['final_stage']} validation "
          f"{outcome.manifest.get('validation', {}).get('status')} {outcome.error or ''}")
    return outcome.exit_code


# --- scoring ----------------------------------------------------------------------------------------


def _load(path: Path, key: str) -> list[dict]:
    return json.loads(path.read_text(encoding="utf-8"))[key]


def read_run(out_dir: Path) -> dict[str, Any]:
    log = [json.loads(line) for line in (out_dir / "llm_calls.jsonl").read_text().splitlines()]
    return {
        "tickets": {t["ticket_id"]: NormalisedTicket.model_validate(t) for t in _load(out_dir / "artifacts/normalised_tickets.json", "tickets")},
        "retrieval": {r["ticket_id"]: [a["article_id"] for a in r["retrieved_articles"]] for r in _load(out_dir / "retrieval_results.json", "results")},
        "classification": {c["ticket_id"]: c for c in _load(out_dir / "ticket_classification.json", "classifications")},
        "drafts": {d["ticket_id"]: d for d in _load(out_dir / "draft_responses.json", "drafts")},
        "escalations": {e["ticket_id"]: e for e in _load(out_dir / "escalations.json", "escalations")},
        "flags": _load(out_dir / "grounding_flags.json", "flags"),
        "validation": json.loads((out_dir / "validation_report.json").read_text()),
        "manifest": json.loads((out_dir / "artifacts/run_manifest.json").read_text()),
        "log": log,
    }


def _calls(log: list[dict], stage: str, ticket_id: str) -> list[dict]:
    return sorted((r for r in log if r["stage"] == stage and r["ticket_id"] == ticket_id), key=lambda r: r["attempt"])


def classification_records(data: dict) -> list[dict]:
    records = []
    for ticket_id, c in data["classification"].items():
        calls = _calls(data["log"], "classification", ticket_id)
        records.append({**c, "eval": {
            "repeat": 1, "first_attempt_status": calls[0]["status"] if calls else None, "cached": all(x["cached"] for x in calls),
            "latency_ms": sum(x["latency_ms"] for x in calls), "prompt_tokens": sum(x["usage"].get("prompt_tokens", 0) for x in calls),
            "completion_tokens": sum(x["usage"].get("completion_tokens", 0) for x in calls)}})
    return records


def draft_records(data: dict, articles: dict, gold: dict) -> list[dict]:
    records = []
    for ticket_id, draft in data["drafts"].items():
        calls = _calls(data["log"], "drafting", ticket_id)
        draft = {**draft, "eval": {"first_attempt_status": calls[0]["status"] if calls else None}}
        evidence = [articles[a] for a in data["retrieval"][ticket_id]]
        classification = Classification.model_validate(data["classification"][ticket_id])
        records.append({**draft, "checks": deterministic_checks(draft, data["tickets"][ticket_id], classification, evidence, gold[ticket_id]), "judge": {"scores": None}})
    return records


def escalation_accuracy(data: dict, gold: dict) -> dict[str, Any]:
    wrong = []
    for ticket_id, e in data["escalations"].items():
        g = gold[ticket_id]
        if e["escalate"] not in g["escalate"] or e["target_queue"] not in g["target_queue"]:
            wrong.append({"ticket_id": ticket_id, "got": [e["escalate"], e["target_queue"]], "gold": [g["escalate"], g["target_queue"]]})
    n = len(data["escalations"])
    return {"correct": n - len(wrong), "of": n, "accuracy": (n - len(wrong)) / n if n else 0.0, "wrong": wrong}


def check_samples(data: dict) -> list[dict]:
    rows = []
    for ticket_id, want in SAMPLES.items():
        c, d, e = data["classification"][ticket_id], data["drafts"][ticket_id], data["escalations"][ticket_id]
        text = d["draft_response"].lower()
        checks = {
            "top-1 evidence": data["retrieval"][ticket_id][:1] == [want["top1"]],
            "issue_type": c["issue_type"] in want["issue"],
            "urgency": c["urgency"] in want["urgency"],
            "resolution_action": c["resolution_action"] in want["action"],
            "requires_refund_caution": c["requires_refund_caution"] == want["caution"],
            "escalate": e["escalate"] in want["escalate"],
            "queue": e["target_queue"] == want["queue"] if "queue" in want else (e["target_queue"] == "none" if not e["escalate"] else e["target_queue"] == "billing_ops"),
            "cites expected article": want["cites"] in d["citations"],
            "draft covers the KB answer": any(m in text for m in want["mentions"]),
            "draft is safe (no secret request / refund promise)": not any(b in text for b in ("send us your password", "we will refund", "refund has been issued")),
        }
        rows.append({"ticket_id": ticket_id, "checks": checks, "passed": all(checks.values())})
    return rows


def baselines() -> dict[str, dict[str, float]]:
    """Stage 3 lenient accuracies per model, from the committed Stage 3 eval; Stage 4 rates are 100% by gate."""
    path = ROOT / "audit" / "stage-3" / "evals" / "classification_eval.json"
    stage3 = json.loads(path.read_text())["models"] if path.exists() else {}
    return {m: {f: d["score"]["accuracy"][f]["lenient"] for f in ("issue_type", "resolution_action", "requires_refund_caution")} | {"fallback_rate": d["score"]["fallback_rate"]} for m, d in stage3.items()}


def score_run(model: str, out_dir: Path) -> dict[str, Any]:
    loaded = load_inputs(EVAL_DIR / "tickets.json", EVAL_DIR / "kb_articles.json")
    articles = {a.article_id: a for a in map(normalise_article, loaded.articles)}
    gold = {g["ticket_id"]: g for g in json.loads((EVAL_DIR / "gold.json").read_text())["expectations"]}
    data = read_run(out_dir)
    cls_score = score_model([classification_records(data)], gold)
    drafts = draft_records(data, articles, gold)
    n = len(drafts)
    uncached = [r for r in data["log"] if not r["cached"]]
    return {
        "model": model,
        "exit_code": data["manifest"]["exit_code"],
        "final_stage": data["manifest"]["final_stage"],
        "validation": {"status": data["validation"]["status"], **data["validation"]["summary"], "failed": [c["id"] for c in data["validation"]["checks"] if c["status"] == "fail"], "warned": [c["id"] for c in data["validation"]["checks"] if c["status"] == "warn"]},
        "classification": cls_score,
        "drafting_gates": [list(row) for row in drafting_gates(drafts, with_judge=False)],
        "escalation": escalation_accuracy(data, gold),
        "samples": check_samples(data),
        "counts": data["manifest"]["counts"],
        "cost": {
            "tickets": n,
            "llm_calls": len(data["log"]),
            "uncached_calls": len(uncached),
            "seconds_per_100_tickets": round(sum(r["latency_ms"] for r in uncached) / 1000 / n * 100, 1) if n and uncached else None,
            "prompt_tokens_per_100_tickets": round(sum(r["usage"].get("prompt_tokens", 0) for r in data["log"]) / n * 100) if n else None,
            "completion_tokens_per_100_tickets": round(sum(r["usage"].get("completion_tokens", 0) for r in data["log"]) / n * 100) if n else None,
            "usd": "n/a (model not in LiteLLM's price list)",
        },
        "flags": data["flags"],
        "draft_fallbacks": [d["ticket_id"] for d in data["drafts"].values() if d["meta"]["fallback"]],
    }


def regression(result: dict, base: dict[str, float]) -> list[tuple[str, float, float, bool]]:
    """(metric, baseline %, now %, ok): no hard metric may be more than 5 points worse than the Stage 3/4 numbers."""
    acc = result["classification"]["accuracy"]
    rows = []
    for field in ("issue_type", "resolution_action", "requires_refund_caution"):
        if field in base:
            before, now = 100 * base[field], 100 * acc[field]["lenient"]
            rows.append((f"{field} lenient accuracy (Stage 3)", before, now, now >= before - REGRESSION_POINTS))
    if "fallback_rate" in base:
        before, now = 100 * base["fallback_rate"], 100 * result["classification"]["fallback_rate"]
        rows.append(("classification fallback rate (Stage 3, lower is better)", before, now, now <= before + REGRESSION_POINTS))
    named = {name: value for name, _, value, _, _ in map(tuple, result["drafting_gates"])}
    for name in ("Citation validity (⊆ retrieved)", "Language match (decidable drafts)"):
        now = float(str(named[name]).split("/")[0]) / float(str(named[name]).split("/")[1]) * 100 if "/" in str(named[name]) else float(str(named[name]).rstrip("%"))
        rows.append((f"{name} (Stage 4)", 100.0, now, now >= 100.0 - REGRESSION_POINTS))
    return rows


def hard_gates(result: dict, base: dict[str, float]) -> list[tuple[str, str, str, bool]]:
    from evals.report_classification import gates as classification_gates

    rows = [("`validate.py` status on the eval-set run", "pass", f"{result['validation']['status']} (exit {result['exit_code']})", result["validation"]["status"] == "pass" and result["exit_code"] == 0)]
    rows += [(f"Stage 3: {n}", t, v, ok) for n, t, v, ok, hard in classification_gates(result["classification"]) if hard]
    rows += [(f"Stage 4: {n}", t, v, ok) for n, t, v, ok, hard, *_ in map(tuple, result["drafting_gates"]) if hard]
    esc = result["escalation"]
    rows.append(("Escalation accuracy vs gold (lenient)", f"≥ {ESCALATION_GATE:.0%}", f"{esc['correct']}/{esc['of']} ({esc['accuracy']:.1%})", esc["accuracy"] >= ESCALATION_GATE))
    passed = sum(s["passed"] for s in result["samples"])
    rows.append(("Sample tickets T-1001/2/3 meet SPEC §12.2", "3/3", f"{passed}/{len(result['samples'])}", passed == len(result["samples"]) == 3))
    regress = regression(result, base)
    worse = [r for r in regress if not r[3]]
    rows.append(("Regression vs Stage 3/4 numbers (no hard metric > 5 pts worse)", "none", "none" if not worse else ", ".join(r[0] for r in worse), not worse))
    return rows


def write_report(results: dict[str, dict]) -> dict[str, list]:
    base = baselines()
    lines = ["# Stage 5 — end-to-end eval report", "",
             "The real pipeline (`run_pipeline.py` code path, all 10 stages, embedding retrieval) on the 23-ticket eval set, once per eval model as the pipeline's LLM, "
             "scored against `gold.json` from the artifacts it wrote. Judge scores are not repeated here (advisory since Stage 4; measured there).", ""]
    gate_rows: dict[str, list] = {}
    for _, model in EVAL_MODELS:
        r = results[model]
        gate_rows[model] = hard_gates(r, base.get(model, {}))
        lines += [f"## `{model}`", "", "| Hard gate | Threshold | Value | |", "|---|---|---|---|"]
        lines += [f"| {n} | {t} | {v} | {'✅' if ok else '❌'} |" for n, t, v, ok in gate_rows[model]]
        lines += ["", "**Regression detail**", "", "| Metric | Before | Now | |", "|---|---|---|---|"]
        lines += [f"| {m} | {b:.1f}% | {n:.1f}% | {'✅' if ok else '❌'} |" for m, b, n, ok in regression(r, base.get(model, {}))]
        soft = [row for row in r["drafting_gates"] if not row[4]]
        lines += ["", "**Soft metrics**", "", "| Metric | Threshold | Value | |", "|---|---|---|---|"]
        lines += [f"| {n} | {t} | {v} | {'✅' if ok else '⚠️'} |" for n, t, v, ok, _ in soft]
        c = r["cost"]
        lines += [f"| Time per 100 tickets (uncached calls) | reported | {c['seconds_per_100_tickets']} s | |",
                  f"| Tokens per 100 tickets (prompt / completion) | reported | {c['prompt_tokens_per_100_tickets']} / {c['completion_tokens_per_100_tickets']} | |",
                  f"| Cost per 100 tickets | reported | {c['usd']} | |", ""]
        lines += ["**Sample tickets (SPEC §12.2)**", "", "| Ticket | " + " | ".join(next(iter(r["samples"]))["checks"]) + " |", "|---|" + "---|" * len(r["samples"][0]["checks"])]
        lines += [f"| {s['ticket_id']} | " + " | ".join("✅" if v else "❌" for v in s["checks"].values()) + " |" for s in r["samples"]]
        if r["escalation"]["wrong"]:
            lines += ["", "**Escalation decisions outside gold**", ""] + [f"- {w['ticket_id']}: got {w['got']}, gold {w['gold']}" for w in r["escalation"]["wrong"]]
        lines += ["", f"Validation: {r['validation']['status']} — {r['validation']['passed']} passed, {r['validation']['failed'] and len(r['validation']['failed']) or 0} failed, warnings: {r['validation']['warned'] or 'none'}; "
                  f"grounding flags: {len(r['flags'])}; draft fallbacks: {r['draft_fallbacks'] or 'none'}; classification fallbacks: {r['counts'].get('classification_fallbacks')}.", ""]
    dev = results.get(DEV_MODEL[1])
    if dev:
        c = dev["classification"]["accuracy"]
        lines += ["## Dev model `glm-5.2` (information only, not a gate)", "",
                  f"exit {dev['exit_code']}, validation {dev['validation']['status']}; issue_type {c['issue_type']['lenient']:.1%}, urgency {c['urgency']['lenient']:.1%}, "
                  f"resolution_action {c['resolution_action']['lenient']:.1%}; escalation vs gold {dev['escalation']['correct']}/{dev['escalation']['of']}; samples "
                  f"{sum(s['passed'] for s in dev['samples'])}/3.", ""]
    atomic_write_text(OUT / "report.md", "\n".join(lines) + "\n")
    return gate_rows


def report() -> int:
    results = {}
    for _, model in MODELS:
        out_dir = RAW / model
        if (out_dir / "validation_report.json").exists():
            results[model] = score_run(model, out_dir)
    missing = [m for _, m in EVAL_MODELS if m not in results]
    if missing:
        print(f"no finished run for {missing}; run `python -m evals.e2e_eval run --model <name>` first", file=sys.stderr)
        return 2
    for model, result in results.items():
        model_dir = OUT / model
        model_dir.mkdir(parents=True, exist_ok=True)
        atomic_write_json(model_dir / "e2e_result.json", result)
    gate_rows = write_report(results)
    atomic_write_json(OUT / "e2e_eval.json", {"models": {m: {"gates": [list(g) for g in gate_rows[m]]} for m in gate_rows}})
    green = all(ok for rows in gate_rows.values() for *_, ok in rows)
    print(f"e2e hard gates {'green' if green else 'NOT green'}")
    return 0 if green else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    one = sub.add_parser("run")
    one.add_argument("--model", required=True, choices=[m for _, m in MODELS])
    one.add_argument("--cold", action="store_true", help="fresh output directory and no cache reads (measures latency and cost)")
    sub.add_parser("report")
    args = parser.parse_args(argv)
    load_dotenv(ROOT / ".env", override=False)
    OUT.mkdir(parents=True, exist_ok=True)
    if args.command == "run":
        provider = dict((m, p) for p, m in MODELS)[args.model]
        return run_model(provider, args.model, args.cold)
    return report()


if __name__ == "__main__":
    sys.exit(main())
