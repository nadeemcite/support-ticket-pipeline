"""Classification eval (PLAN Stage 3): both eval models x 3 repeats x 23 eval tickets, scored against gold.

Inputs are frozen: normalisation, PII masking and retrieval run once (deterministic / cached), so any
difference between models comes from the model alone. Each (model, repeat) has its own LLM cache
namespace, so repeats are real calls while regenerating a report is free.

Usage: python -m evals.classification_eval [--repeats 3] [--workers 6]
"""

import argparse
import json
import statistics
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from pipeline.cache import JsonCache
from pipeline.classify import classify_ticket
from pipeline.llm import LiteLLMProvider, LLMClient
from pipeline.orchestrator import Stage, utc_now
from pipeline.retrieval import CachedEmbedder, LiteLLMEmbedder, build_retriever, retrieve

from evals.retrieval_eval import EMBEDDING_MODEL, EVAL, load_eval_set

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "audit" / "stage-3" / "evals"
EVAL_MODELS = [("openai", "gpt-6.1-sol"), ("ollama", "deepseek-v4.1-flash")]
DEV_MODEL = ("ollama", "glm-5.2")
FIELDS = ("issue_type", "urgency", "resolution_action", "requires_refund_caution", "customer_sensitive")
INPUT_ARTIFACTS = ["data/eval/tickets.json (normalised)", "retrieval (embedding, min_score 0.25)", "data/eval/kb_articles.json"]
MIN_SCORE = 0.25


def frozen_inputs() -> tuple[list, dict, dict[str, dict]]:
    tickets, articles, gold = load_eval_set()
    embedder = CachedEmbedder(LiteLLMEmbedder(EMBEDDING_MODEL), JsonCache(ROOT / ".cache"), clock=utc_now)
    retriever = build_retriever("embedding", articles, embedder)
    retriever.prefetch(tickets)
    by_id = {a.article_id: a for a in articles}
    evidence = {
        t.ticket_id: [by_id[hit.article_id] for hit in retrieve(retriever, t, 3, MIN_SCORE)[0].retrieved_articles]
        for t in tickets
    }
    return tickets, evidence, gold


def run_model(provider_name: str, model: str, repeat: int, tickets: list, evidence: dict, workers: int) -> list[dict]:
    log_dir = OUT / "raw" / model / f"r{repeat}"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / "llm_calls.jsonl"
    log_path.write_text("")
    client = LLMClient(
        provider=LiteLLMProvider(provider_name, model, timeout_s=120),
        max_tokens=1500,
        temperature=0.0,
        log_path=log_path,
        clock=utc_now,
        cache=JsonCache(ROOT / ".cache"),
        cache_namespace=f"eval-classification/{model}/r{repeat}",
        current_stage=lambda: Stage.TICKETS_CLASSIFIED,
    )

    def one(ticket):
        result = classify_ticket(client, ticket, evidence[ticket.ticket_id], INPUT_ARTIFACTS)
        return result.model_dump(mode="json")

    with ThreadPoolExecutor(max_workers=workers) as pool:
        results = list(pool.map(one, tickets))
    calls = {}
    for record in client.records:
        calls.setdefault(record["ticket_id"], []).append(record)
    for result in results:
        attempts = sorted(calls.get(result["ticket_id"], []), key=lambda r: r["attempt"])
        result["eval"] = {
            "repeat": repeat,
            "first_attempt_status": attempts[0]["status"] if attempts else None,
            "latency_ms": sum(r["latency_ms"] for r in attempts),
            "prompt_tokens": sum(r["usage"].get("prompt_tokens", 0) for r in attempts),
            "completion_tokens": sum(r["usage"].get("completion_tokens", 0) for r in attempts),
            "cached": all(r["cached"] for r in attempts),
            "prompt_hashes": [r["prompt_hash"] for r in attempts],
        }
    return results


# --- scoring --------------------------------------------------------------------------------------


def _ok(pred: Any, acceptable: list) -> bool:
    return pred in acceptable


def kappa(a: list[str], b: list[str]) -> float:
    """Cohen's kappa between two raters' labels on the same items."""
    n = len(a)
    if n == 0:
        return 0.0
    observed = sum(x == y for x, y in zip(a, b)) / n
    labels = set(a) | set(b)
    expected = sum((a.count(label) / n) * (b.count(label) / n) for label in labels)
    return round((observed - expected) / (1 - expected), 3) if expected < 1 else 1.0


def score_model(runs: list[list[dict]], gold: dict[str, dict]) -> dict[str, Any]:
    flat = [r for run in runs for r in run]
    n = len(flat)
    accuracy = {}
    for field in FIELDS:
        lenient = sum(_ok(r[field], gold[r["ticket_id"]][field]) for r in flat)
        strict = sum(r[field] == gold[r["ticket_id"]][field][0] for r in flat)
        accuracy[field] = {"lenient": round(lenient / n, 4), "strict": round(strict / n, 4), "n": n}

    by_ticket: dict[str, list[dict]] = {}
    for r in flat:
        by_ticket.setdefault(r["ticket_id"], []).append(r)
    stable = sum(len({tuple(r[f] for f in FIELDS) for r in rs}) == 1 for rs in by_ticket.values())
    injection = [r for r in by_ticket.get("E-2009", [])]
    latencies = sorted(r["eval"]["latency_ms"] for r in flat if not r["eval"]["cached"])

    misses = []
    for ticket_id, rs in by_ticket.items():
        for r in rs:
            wrong = [f for f in FIELDS if not _ok(r[f], gold[ticket_id][f])]
            if wrong:
                misses.append({"ticket_id": ticket_id, "repeat": r["eval"]["repeat"], "fields": wrong})
    return {
        "predictions": n,
        "final_valid": n,  # every record passed Classification validation (fallbacks included)
        "first_attempt_ok": round(sum(r["eval"]["first_attempt_status"] == "ok" for r in flat) / n, 4),
        "fallback_rate": round(sum(r["meta"]["fallback"] for r in flat) / n, 4),
        "accuracy": accuracy,
        "injection_resisted": sum(r["urgency"] != "critical" for r in injection),
        "injection_total": len(injection),
        "stability": {"stable_tickets": stable, "tickets": len(by_ticket)},
        "latency_ms": {
            "p50": round(statistics.median(latencies), 1) if latencies else None,
            "p95": round(latencies[int(0.95 * (len(latencies) - 1))], 1) if latencies else None,
            "uncached_calls": len(latencies),
        },
        "tokens": {
            "prompt": sum(r["eval"]["prompt_tokens"] for r in flat),
            "completion": sum(r["eval"]["completion_tokens"] for r in flat),
        },
        "overrides": _count_overrides(flat),
        "misses": misses,
    }


def _count_overrides(flat: list[dict]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for r in flat:
        for override in r["meta"]["overrides"]:
            rule = override.split(":")[0]
            counts[rule] = counts.get(rule, 0) + 1
    return dict(sorted(counts.items()))


def confusion(run: list[dict], gold: dict[str, dict], field: str) -> dict[str, dict[str, int]]:
    """Gold-preferred label (rows) vs predicted label (columns), first repeat."""
    matrix: dict[str, dict[str, int]] = {}
    for r in run:
        row = matrix.setdefault(str(gold[r["ticket_id"]][field][0]), {})
        row[str(r[field])] = row.get(str(r[field]), 0) + 1
    return matrix


def run(repeats: int, workers: int, include_dev: bool = True) -> dict[str, Any]:
    tickets, evidence, gold = frozen_inputs()
    models = [(p, m, repeats, "eval") for p, m in EVAL_MODELS]
    if include_dev:
        models.append((*DEV_MODEL, 1, "dev (information only)"))
    output: dict[str, Any] = {
        "repeats": repeats,
        "tickets": len(tickets),
        "evidence": {t: [a.article_id for a in arts] for t, arts in evidence.items()},
        "models": {},
    }
    for provider_name, model, n_repeats, role in models:
        runs = [run_model(provider_name, model, r, tickets, evidence, workers) for r in range(1, n_repeats + 1)]
        model_dir = OUT / model
        model_dir.mkdir(parents=True, exist_ok=True)
        with (model_dir / "results.jsonl").open("w", encoding="utf-8") as handle:
            for record in (r for run_ in runs for r in run_):
                handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        output["models"][model] = {
            "provider": provider_name,
            "role": role,
            "repeats": n_repeats,
            "score": score_model(runs, gold),
            "confusion": {f: confusion(runs[0], gold, f) for f in ("issue_type", "urgency", "resolution_action")},
            "runs": runs,
        }
    a, b = (output["models"][m]["runs"][0] for _, m in EVAL_MODELS)
    output["agreement"] = {
        field: {
            "kappa": kappa([str(x[field]) for x in a], [str(y[field]) for y in b]),
            "agree": sum(x[field] == y[field] for x, y in zip(a, b)),
            "of": len(a),
        }
        for field in ("issue_type", "urgency", "resolution_action")
    }
    return output


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument("--no-dev", action="store_true", help="skip the dev-model information run")
    args = parser.parse_args(argv)
    load_dotenv(ROOT / ".env", override=False)
    OUT.mkdir(parents=True, exist_ok=True)
    result = run(args.repeats, args.workers, include_dev=not args.no_dev)
    slim = {**result, "models": {m: {k: v for k, v in d.items() if k != "runs"} for m, d in result["models"].items()}}
    (OUT / "classification_eval.json").write_text(json.dumps(slim, indent=2, ensure_ascii=False) + "\n")
    for model, data in result["models"].items():
        s = data["score"]
        acc = {f: s["accuracy"][f]["lenient"] for f in FIELDS}
        print(f"{model:22} {data['role']:24} fallback={s['fallback_rate']} first_ok={s['first_attempt_ok']} acc={acc} "
              f"stable={s['stability']} injection={s['injection_resisted']}/{s['injection_total']}")
    print("agreement:", result["agreement"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
