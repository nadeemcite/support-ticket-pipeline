"""Stage 4 AI audit (PLAN §1 step 2): pytest (stages 1-4) with coverage, the drafting eval reports
(run ``python -m evals.drafting_eval`` first; results are cached), escalation and grounding review reports,
the blind calibration sheet, exit-criteria runs, and audit/stage-4/AUDIT_SUMMARY.md.

Usage: python scripts/audit_stage4.py   (needs keys in .env for the dev-model exit-criteria run)
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

from evals import calibration, report_drafting  # noqa: E402
from evals.classification_eval import EVAL_MODELS, frozen_inputs  # noqa: E402
from evals.drafting_eval import MODES, OUT as EVAL_OUT, gold_classification  # noqa: E402
from pipeline.config import Config  # noqa: E402
from pipeline.escalate import decide  # noqa: E402
from pipeline.io_utils import atomic_write_text, sha256_file  # noqa: E402
from pipeline.runner import run  # noqa: E402
from pipeline.schemas import Classification  # noqa: E402
from scripts.audit_stage1 import git_sha, md_escape, rel  # noqa: E402

OUT = ROOT / "audit" / "stage-4"
STAGE4_MODULES = ["pipeline/guards.py", "pipeline/grounding.py", "pipeline/escalate.py", "pipeline/draft.py", "pipeline/language.py", "pipeline/prompts.py", "pipeline/stages.py"]
COVERAGE_GATE = 90.0


def run_pytest() -> dict:
    junit = OUT / "pytest.xml"
    cmd = [sys.executable, "-m", "pytest", "-m", "(stage1 or stage2 or stage3 or stage4) and not live", "-q", "-p", "no:cacheprovider",
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
    covered = {l.split()[0]: (int(l.split()[1]), int(l.split()[2])) for l in coverage_lines if l.split() and l.split()[0] in STAGE4_MODULES}
    statements = sum(s for s, _ in covered.values())
    coverage = 100.0 * (statements - sum(m for _, m in covered.values())) / statements if statements else 0.0
    return {"returncode": result.returncode, "totals": totals, "per_file": per_file, "coverage": coverage}


def write_pytest_summary(tests: dict) -> None:
    t = tests["totals"]
    passed = t["tests"] - t["failures"] - t["errors"] - t["skipped"]
    lines = ["# Stage 4 — pytest summary", "",
             "- Command: `pytest -m \"(stage1 or stage2 or stage3 or stage4) and not live\" --cov=pipeline --cov=run_pipeline` (earlier stages re-run as regression)",
             f"- Result: **{passed}/{t['tests']} passed**, {t['failures']} failed, {t['errors']} errors, {t['skipped']} skipped",
             f"- Line coverage, Stage 4 modules ({', '.join(f'`{m}`' for m in STAGE4_MODULES)}): **{tests['coverage']:.1f}%** (gate ≥ {COVERAGE_GATE:.0f}%)",
             "", "| Test module | Passed | Failed |", "|---|---|---|"]
    lines += [f"| `{m}.py` | {p} | {f} |" for m, (p, f) in sorted(tests["per_file"].items())]
    atomic_write_text(OUT / "pytest_summary.md", "\n".join(lines) + "\n")


ARTIFACTS = ("draft_responses.json", "grounding_flags.json", "escalations.json")


def exit_criteria(workdir: Path) -> list[dict]:
    """Dev-model run on the root inputs, the same run repeated (cache), and two offline stub runs."""
    specs = [
        ("root, dev model glm-5.2 (ollama), fresh", "dev", dict(provider="ollama", model="glm-5.2", retriever="embedding")),
        ("root, dev model glm-5.2, rerun (same classifications via cache)", "dev", dict(provider="ollama", model="glm-5.2", retriever="embedding")),
        ("root, stub (offline) #1", "stub1", dict(provider="stub", model="stub", retriever="tfidf")),
        ("root, stub (offline) #2", "stub2", dict(provider="stub", model="stub", retriever="tfidf")),
    ]
    rows = []
    for name, folder, settings in specs:
        out = workdir / folder
        out.mkdir(exist_ok=True)
        if not (out / ".cache").exists():
            (out / ".cache").symlink_to(ROOT / ".cache", target_is_directory=True)
        outcome = run(Config(tickets_path=ROOT / "tickets.json", kb_path=ROOT / "kb_articles.json", out_dir=out, **settings))
        counts = outcome.manifest.get("counts", {})
        data = {a: json.loads((out / a).read_text()) if (out / a).exists() else None for a in ARTIFACTS}
        rows.append({
            "name": name, "exit_code": outcome.exit_code, "final_stage": outcome.manifest["final_stage"],
            "present": all(data.values()), "drafts": len((data["draft_responses.json"] or {}).get("drafts", [])),
            "escalations": len((data["escalations.json"] or {}).get("escalations", [])),
            "fallbacks": counts.get("draft_fallbacks"), "retries": counts.get("draft_retries"), "flags": counts.get("grounding_flags"),
            "escalation_bytes": (out / "escalations.json").read_bytes() if (out / "escalations.json").exists() else b"",
            "draft_bytes": (out / "draft_responses.json").read_bytes() if (out / "draft_responses.json").exists() else b"",
            "summary": [(d["ticket_id"], d["citations"], d["meta"]["attempts"], d["meta"]["violations_resolved"]) for d in (data["draft_responses.json"] or {}).get("drafts", [])],
            "escalated": [(e["ticket_id"], e["escalate"], e["target_queue"]) for e in (data["escalations.json"] or {}).get("escalations", [])],
        })
    return rows


def _gold_ok(g: dict, escalation) -> bool:
    return escalation.escalate in g["escalate"] and escalation.target_queue.value in g["target_queue"]


def write_escalation_report(evidence: dict, gold: dict, data: dict) -> dict:
    """Per ticket: classification -> rules fired -> queue -> reason with KB clause, for gold-oracle and each model's e2e classification."""
    articles = {a.article_id: a for arts in evidence.values() for a in arts}
    models = [m for _, m in EVAL_MODELS]
    lines = ["# Stage 4 — escalation report", "",
             "`escalate.decide(classification, retrieved evidence)` is a pure function. For every eval ticket this shows the rules that fired, the queue and the reason (with the quoted KB clause), "
             "for (a) the **gold-preferred** classification and (b) each eval model's **own** classification (e2e). ✅ = inside gold's acceptable `escalate`/`target_queue` lists.", ""]
    totals = {"oracle": [0, 0], **{m: [0, 0] for m in models}}
    body = []
    for ticket_id, g in gold.items():
        evidence_list = evidence[ticket_id]
        oracle = decide(gold_classification(ticket_id, gold, [a.article_id for a in evidence_list]), evidence_list)
        ok = _gold_ok(g, oracle)
        totals["oracle"][0] += ok
        totals["oracle"][1] += 1
        c = gold_classification(ticket_id, gold, [])
        body += [f"### {ticket_id} — {', '.join(g.get('tags', []))}", "",
                 f"Evidence: {[a.article_id for a in evidence_list] or 'none'} · gold: escalate {g['escalate']}, queue {g['target_queue']}", "",
                 "| Source | Classification (issue / urgency / action / refund caution) | Rules | Escalate | Queue | |", "|---|---|---|---|---|---|",
                 f"| gold-preferred | {c.issue_type.value} / {c.urgency.value} / {c.resolution_action.value} / {c.requires_refund_caution} | {' '.join(oracle.meta.rules_fired)} | {oracle.escalate} | {oracle.target_queue.value} | {'✅' if ok else '❌'} |"]
        reasons = [("gold-preferred", oracle.reason)]
        for model in models:
            record = next(r for r in data[model]["e2e"] if r["ticket_id"] == ticket_id)
            cls = Classification.model_validate(record["classification"])
            result = decide(cls, evidence_list)
            ok = _gold_ok(g, result)
            totals[model][0] += ok
            totals[model][1] += 1
            body.append(f"| `{model}` e2e | {cls.issue_type.value} / {cls.urgency.value} / {cls.resolution_action.value} / {cls.requires_refund_caution} | {' '.join(result.meta.rules_fired)} | {result.escalate} | {result.target_queue.value} | {'✅' if ok else '❌'} |")
            reasons.append((f"{model} e2e", result.reason))
        body += [""] + [f"- **{who}:** {md_escape(reason)}" for who, reason in reasons] + [""]
    lines += ["## Agreement with gold", "", "| Source | Matches gold-acceptable | |", "|---|---|---|"]
    lines += [f"| {'gold-preferred (oracle)' if k == 'oracle' else f'`{k}` e2e'} | {a}/{b} | {'✅' if a == b else '⚠️'} |" for k, (a, b) in totals.items()]
    lines += ["", "## Per ticket", ""] + body
    atomic_write_text(OUT / "escalation_report.md", "\n".join(lines) + "\n")
    return totals


def write_grounding_review(data: dict, articles: dict) -> int:
    rows = []
    for model in data:
        for mode in MODES:
            for record in data[model][mode]:
                for flag in record["checks"]["grounding_flags"]:
                    rows.append((model, mode, record["ticket_id"], flag))
    lines = ["# Stage 4 — grounding flags review", "",
             "Every G1–G3 flag raised on the eval drafts, with the cited KB text next to it. Flags never block a draft. "
             "Mark each **TP** (the draft claims something its cited text doesn't support) or **FP** (heuristic too strict), and note any tuning.", "",
             f"Total flags: **{len(rows)}** across {2 * len(MODES) * 23} drafts.", ""]
    if not rows:
        lines.append("No flags were raised.")
    for index, (model, mode, ticket_id, flag) in enumerate(rows, start=1):
        cited = "\n".join(f"[{c}] {articles[c].content}" for c in flag["cited_articles_checked"] if c in articles) or "(no cited text)"
        lines += [f"### F{index} — {ticket_id} · `{model}` · {mode} · {flag['check']} ({flag['claim_type']})", "",
                  f"- Sentence: “{md_escape(flag['sentence'])}”", f"- Unsupported: {flag['unsupported_tokens']} · best overlap with cited text: {flag['overlap']}",
                  "- Cited KB text:", "", "  ```", *[f"  {l}" for l in cited.splitlines()], "  ```", "", "- Human verdict: ☐ TP ☐ FP · Note: ______", ""]
    atomic_write_text(OUT / "grounding_flags_review.md", "\n".join(lines) + "\n")
    return len(rows)


def main() -> int:
    load_dotenv(ROOT / ".env", override=False)
    OUT.mkdir(parents=True, exist_ok=True)
    if not (EVAL_OUT / "drafting_eval.json").exists():
        print("run `python -m evals.drafting_eval` first", file=sys.stderr)
        return 2
    tests = run_pytest()
    write_pytest_summary(tests)
    data = report_drafting.load()
    eval_rows = report_drafting.write_report(data)
    calibration.build()
    tickets, evidence, gold = frozen_inputs()
    esc_totals = write_escalation_report(evidence, gold, data)
    kb = {a.article_id: a for arts in evidence.values() for a in arts}
    flag_count = write_grounding_review(data, kb)
    with tempfile.TemporaryDirectory() as workdir:
        runs = exit_criteria(Path(workdir))

    t = tests["totals"]
    passed = t["tests"] - t["failures"] - t["errors"] - t["skipped"]
    dev, rerun, s1, s2 = runs
    esc_same = dev["escalation_bytes"] == rerun["escalation_bytes"] != b"" and s1["escalation_bytes"] == s2["escalation_bytes"] != b""
    hard = [
        ("Stage 1–4 tests pass (offline)", "100%", f"{passed}/{t['tests']}", passed == t["tests"] and tests["returncode"] == 0),
        ("Line coverage, Stage 4 modules", f"≥ {COVERAGE_GATE:.0f}%", f"{tests['coverage']:.1f}%", tests["coverage"] >= COVERAGE_GATE),
        ("Dev-model run on root inputs (glm-5.2) produces all three artifacts", "exit 0, 3 drafts, 3 escalations", f"exit {dev['exit_code']}, {dev['drafts']} drafts, {dev['escalations']} escalations", dev["exit_code"] == 0 and dev["present"] and dev["drafts"] == 3 and dev["escalations"] == 3),
        ("Escalations byte-identical across repeated runs (dev rerun, stub ×2)", "identical", "identical" if esc_same else "different", esc_same),
        ("Escalation rules reproduce gold from gold-preferred classifications", "23/23", f"{esc_totals['oracle'][0]}/{esc_totals['oracle'][1]}", esc_totals["oracle"][0] == esc_totals["oracle"][1] == 23),
    ]
    soft: list[tuple[str, str, str, bool]] = []
    for model, mode in eval_rows:
        for name, threshold, value, ok, is_hard in eval_rows[(model, mode)]:
            (hard if is_hard else soft).append((f"`{model}` · {mode}: {name}", threshold, value, ok))
    for _, model in EVAL_MODELS:
        a, b = esc_totals[model]
        soft.append((f"`{model}` e2e escalation decisions inside gold", "23/23", f"{a}/{b}", a == b))
    green = all(ok for *_, ok in hard)
    lines = [
        "# Stage 4 — AI audit summary", "",
        f"- Generated: {datetime.now(UTC).strftime('%Y-%m-%d %H:%M UTC')} · git: `{git_sha()}` · Python {sys.version.split()[0]}",
        f"- Input hashes (sha256): `data/eval/tickets.json` {sha256_file(ROOT / 'data/eval/tickets.json')[:16]}… · `gold.json` {sha256_file(ROOT / 'data/eval/gold.json')[:16]}…",
        f"- Eval models: {', '.join(f'`{m}`' for _, m in EVAL_MODELS)} × modes oracle + e2e × 23 tickets, cross-judged (each model judges the other); prompts `draft.v1`, `judge.v1`; temperature 0, seed 42.",
        f"- **AI gates: {'ALL HARD GATES GREEN ✅' if green else 'NOT GREEN ❌'}** — the stage still needs human review and sign-off in `PLAN.md` before it is closed.",
        "- **Pending human:** judge–human agreement on the 8 calibration drafts (≥ 75% within ±1) decides whether judge scores are authoritative or advisory. Until the sheet is scored the judge faithfulness gate is provisional.",
        "", "## Hard gates", "", "| Gate | Threshold | Value | |", "|---|---|---|---|",
    ]
    lines += [f"| {n} | {th} | {v} | {'✅' if ok else '❌'} |" for n, th, v, ok in hard]
    lines += ["", "## Soft gates", "", "| Gate | Threshold | Value | |", "|---|---|---|---|"]
    lines += [f"| {n} | {th} | {v} | {'✅' if ok else '⚠️'} |" for n, th, v, ok in soft]
    lines += ["", "## Exit-criteria runs", "", "| Run | Exit | Final stage | Drafts | Escalations | Draft fallbacks | Retries | Grounding flags |", "|---|---|---|---|---|---|---|---|",
              *[f"| {r['name']} | {r['exit_code']} | {r['final_stage']} | {r['drafts']} | {r['escalations']} | {r['fallbacks']} | {r['retries']} | {r['flags']} |" for r in runs]]
    lines += ["", "Dev-model escalation decisions: " + "; ".join(f"{t}: {'escalate → ' + q if e else 'no'}" for t, e, q in dev["escalated"]),
              "", "Dev-model draft attempts / rules hit before acceptance: " + "; ".join(f"{t}: {a} attempt(s) {v or ''}" for t, _, a, v in dev["summary"]),
              "", f"Note: the *fresh* dev run and the stub runs call the model/stub afresh, so drafts and labels can differ between those; escalations are a pure function of the classifications, "
              f"and are byte-identical whenever the classifications are (dev rerun uses the LLM cache). Drafts byte-identical on dev rerun: {'yes' if dev['draft_bytes'] == rerun['draft_bytes'] else 'no'}.",
              "", "## Reports for human review", "",
              "- `evals/report.md` — gates per model and mode, **side-by-side drafts** (priority tickets first) with citations, judge scores + rationale, grounding flags, hard-check results",
              f"- `escalation_report.md` — classification → rules → queue → reason with KB clause, for gold-oracle and both models (e2e)",
              f"- `calibration_sheet.md` — **8 blind drafts to score by hand**; then run `python -m evals.calibration score`",
              f"- `grounding_flags_review.md` — {flag_count} flags with the cited KB text beside each",
              "- `pytest_summary.md`, `coverage.txt`, `pytest.xml`; raw per-model results in `evals/<model>/drafts_<mode>.jsonl`",
              ]
    atomic_write_text(OUT / "AUDIT_SUMMARY.md", "\n".join(lines) + "\n")
    print(f"Stage 4 audit written to {rel(OUT)} — hard gates {'green' if green else 'NOT green'}")
    return 0 if green else 1


if __name__ == "__main__":
    sys.exit(main())
