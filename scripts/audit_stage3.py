"""Stage 3 AI audit (PLAN §1 step 2): pytest (stages 1-3) with coverage, the 2-model classification eval
(run first with ``python -m evals.classification_eval``; results are cached), the reports, exit-criteria
runs, and audit/stage-3/AUDIT_SUMMARY.md.

Usage: python scripts/audit_stage3.py   (needs keys in .env for the dev-model exit-criteria run)
"""

import json
import re
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

from evals import report_classification  # noqa: E402
from evals.classification_eval import EVAL_MODELS, OUT as EVAL_OUT  # noqa: E402
from pipeline.config import Config  # noqa: E402
from pipeline.io_utils import atomic_write_text, sha256_file  # noqa: E402
from pipeline.runner import run  # noqa: E402
from scripts.audit_stage1 import git_sha, rel  # noqa: E402

OUT = ROOT / "audit" / "stage-3"
STAGE3_MODULES = ["pipeline/llm.py", "pipeline/classify.py", "pipeline/prompts.py", "pipeline/stub.py", "pipeline/stages.py", "pipeline/orchestrator.py"]
COVERAGE_GATE = 90.0


def run_pytest() -> dict:
    junit = OUT / "pytest.xml"
    cmd = [sys.executable, "-m", "pytest", "-m", "(stage1 or stage2 or stage3) and not live", "-q", "-p", "no:cacheprovider",
           f"--junitxml={junit}", "--cov=pipeline", "--cov=run_pipeline", "--cov-report=term-missing"]
    result = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
    coverage_lines = [l for l in result.stdout.splitlines() if re.match(r"^(Name|-+|TOTAL|pipeline/|run_pipeline)", l)]
    atomic_write_text(OUT / "coverage.txt", "\n".join(coverage_lines) + "\n")
    junit.write_text(re.sub(r' timestamp="[^"]+"| hostname="[^"]+"', "", junit.read_text()))
    suite = ET.parse(junit).getroot().find("testsuite")
    totals = {k: int(suite.get(k, 0)) for k in ("tests", "failures", "errors", "skipped")}
    per_file: dict[str, list[int]] = {}
    for case in suite.iter("testcase"):
        module = case.get("classname", "").split(".")[-1]
        passed = case.find("failure") is None and case.find("error") is None
        per_file.setdefault(module, [0, 0])[0 if passed else 1] += 1
    covered = {l.split()[0]: (int(l.split()[1]), int(l.split()[2])) for l in coverage_lines if l.split() and l.split()[0] in STAGE3_MODULES}
    statements = sum(s for s, _ in covered.values())
    coverage = 100.0 * (statements - sum(m for _, m in covered.values())) / statements if statements else 0.0
    return {"returncode": result.returncode, "totals": totals, "per_file": per_file, "coverage": coverage}


def exit_criteria(workdir: Path) -> list[dict]:
    """Dev-model run on the root inputs, plus two identical offline stub runs (must be byte-identical)."""
    rows = []
    specs = [
        ("root, dev model glm-5.2 (ollama)", dict(provider="ollama", model="glm-5.2", retriever="embedding")),
        ("root, stub (offline) #1", dict(provider="stub", model="stub", retriever="tfidf")),
        ("root, stub (offline) #2", dict(provider="stub", model="stub", retriever="tfidf")),
    ]
    for index, (name, settings) in enumerate(specs):
        out = workdir / str(index)
        out.mkdir(parents=True)
        (out / ".cache").symlink_to(ROOT / ".cache", target_is_directory=True)
        config = Config(tickets_path=ROOT / "tickets.json", kb_path=ROOT / "kb_articles.json", out_dir=out, **settings)
        outcome = run(config)
        artifact = out / "ticket_classification.json"
        log = (out / "llm_calls.jsonl").read_text().splitlines() if (out / "llm_calls.jsonl").exists() else []
        rows.append({
            "name": name, "exit_code": outcome.exit_code, "final_stage": outcome.manifest["final_stage"],
            "classifications": len(json.loads(artifact.read_text())["classifications"]) if artifact.exists() else 0,
            "log_lines": len(log), "bytes": artifact.read_bytes() if artifact.exists() else b"",
            "fallbacks": outcome.manifest.get("counts", {}).get("classification_fallbacks"),
            "labels": [(c["ticket_id"], c["issue_type"], c["urgency"], c["resolution_action"]) for c in json.loads(artifact.read_text())["classifications"]] if artifact.exists() else [],
        })
    return rows


def write_pytest_summary(tests: dict) -> None:
    t = tests["totals"]
    passed = t["tests"] - t["failures"] - t["errors"] - t["skipped"]
    lines = ["# Stage 3 — pytest summary", "",
             "- Command: `pytest -m \"(stage1 or stage2 or stage3) and not live\" --cov=pipeline --cov=run_pipeline` (earlier stages re-run as regression)",
             f"- Result: **{passed}/{t['tests']} passed**, {t['failures']} failed, {t['errors']} errors, {t['skipped']} skipped",
             f"- Line coverage, Stage 3 modules ({', '.join(f'`{m}`' for m in STAGE3_MODULES)}): **{tests['coverage']:.1f}%** (gate ≥ {COVERAGE_GATE:.0f}%)",
             "", "| Test module | Passed | Failed |", "|---|---|---|"]
    lines += [f"| `{m}.py` | {p} | {f} |" for m, (p, f) in sorted(tests["per_file"].items())]
    atomic_write_text(OUT / "pytest_summary.md", "\n".join(lines) + "\n")


def main() -> int:
    load_dotenv(ROOT / ".env", override=False)
    OUT.mkdir(parents=True, exist_ok=True)
    if not (EVAL_OUT / "classification_eval.json").exists():
        print("run `python -m evals.classification_eval` first", file=sys.stderr)
        return 2
    tests = run_pytest()
    write_pytest_summary(tests)
    summary, results = report_classification.load()
    report_classification.write_report(summary, results)
    matches = report_classification.write_trace_sample(summary, results)
    with tempfile.TemporaryDirectory() as workdir:
        runs = exit_criteria(Path(workdir))

    t = tests["totals"]
    passed = t["tests"] - t["failures"] - t["errors"] - t["skipped"]
    hard = [
        ("Stage 1–3 tests pass (offline)", "100%", f"{passed}/{t['tests']}", passed == t["tests"] and tests["returncode"] == 0),
        ("Line coverage, Stage 3 modules", f"≥ {COVERAGE_GATE:.0f}%", f"{tests['coverage']:.1f}%", tests["coverage"] >= COVERAGE_GATE),
        ("Dev-model run on root inputs (glm-5.2) produces 3 classifications + log", "exit 0", f"exit {runs[0]['exit_code']}, {runs[0]['classifications']} records, {runs[0]['log_lines']} log lines", runs[0]["exit_code"] == 0 and runs[0]["classifications"] == 3 and runs[0]["log_lines"] >= 3),
        ("Stub reproduces a run fully offline (two runs byte-identical)", "identical", "identical" if runs[1]["bytes"] == runs[2]["bytes"] and runs[1]["bytes"] else "different", runs[1]["bytes"] == runs[2]["bytes"] != b""),
        ("Trace sample: recomputed prompt hashes match the log", "5/5", f"{sum(matches)}/{len(matches)}", all(matches) and len(matches) == 5),
    ]
    soft: list[tuple[str, str, str, bool]] = []
    for _, model in EVAL_MODELS:
        for name, threshold, value, ok, is_hard in report_classification.gates(summary["models"][model]["score"]):
            (hard if is_hard else soft).append((f"`{model}`: {name}", threshold, value, ok))
    green = all(ok for *_, ok in hard)
    dev = summary["models"].get("glm-5.2", {}).get("score")
    lines = [
        "# Stage 3 — AI audit summary", "",
        f"- Generated: {datetime.now(UTC).strftime('%Y-%m-%d %H:%M UTC')} · git: `{git_sha()}` · Python {sys.version.split()[0]}",
        f"- Input hashes (sha256): `data/eval/tickets.json` {sha256_file(ROOT / 'data/eval/tickets.json')[:16]}… · `gold.json` {sha256_file(ROOT / 'data/eval/gold.json')[:16]}…",
        f"- Eval models: {', '.join(f'`{m}`' for _, m in EVAL_MODELS)} × {summary['repeats']} repeats × {summary['tickets']} tickets; prompt `classify.v1`; temperature 0, seed 42.",
        f"- **AI gates: {'ALL HARD GATES GREEN ✅' if green else 'NOT GREEN ❌'}** — the stage still needs human review and sign-off in `PLAN.md` before it is closed.",
        "", "## Hard gates", "", "| Gate | Threshold | Value | |", "|---|---|---|---|",
    ]
    lines += [f"| {n} | {th} | {v} | {'✅' if ok else '❌'} |" for n, th, v, ok in hard]
    lines += ["", "## Soft gates", "", "| Gate | Threshold | Value | |", "|---|---|---|---|"]
    lines += [f"| {n} | {th} | {v} | {'✅' if ok else '⚠️'} |" for n, th, v, ok in soft]
    lines += [
        "", "## Cross-model agreement (repeat 1)", "",
        "| Field | Agree | Cohen's κ |", "|---|---|---|",
        *[f"| `{f}` | {d['agree']}/{d['of']} | {d['kappa']} |" for f, d in summary["agreement"].items()],
    ]
    gold = {g["ticket_id"]: g for g in json.loads((ROOT / "data/eval/gold.json").read_text())["expectations"]}
    justification = []
    for _, model in EVAL_MODELS:
        stable = summary["models"][model]["score"]["stability"]
        if stable["stable_tickets"] / stable["tickets"] < 0.90:
            rows = report_classification.instability(results[model], gold)
            justification += [
                f"**`{model}` repeat stability {stable['stable_tickets']}/{stable['tickets']} (soft gate missed).** Unstable tickets:",
                "",
                *[f"- {r['ticket_id']}: changed {', '.join(r['changed_fields'])}; every variant gold-acceptable: "
                  f"{'yes' if r['all_acceptable'] else '**no**'}; escalation outcome changes: {'**yes**' if r['escalation_changes'] else 'no'}" for r in rows],
                "",
                "Justification: " + (
                    "every variation stays within gold's acceptable values and none changes whether the ticket escalates "
                    "(rules E1/E2), so downstream behaviour is unaffected. temperature=0 does not make this hosted model "
                    "deterministic; the pipeline's LLM cache makes reruns identical."
                    if all(r["all_acceptable"] and not r["escalation_changes"] for r in rows)
                    else "at least one variation is outside gold or changes escalation — needs reviewer attention."
                ),
                "",
            ]
    if justification:
        lines += ["", "## Soft-gate misses and justification", "", *justification]
    if dev:
        lines += ["", "## Dev model (information only, not a gate)", "",
                  f"`glm-5.2`, 1 repeat: issue_type {dev['accuracy']['issue_type']['lenient']:.1%}, urgency {dev['accuracy']['urgency']['lenient']:.1%}, "
                  f"resolution_action {dev['accuracy']['resolution_action']['lenient']:.1%}, refund caution {dev['accuracy']['requires_refund_caution']['lenient']:.1%}, "
                  f"fallbacks {dev['fallback_rate']:.1%} (lenient accuracy)."]
    lines += [
        "", "## Exit-criteria runs", "", "| Run | Exit | Final stage | Classifications | Log lines | Fallbacks |", "|---|---|---|---|---|---|",
        *[f"| {r['name']} | {r['exit_code']} | {r['final_stage']} | {r['classifications']} | {r['log_lines']} | {r['fallbacks']} |" for r in runs],
        "", f"Dev-model labels on the samples: " + "; ".join(f"{t}: {i}/{u}/{a}" for t, i, u, a in runs[0]["labels"]),
        "", "## Reports for human review", "",
        "- `evals/report.md` — gates per model, accuracy (lenient/strict), confusion matrices, **disagreement table** with both rationales, stability, overrides, latency/tokens/cost",
        "- `llm_trace_sample.md` — 5 log lines traced to re-built masked prompts (hash recomputed), raw outputs and final records",
        "- `pytest_summary.md`, `coverage.txt`, `pytest.xml`; raw per-model results in `evals/<model>/results.jsonl`",
        "", "## Notes for the reviewer", "",
        "- **E-2014 (outage, VIP):** `gpt-6.1-sol` chose `request_more_info` in 2 of 3 repeats (gold allows `needs_human_escalation` or `answer_from_kb`). "
        "Its rationale: KB-011's escalation condition depends on whether the status page lists an incident, which the ticket doesn't say. Decide whether this is a model error or whether gold should also accept `request_more_info`.",
        "- **`urgency` for VIP billing escalations (E-2018, E-2019):** `gpt-6.1-sol` says `high` every time, gold says `medium` (E-2019 also allows `low`). Policy question: does VIP status raise urgency for non-blocking billing issues?",
        "- **`issue_type` how_to vs billing (T-1003, E-2005, E-2009):** the models split; gold accepts both, so these are not misses.",
        "- Cost: LiteLLM has no price for `gpt-6.1-sol` / Ollama Cloud models, so cost shows `n/a`; token counts are reported instead.",
    ]
    atomic_write_text(OUT / "AUDIT_SUMMARY.md", "\n".join(lines) + "\n")
    print(f"Stage 3 audit written to {rel(OUT)} — hard gates {'green' if green else 'NOT green'}")
    return 0 if green else 1


if __name__ == "__main__":
    sys.exit(main())
