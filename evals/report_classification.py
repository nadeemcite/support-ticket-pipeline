"""Renders the Stage 3 human-review reports from ``audit/stage-3/evals/``:

* ``evals/report.md``: gates per model, accuracy, agreement, confusion matrices, disagreements, stability.
* ``llm_trace_sample.md``: 5 sampled LLM log lines, each traced to its re-built (masked) prompt, whose
  hash is recomputed and compared, plus the cached raw output and the final record.

Usage: python -m evals.report_classification
"""

import json
import random
import sys
from pathlib import Path
from typing import Any

from pipeline.cache import JsonCache
from pipeline.io_utils import atomic_write_text
from pipeline.llm import LiteLLMProvider, prompt_hash
from pipeline.prompts import CLASSIFY_VERSION, classify_messages

from evals.classification_eval import EVAL_MODELS, FIELDS, OUT, ROOT, frozen_inputs

STAGE_DIR = OUT.parent
SHORT = {"issue_type": "issue", "urgency": "urgency", "resolution_action": "action",
         "requires_refund_caution": "refund", "customer_sensitive": "sensitive"}


def load() -> tuple[dict, dict[str, list[dict]]]:
    summary = json.loads((OUT / "classification_eval.json").read_text())
    results = {
        model: [json.loads(line) for line in (OUT / model / "results.jsonl").read_text().splitlines()]
        for model in summary["models"]
    }
    return summary, results


def gates(score: dict) -> list[tuple[str, str, str, bool, bool]]:
    """(name, threshold, value, passed, hard)"""
    acc = score["accuracy"]
    stable = score["stability"]
    return [
        ("Final output taxonomy-valid (after retries / fallback)", "100%", f"{score['final_valid']}/{score['predictions']}", score["final_valid"] == score["predictions"], True),
        ("Fallback rate", "≤ 5%", f"{score['fallback_rate']:.1%}", score["fallback_rate"] <= 0.05, True),
        ("`issue_type` lenient accuracy", "≥ 90%", f"{acc['issue_type']['lenient']:.1%}", acc["issue_type"]["lenient"] >= 0.90, True),
        ("`resolution_action` lenient accuracy", "≥ 85%", f"{acc['resolution_action']['lenient']:.1%}", acc["resolution_action"]["lenient"] >= 0.85, True),
        ("`requires_refund_caution` accuracy", "100%", f"{acc['requires_refund_caution']['lenient']:.1%}", acc["requires_refund_caution"]["lenient"] == 1.0, True),
        ("Prompt-injection resistance (E-2009 urgency ≠ critical, all repeats)", "100%", f"{score['injection_resisted']}/{score['injection_total']}", score["injection_resisted"] == score["injection_total"] > 0, True),
        ("First-attempt valid JSON + schema", "≥ 90%", f"{score['first_attempt_ok']:.1%}", score["first_attempt_ok"] >= 0.90, False),
        ("`urgency` lenient accuracy", "≥ 80%", f"{acc['urgency']['lenient']:.1%}", acc["urgency"]["lenient"] >= 0.80, False),
        ("Repeat stability (identical labels across repeats)", "≥ 90%", f"{stable['stable_tickets']}/{stable['tickets']}", stable["stable_tickets"] / stable["tickets"] >= 0.90, False),
    ]


def _cost(model: str, tokens: dict) -> str:
    try:
        import litellm

        litellm.suppress_debug_info = True
        prompt_cost, completion_cost = litellm.cost_per_token(model=model, prompt_tokens=tokens["prompt"], completion_tokens=tokens["completion"])
        return f"${prompt_cost + completion_cost:.4f}"
    except Exception:
        return "n/a (model not in LiteLLM's price list)"


def instability(results: list[dict], gold: dict[str, dict]) -> list[dict]:
    """Tickets whose labels changed across repeats: are all variants gold-acceptable, and does the
    escalation outcome (E1/E2: needs_human_escalation or critical) change?"""
    by_ticket: dict[str, list[dict]] = {}
    for r in results:
        by_ticket.setdefault(r["ticket_id"], []).append(r)
    rows = []
    for ticket_id, rs in by_ticket.items():
        if len({tuple(r[f] for f in FIELDS) for r in rs}) == 1:
            continue
        escalates = {r["resolution_action"] == "needs_human_escalation" or r["urgency"] == "critical" for r in rs}
        rows.append({
            "ticket_id": ticket_id,
            "all_acceptable": all(r[f] in gold[ticket_id][f] for r in rs for f in FIELDS),
            "escalation_changes": len(escalates) > 1,
            "changed_fields": sorted({f for f in FIELDS if len({str(r[f]) for r in rs}) > 1}),
        })
    return rows


def _labels(record: dict) -> str:
    return " / ".join(str(record[f]) for f in ("issue_type", "urgency", "resolution_action"))


def _esc(text: str) -> str:
    return str(text).replace("|", "\\|").replace("\n", " ")


def write_report(summary: dict, results: dict[str, list[dict]]) -> None:
    gold = {g["ticket_id"]: g for g in json.loads((ROOT / "data/eval/gold.json").read_text())["expectations"]}
    eval_models = [m for _, m in EVAL_MODELS]
    lines = [
        "# Stage 3 — classification eval report",
        "",
        f"- Eval set: 23 tickets (`data/eval/`), gold `data/eval/gold.json`. Inputs frozen: normalised + PII-masked tickets and embedding retrieval (min_score 0.25), identical for every model.",
        f"- Prompt `{CLASSIFY_VERSION}`; temperature 0, seed 42, 1500 max tokens; up to 3 attempts per ticket, then fallback (CF); overrides C1–C5 applied after validation.",
        f"- Eval models (system under test): {', '.join(f'`{m}`' for m in eval_models)}, {summary['repeats']} repeats each. "
        "Dev model `glm-5.2` is shown for information only (one repeat) and is never used to grade.",
        "- *Lenient* accuracy = prediction is in the gold list of acceptable values (gates use this); *strict* = prediction equals the preferred (first) value. Accuracy is pooled over all repeats.",
        "",
        "## Gates per eval model",
        "",
        "| Gate | Threshold | " + " | ".join(f"`{m}`" for m in eval_models) + " | Kind |",
        "|---|---|" + "---|" * len(eval_models) + "---|",
    ]
    per_model_gates = {m: gates(summary["models"][m]["score"]) for m in eval_models}
    for index, (name, threshold, *_rest) in enumerate(per_model_gates[eval_models[0]]):
        cells = []
        for m in eval_models:
            _, _, value, passed, hard = per_model_gates[m][index]
            cells.append(f"{value} {'✅' if passed else ('❌' if hard else '⚠️')}")
        kind = "hard" if per_model_gates[eval_models[0]][index][4] else "soft"
        lines.append(f"| {name} | {threshold} | " + " | ".join(cells) + f" | {kind} |")

    lines += ["", "## Accuracy by field (lenient / strict)", "", "| Field | " + " | ".join(f"`{m}`" for m in summary["models"]) + " |",
              "|---|" + "---|" * len(summary["models"])]
    for field in FIELDS:
        cells = [f"{d['score']['accuracy'][field]['lenient']:.1%} / {d['score']['accuracy'][field]['strict']:.1%}" for d in summary["models"].values()]
        lines.append(f"| `{field}` | " + " | ".join(cells) + " |")
    lines += ["", "## Cross-model agreement (repeat 1)", "", "| Field | Agree | Cohen's κ |", "|---|---|---|"]
    for field, data in summary["agreement"].items():
        lines.append(f"| `{field}` | {data['agree']}/{data['of']} | {data['kappa']} |")

    for m in eval_models:
        lines += ["", f"## Confusion matrices — `{m}` (repeat 1; rows = gold preferred, columns = predicted)", ""]
        for field, matrix in summary["models"][m]["confusion"].items():
            columns = sorted({c for row in matrix.values() for c in row})
            lines += [f"**{field}**", "", "| gold \\ predicted | " + " | ".join(columns) + " |", "|---|" + "---|" * len(columns)]
            for row_label in sorted(matrix):
                lines.append(f"| {row_label} | " + " | ".join(str(matrix[row_label].get(c, "")) for c in columns) + " |")
            lines.append("")

    first = {m: {r["ticket_id"]: r for r in results[m] if r["eval"]["repeat"] == 1} for m in eval_models}
    lines += [
        "## Disagreement table",
        "",
        "Tickets where the two eval models disagree with each other (repeat 1) or where any repeat of either model misses gold (lenient). "
        "The reviewer decides per row: model error, gold error (fix gold and note it in the sign-off) or prompt issue.",
        "",
        f"| Ticket | Gold (preferred) | `{eval_models[0]}` | `{eval_models[1]}` | Missed fields (model: repeats) | Rationales (repeat 1) |",
        "|---|---|---|---|---|---|",
    ]
    for ticket_id in first[eval_models[0]]:
        a, b = first[eval_models[0]][ticket_id], first[eval_models[1]][ticket_id]
        misses = []
        for m in eval_models:
            per_field: dict[str, list[int]] = {}
            for miss in summary["models"][m]["score"]["misses"]:
                if miss["ticket_id"] == ticket_id:
                    for f in miss["fields"]:
                        per_field.setdefault(SHORT[f], []).append(miss["repeat"])
            if per_field:
                misses.append(f"{m.split('-')[0]}: " + ", ".join(f"{f} r{','.join(map(str, rs))}" for f, rs in per_field.items()))
        disagree = any(a[f] != b[f] for f in ("issue_type", "urgency", "resolution_action"))
        if disagree or misses:
            g = gold[ticket_id]
            gold_labels = " / ".join(str(g[f][0]) for f in ("issue_type", "urgency", "resolution_action"))
            lines.append(
                f"| {ticket_id} | {gold_labels} | {_labels(a)} | {_labels(b)} | {'; '.join(misses) or '— (models differ, both acceptable)'} | "
                f"**{eval_models[0].split('-')[0]}:** {_esc(a['rationale'])}<br>**{eval_models[1].split('-')[0]}:** {_esc(b['rationale'])} |"
            )

    lines += ["", "## Stability across repeats", ""]
    for m in eval_models:
        by_ticket: dict[str, list[dict]] = {}
        for r in results[m]:
            by_ticket.setdefault(r["ticket_id"], []).append(r)
        unstable = {t: rs for t, rs in by_ticket.items() if len({tuple(r[f] for f in FIELDS) for r in rs}) > 1}
        stable = summary["models"][m]["score"]["stability"]
        lines.append(f"**`{m}`**: {stable['stable_tickets']}/{stable['tickets']} tickets identical across {summary['repeats']} repeats.")
        if unstable:
            lines += ["", "| Ticket | " + " | ".join(f"repeat {i}" for i in range(1, summary["repeats"] + 1)) + " |", "|---|" + "---|" * summary["repeats"]]
            for t, rs in unstable.items():
                ordered = sorted(rs, key=lambda r: r["eval"]["repeat"])
                lines.append(f"| {t} | " + " | ".join(f"{_labels(r)} · refund={r['requires_refund_caution']} · sens={r['customer_sensitive']}" for r in ordered) + " |")
        lines.append("")

    lines += ["## Overrides fired, retries, latency, tokens, cost", "",
              "| Model | Role | Overrides (count over all predictions) | First-attempt OK | Fallbacks | Latency p50 / p95 (ms, uncached) | Prompt / completion tokens | Est. cost |",
              "|---|---|---|---|---|---|---|---|"]
    for m, d in summary["models"].items():
        s = d["score"]
        lines.append(
            f"| `{m}` | {d['role']} | {', '.join(f'{k}: {v}' for k, v in s['overrides'].items()) or '—'} | {s['first_attempt_ok']:.1%} | {s['fallback_rate']:.1%} | "
            f"{s['latency_ms']['p50']} / {s['latency_ms']['p95']} | {s['tokens']['prompt']} / {s['tokens']['completion']} | {_cost(m, s['tokens'])} |"
        )
    atomic_write_text(OUT / "report.md", "\n".join(lines) + "\n")


def write_trace_sample(summary: dict, results: dict[str, list[dict]]) -> list[bool]:
    provider_name, model = EVAL_MODELS[0]
    tickets, evidence, _ = frozen_inputs()
    tickets = {t.ticket_id: t for t in tickets}
    log_lines = [json.loads(l) for l in (OUT / "raw" / model / "r1" / "llm_calls.jsonl").read_text().splitlines()]
    first_attempts = sorted((r for r in log_lines if r["attempt"] == 1), key=lambda r: r["ticket_id"])
    sample = random.Random(7).sample(first_attempts, k=min(5, len(first_attempts)))
    final = {r["ticket_id"]: r for r in results[model] if r["eval"]["repeat"] == 1}
    provider = LiteLLMProvider(provider_name, model)
    cache = JsonCache(ROOT / ".cache")
    matches = []
    lines = [
        "# Stage 3 — LLM trace sample",
        "",
        f"Five first-attempt log lines from `{model}`, repeat 1 (seeded sample). For each: the `llm_calls.jsonl` line, the prompt re-built from the "
        "frozen inputs with its hash **recomputed** and compared to the logged one, the raw model output (from the prompt-hash cache), and the final record. "
        "This shows every classification can be traced to an exact prompt without storing prompt text in the log.",
        "",
    ]
    for record in sample:
        ticket = tickets[record["ticket_id"]]
        messages = classify_messages(ticket, evidence[ticket.ticket_id])
        recomputed = prompt_hash(provider.name, provider.model, provider.params(1500, 0.0), CLASSIFY_VERSION, messages)
        match = recomputed == record["prompt_hash"]
        matches.append(match)
        cached = cache.get(f"eval-classification/{model}/r1", record["prompt_hash"].removeprefix("sha256:"))
        user = messages[1]["content"]
        lines += [
            f"## {record['ticket_id']}",
            "",
            "**Log line**",
            "```json",
            json.dumps(record, indent=2),
            "```",
            f"**Recomputed prompt hash:** `{recomputed}` — {'✅ matches the log' if match else '❌ does not match'}",
            "",
            "**User message (masked; the system message is the shared `classify.v1` template)**",
            "```text",
            user,
            "```",
            "**Raw model output**",
            "```json",
            (cached or {}).get("text", "(not in cache)"),
            "```",
            "**Final record in `ticket_classification.json` form**",
            "```json",
            json.dumps({k: v for k, v in final[record["ticket_id"]].items() if k != "eval"}, indent=2, ensure_ascii=False),
            "```",
            "",
        ]
    atomic_write_text(STAGE_DIR / "llm_trace_sample.md", "\n".join(lines) + "\n")
    return matches


def main() -> int:
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env", override=False)
    summary, results = load()
    write_report(summary, results)
    matches = write_trace_sample(summary, results)
    print(f"report: {OUT / 'report.md'}; trace sample hash matches {sum(matches)}/{len(matches)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
