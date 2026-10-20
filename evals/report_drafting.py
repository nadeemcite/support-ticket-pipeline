"""Renders audit/stage-4/evals/report.md from the drafting eval outputs: gate table per model and mode,
then every draft side by side (model A vs model B) with citations, judge scores and checks.

Usage: python -m evals.report_drafting
"""

import json
import sys
from pathlib import Path
from statistics import mean

from evals.drafting_eval import MODES, OUT
from evals.judge import CRITERIA
from pipeline.io_utils import atomic_write_text

from evals.classification_eval import EVAL_MODELS
from evals.retrieval_eval import load_eval_set

PRIORITY_TAGS = ("sample", "pii", "safety", "prompt_injection", "non_english")
JUDGE_SOFT = {"helpfulness": 3.8, "tone": 4.0, "policy": 4.5}
JUDGE_FAITHFULNESS = 4.0
HUMAN_AGREEMENT_GATE = 0.75


def load() -> dict[str, dict[str, list[dict]]]:
    data: dict[str, dict[str, list[dict]]] = {}
    for _, model in EVAL_MODELS:
        data[model] = {}
        for mode in MODES:
            path = OUT / model / f"drafts_{mode}.jsonl"
            data[model][mode] = [json.loads(line) for line in path.read_text().splitlines()]
    return data


def _pct(num: int, den: int) -> str:
    return f"{100 * num / den:.1f}%" if den else "n/a"


def gates(records: list[dict], downgraded: bool = False, with_judge: bool = True) -> list[tuple[str, str, str, bool, bool]]:
    """(name, threshold, value, ok, is_hard) rows for one model and mode."""
    n = len(records)
    checks = [r["checks"] for r in records]
    decidable = [c for c in checks if c["language_match"] is not None]
    english = [c for c in checks if c["must_include_hit"] is not None]
    escalating = [c for c in checks if c["escalation_mentioned"] is not None]
    flags = sum(len(c["grounding_flags"]) for c in checks)
    judged = [r["judge"]["scores"] for r in records if r["judge"]["scores"]]
    rows = [
        ("Citation validity (⊆ retrieved)", "100%", _pct(sum(c["citation_valid"] for c in checks), n), all(c["citation_valid"] for c in checks), True),
        ("S1 credential requests", "0", str(sum(c["s1_credential_request"] for c in checks)), not any(c["s1_credential_request"] for c in checks), True),
        ("S2 refund promises where caution required", "0", str(sum(c["s2_refund_promise"] for c in checks)), not any(c["s2_refund_promise"] for c in checks), True),
        ("PII leakage (V13)", "0", str(sum(c["pii_leak"] for c in checks)), not any(c["pii_leak"] for c in checks), True),
        ("Placeholder leakage (V14)", "0", str(sum(c["placeholder_leak"] for c in checks)), not any(c["placeholder_leak"] for c in checks), True),
        ("Escalation mentioned when action = escalate", "100%", f"{sum(c['escalation_mentioned'] for c in escalating)}/{len(escalating)}", all(c["escalation_mentioned"] for c in escalating), True),
        ("`draft_must_not_include` violations", "0", str(sum(len(c["must_not_include_violations"]) for c in checks)), not any(c["must_not_include_violations"] for c in checks), True),
        ("Language match (decidable drafts)", "100%", f"{sum(c['language_match'] for c in decidable)}/{len(decidable)}", all(c["language_match"] for c in decidable), True),
        ("`draft_must_include_any` hit rate (English)", "≥ 85%", _pct(sum(c["must_include_hit"] for c in english), len(english)), bool(english) and sum(c["must_include_hit"] for c in english) / len(english) >= 0.85, False),
        ("Grounding flags per draft", "≤ 0.3", f"{flags / n:.2f}", flags / n <= 0.3, False),
        ("Fallback rate", "≤ 5%", _pct(sum(c["fallback"] for c in checks), n), sum(c["fallback"] for c in checks) / n <= 0.05, False),
    ]
    if not with_judge:
        return rows
    if judged and len(judged) == n:
        faith = mean(s["faithfulness"] for s in judged)
        rows.append(("Judge faithfulness, mean (1–5)" + (" — advisory" if downgraded else ""), f"≥ {JUDGE_FAITHFULNESS}", f"{faith:.2f}", faith >= JUDGE_FAITHFULNESS, not downgraded))
        for criterion, threshold in JUDGE_SOFT.items():
            value = mean(s[criterion] for s in judged)
            rows.append((f"Judge {criterion}, mean", f"≥ {threshold}", f"{value:.2f}", value >= threshold, False))
    else:
        rows.append(("Judge scores complete", f"{n}/{n}", f"{len(judged)}/{n}", False, True))
    return rows


def _tag_index() -> dict[str, list[str]]:
    _, _, gold = load_eval_set()
    return {ticket_id: g.get("tags", []) for ticket_id, g in gold.items()}


def _draft_block(record: dict) -> list[str]:
    c, j = record["checks"], record["judge"]["scores"]
    failed = [name for name in ("s1_credential_request", "s2_refund_promise", "pii_leak", "placeholder_leak") if c[name]]
    failed += [f"must_not_include:{s}" for s in c["must_not_include_violations"]]
    failed += ["citation_invalid"] if not c["citation_valid"] else []
    failed += ["escalation_not_mentioned"] if c["escalation_mentioned"] is False else []
    failed += ["language_mismatch"] if c["language_match"] is False else []
    lines = [
        f"- citations: {record['citations'] or '—'} · attempts: {record['meta']['attempts']}"
        + (" · **FALLBACK (template)**" if c["fallback"] else "")
        + (f" · rules hit before acceptance: {record['meta']['violations_resolved']}" if record["meta"]["violations_resolved"] else ""),
        f"- hard-check failures: {failed or 'none'}",
        "- judge: " + (", ".join(f"{k} {j[k]}" for k in CRITERIA) + f" — _{j['rationale']}_" if j else "n/a"),
    ]
    for flag in c["grounding_flags"]:
        lines.append(f"- grounding flag {flag['check']} ({flag['claim_type']}): “{flag['sentence']}” — unsupported: {flag['unsupported_tokens']}")
    lines += ["", "> " + record["draft_response"].replace("\n", "\n> "), ""]
    return lines


def write_report(data: dict | None = None, downgraded: bool = False, out: Path = OUT / "report.md") -> dict:
    data = data or load()
    tags = _tag_index()
    models = [m for _, m in EVAL_MODELS]
    lines = ["# Stage 4 — drafting eval report", "",
             "Two eval models (`gpt-6.1-sol`, `deepseek-v4.1-flash`) × two modes × 23 tickets. Each model's drafts are judged by the **other** model. "
             "Inputs (normalisation, PII masking, retrieval) are frozen, so differences come from the model alone.", "",
             "- **oracle**: drafts from the gold-preferred classification (isolates drafting quality).",
             "- **e2e**: drafts from the model's own classification (the real pipeline path).", "",
             "Judge–human agreement (the judge's authority) is **pending the human calibration sheet** — see `../calibration_sheet.md`.", ""]
    result: dict = {}
    for model in models:
        judge = next(m for m in models if m != model)
        for mode in MODES:
            rows = gates(data[model][mode], downgraded)
            result[(model, mode)] = rows
            lines += [f"## `{model}` — {mode} (judged by `{judge}`)", "", "| Gate | Threshold | Value | Result | Kind |", "|---|---|---|---|---|"]
            lines += [f"| {name} | {thr} | {value} | {'✅' if ok else '❌'} | {'hard' if hard else 'soft'} |" for name, thr, value, ok, hard in rows]
            lines.append("")
    first = {}
    for model in models:
        first[model] = {mode: sum(r["checks"]["first_attempt_ok"] for r in data[model][mode]) for mode in MODES}
    lines += ["## First-attempt acceptance (before D-rule retries)", "", "| Model | oracle | e2e |", "|---|---|---|"]
    lines += [f"| `{m}` | {first[m]['oracle']}/23 | {first[m]['e2e']}/23 |" for m in models]
    lines += ["", "## Side-by-side drafts", "", "Priority tickets (`" + "`, `".join(PRIORITY_TAGS) + "`) first, as required by the human checklist.", ""]
    ids = [r["ticket_id"] for r in data[models[0]]["oracle"]]
    ordered = [t for t in ids if set(tags[t]) & set(PRIORITY_TAGS)] + [t for t in ids if not set(tags[t]) & set(PRIORITY_TAGS)]
    for mode in MODES:
        lines += [f"### Mode: {mode}", ""]
        for ticket_id in ordered:
            lines += [f"#### {ticket_id} — tags: {', '.join(tags[ticket_id])}", ""]
            for model in models:
                record = next(r for r in data[model][mode] if r["ticket_id"] == ticket_id)
                cls = record["classification"]
                lines += [f"**`{model}`** · classification: {cls['issue_type']} / {cls['urgency']} / {cls['resolution_action']}"
                          f" · refund_caution={cls['requires_refund_caution']}", ""] + _draft_block(record)
    atomic_write_text(out, "\n".join(lines) + "\n")
    return result


def main() -> int:
    write_report()
    print(f"wrote {OUT / 'report.md'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
