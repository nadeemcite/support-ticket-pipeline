"""Stage 1 AI audit (PLAN §1 step 2): runs pytest + coverage, runs the pipeline on the root inputs and
every fixture, and writes the human-review reports to audit/stage-1/.

Usage: python scripts/audit_stage1.py
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

from pipeline import pii  # noqa: E402
from pipeline.config import Config  # noqa: E402
from pipeline.io_utils import atomic_write_text, sha256_file  # noqa: E402
from pipeline.runner import run  # noqa: E402

OUT = ROOT / "audit" / "stage-1"
FIX = ROOT / "data" / "fixtures"
EVAL = ROOT / "data" / "eval"
STAGE1_MODULES = [
    "pipeline/__init__.py", "pipeline/config.py", "pipeline/io_utils.py", "pipeline/loader.py",
    "pipeline/normalise.py", "pipeline/orchestrator.py", "pipeline/pii.py", "pipeline/runner.py",
    "pipeline/schemas.py", "pipeline/stages.py", "pipeline/taxonomy.py", "run_pipeline.py",
]
COVERAGE_GATE = 90.0

FIXTURE_RUNS = [
    ("root", ROOT / "tickets.json", ROOT / "kb_articles.json", 0),
    ("eval_set", EVAL / "tickets.json", EVAL / "kb_articles.json", 0),
    ("edge_cases", FIX / "edge_cases/tickets.json", ROOT / "kb_articles.json", 0),
    ("empty_kb", ROOT / "tickets.json", FIX / "empty_kb/kb_articles.json", 0),
    ("empty_tickets", FIX / "empty_tickets/tickets.json", ROOT / "kb_articles.json", 0),
    ("replay_v2", FIX / "replay/tickets_v2.json", ROOT / "kb_articles.json", 0),
    ("malformed_invalid_json", FIX / "malformed/invalid_json.txt", ROOT / "kb_articles.json", 2),
    ("malformed_wrong_key", FIX / "malformed/wrong_top_level_key.json", ROOT / "kb_articles.json", 2),
]


def rel(path: Path) -> str:
    return str(Path(path).resolve().relative_to(ROOT))


def md_escape(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")


def git_sha() -> str:
    result = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True, text=True)
    return result.stdout.strip() if result.returncode == 0 else "no commits yet"


def run_pytest() -> dict:
    junit = OUT / "pytest.xml"
    cmd = [
        sys.executable, "-m", "pytest", "-m", "stage1", "-q", "-p", "no:cacheprovider",
        f"--junitxml={junit}", "--cov=pipeline", "--cov=run_pipeline", "--cov-report=term-missing",
    ]
    result = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
    coverage_lines = [line for line in result.stdout.splitlines() if re.match(r"^(Name|-+|TOTAL|pipeline/|run_pipeline)", line)]
    atomic_write_text(OUT / "coverage.txt", "\n".join(coverage_lines) + "\n")
    junit.write_text(re.sub(r' timestamp="[^"]+"| hostname="[^"]+"', "", junit.read_text()))

    suite = ET.parse(junit).getroot().find("testsuite")
    totals = {key: int(suite.get(key, 0)) for key in ("tests", "failures", "errors", "skipped")}
    per_file: dict[str, list[int]] = {}
    failed = []
    for case in suite.iter("testcase"):
        module = case.get("classname", "").split(".")[1] if "." in case.get("classname", "") else case.get("classname")
        passed = case.find("failure") is None and case.find("error") is None
        per_file.setdefault(module, [0, 0])[0 if passed else 1] += 1
        if not passed:
            failed.append(f"{case.get('classname')}::{case.get('name')}")

    covered = {}
    for line in coverage_lines:
        parts = line.split()
        if parts and parts[0] in STAGE1_MODULES:
            covered[parts[0]] = (int(parts[1]), int(parts[2]))
    statements = sum(s for s, _ in covered.values())
    missed = sum(m for _, m in covered.values())
    coverage = 100.0 * (statements - missed) / statements if statements else 0.0
    return {"returncode": result.returncode, "totals": totals, "per_file": per_file, "failed": failed, "coverage": coverage}


def run_fixtures(workdir: Path) -> list[dict]:
    results = []
    for name, tickets, kb, expected_exit in FIXTURE_RUNS:
        config = Config(provider="stub", model="stub", tickets_path=tickets, kb_path=kb, out_dir=workdir / name)
        outcome = run(config)
        normalised_path = config.artifacts_dir / "normalised_tickets.json"
        raw_values = []
        if tickets.suffix == ".json" and expected_exit == 0:
            for ticket in json.loads(tickets.read_text()).get("tickets", []):
                if isinstance(ticket, dict):
                    text = " ".join(str(v) for v in ticket.values() if isinstance(v, str))
                    raw_values += [d.value for d in pii.detect(text)]
        artifact_text = normalised_path.read_text() if normalised_path.exists() else ""
        manifest_text = (config.artifacts_dir / "run_manifest.json").read_text()
        leaks = [v for v in raw_values if v in artifact_text or v in manifest_text]
        results.append({
            "name": name,
            "tickets": rel(tickets),
            "kb": rel(kb),
            "expected_exit": expected_exit,
            "exit_code": outcome.exit_code,
            "final_stage": outcome.manifest["final_stage"],
            "accepted": outcome.manifest.get("counts", {}).get("tickets_accepted", "-"),
            "normalised_written": normalised_path.exists(),
            "manifest_written": (config.artifacts_dir / "run_manifest.json").exists(),
            "raw_pii_values_in_input": len(raw_values),
            "raw_pii_leaks": len(leaks),
            "error": outcome.error,
            "manifest": outcome.manifest,
            "normalised": json.loads(artifact_text) if artifact_text else None,
        })
    return results


def write_pytest_summary(result: dict) -> None:
    totals = result["totals"]
    passed = totals["tests"] - totals["failures"] - totals["errors"] - totals["skipped"]
    lines = [
        "# Stage 1 — pytest summary",
        "",
        f"- Command: `pytest -m stage1 --cov=pipeline --cov=run_pipeline`",
        f"- Result: **{passed}/{totals['tests']} passed**, {totals['failures']} failed, {totals['errors']} errors, {totals['skipped']} skipped",
        f"- Line coverage, Stage 1 modules: **{result['coverage']:.1f}%** (gate ≥ {COVERAGE_GATE:.0f}%) — details in `coverage.txt`",
        "",
        "| Test module | Passed | Failed |",
        "|---|---|---|",
    ]
    lines += [f"| `{module}.py` | {p} | {f} |" for module, (p, f) in sorted(result["per_file"].items())]
    if result["failed"]:
        lines += ["", "## Failures", ""] + [f"- `{name}`" for name in result["failed"]]
    atomic_write_text(OUT / "pytest_summary.md", "\n".join(lines) + "\n")


def write_pii_report(fixture_results: list[dict]) -> dict:
    gold = {g["ticket_id"]: g for g in json.loads((EVAL / "gold.json").read_text())["expectations"]}
    raw = {t["ticket_id"]: t for t in json.loads((EVAL / "tickets.json").read_text())["tickets"]}
    eval_run = next(r for r in fixture_results if r["name"] == "eval_set")
    normalised = {t["ticket_id"]: t for t in eval_run["normalised"]["tickets"]}

    matches = 0
    rows = []
    for ticket_id, ticket in raw.items():
        found = sorted(item["type"] for item in normalised[ticket_id]["pii_summary"]["items"])
        expected = sorted(gold[ticket_id]["pii_expected"])
        ok = found == expected
        matches += ok
        rows.append((ticket_id, ticket, normalised[ticket_id], found, expected, ok))

    cases = json.loads((FIX / "pii_cases.json").read_text())["cases"]
    case_rows = []
    case_pass = 0
    for case in cases:
        result = pii.mask(case["text"])
        types = [d.type.value for d in result.detections]
        ok = types == case["expected"] and result.text == case["masked"]
        case_pass += ok
        case_rows.append((case, types, result.text, ok))

    lines = [
        "# Stage 1 — PII masking report",
        "",
        "> All PII below is **synthetic** test data (see `data/README.md`). The original text is shown so the reviewer can confirm nothing was missed; it exists only in the input files, never in pipeline artifacts.",
        "",
        "## Summary",
        "",
        f"- Eval tickets whose detected PII types equal `gold.pii_expected`: **{matches}/{len(raw)}**",
        f"- `pii_cases.json` fixtures passing (types + exact masked text): **{case_pass}/{len(cases)}**",
        f"- Raw PII values found in `normalised_tickets.json` / `run_manifest.json` across all fixture runs: **{sum(r['raw_pii_leaks'] for r in fixture_results)}**",
        "",
        "## Eval tickets with PII (original vs masked)",
        "",
        "| Ticket | Original | Masked (what every later stage and API sees) | Detected | Expected | |",
        "|---|---|---|---|---|---|",
    ]
    for ticket_id, ticket, norm, found, expected, ok in rows:
        if found or expected:
            lines.append(
                f"| {ticket_id} | {md_escape(ticket['message'])} | {md_escape(norm['message'])} | "
                f"{', '.join(found) or '—'} | {', '.join(expected) or '—'} | {'✅' if ok else '❌'} |"
            )
    lines += [
        "",
        "## Eval tickets without PII (must be unchanged by masking)",
        "",
        "| Ticket | Detected | Expected | Text unchanged | |",
        "|---|---|---|---|---|",
    ]
    for ticket_id, ticket, norm, found, expected, ok in rows:
        if not found and not expected:
            unchanged = norm["message"] == " ".join(ticket["message"].split()) and norm["subject"] == " ".join(ticket["subject"].split())
            lines.append(f"| {ticket_id} | — | — | {'yes' if unchanged else '**no**'} | {'✅' if ok and unchanged else '❌'} |")
    lines += [
        "",
        "## Detector fixtures (`data/fixtures/pii_cases.json`)",
        "",
        "Cases with an empty expected list are **false-positive guards** (order IDs, dates, amounts, error codes, Luhn-invalid numbers, advice text).",
        "",
        "| ID | Input | Masked output | Detected | Expected | |",
        "|---|---|---|---|---|---|",
    ]
    for case, types, masked, ok in case_rows:
        lines.append(
            f"| {case['id']} | {md_escape(case['text'])} | {md_escape(masked)} | {', '.join(types) or '—'} | "
            f"{', '.join(case['expected']) or '— (guard)'} | {'✅' if ok else '❌'} |"
        )
    lines += [
        "",
        "## How placeholders and hashes appear in the artifact",
        "",
        "`normalised_tickets.json` stores only masked text plus a `pii_summary` (type, placeholder, salted hash). Example for E-2007:",
        "",
        "```json",
        json.dumps(normalised["E-2007"]["pii_summary"], indent=2),
        "```",
    ]
    atomic_write_text(OUT / "pii_masking_report.md", "\n".join(lines) + "\n")
    return {"eval_matches": matches, "eval_total": len(raw), "cases_pass": case_pass, "cases_total": len(cases)}


def write_normalisation_report(fixture_results: list[dict]) -> None:
    edge = next(r for r in fixture_results if r["name"] == "edge_cases")
    raw_tickets = json.loads((FIX / "edge_cases/tickets.json").read_text())["tickets"]
    normalised = edge["normalised"]["tickets"]
    by_index = {t["input_index"]: t for t in normalised}

    lines = [
        "# Stage 1 — normalisation report",
        "",
        "Source: `data/fixtures/edge_cases/tickets.json` (expectations in `expected.json`).",
        "",
        "## Rejected and duplicate records (from `run_manifest.json`)",
        "",
        "| Input index | ticket_id | Outcome | Rule | Reason |",
        "|---|---|---|---|---|",
    ]
    for item in edge["manifest"]["rejected_tickets"]:
        lines.append(f"| {item['input_index']} | — | rejected | {item['rule']} | {item['reason']} |")
    for item in edge["manifest"]["duplicate_tickets"]:
        lines.append(f"| {item['input_index']} | {item['ticket_id']} | dropped (duplicate; first occurrence kept) | {item['rule']} | repeated ticket_id |")
    lines += [
        "",
        "## Before → after (accepted tickets)",
        "",
        "| Input index | ticket_id | Field | Before | After |",
        "|---|---|---|---|---|",
    ]
    for index, raw in enumerate(raw_tickets):
        if index not in by_index:
            continue
        norm = by_index[index]
        for field in ("language", "customer_tier", "subject", "message"):
            before = raw.get(field, "∅ (missing)")
            before_repr = json.dumps(before, ensure_ascii=True) if isinstance(before, str) else str(before)
            after = norm[field]
            if before != after:
                lines.append(f"| {index} | {norm['ticket_id']} | {field} | `{md_escape(before_repr)}` | `{md_escape(json.dumps(after, ensure_ascii=False))}` |")
        if norm["insufficient_content"]:
            lines.append(f"| {index} | {norm['ticket_id']} | insufficient_content | — | `true` (rule I6) |")
        if norm["extra"]:
            lines.append(f"| {index} | {norm['ticket_id']} | extra (I2) | top-level unknown fields | `{md_escape(json.dumps(norm['extra']))}` |")
        if norm["notes"]:
            lines.append(f"| {index} | {norm['ticket_id']} | notes | — | {md_escape('; '.join(norm['notes']))} |")
    lines += [
        "",
        "Unchanged tickets/fields are omitted. Idempotency (`normalise(normalise(x)) == normalise(x)`) and byte-identical reruns are asserted in `test_normalise.py` and `test_manifest.py`.",
    ]
    atomic_write_text(OUT / "normalisation_report.md", "\n".join(lines) + "\n")


def write_audit_summary(test_result: dict, pii_result: dict, fixture_results: list[dict]) -> bool:
    totals = test_result["totals"]
    passed = totals["tests"] - totals["failures"] - totals["errors"] - totals["skipped"]
    eval_run = next(r for r in fixture_results if r["name"] == "eval_set")
    gates = [
        ("All Stage 1 tests pass", "100%", f"{passed}/{totals['tests']}", passed == totals["tests"] and test_result["returncode"] == 0),
        ("Line coverage, Stage 1 modules", f"≥ {COVERAGE_GATE:.0f}%", f"{test_result['coverage']:.1f}%", test_result["coverage"] >= COVERAGE_GATE),
        ("Raw-PII hits in eval-set `normalised_tickets.json`", "0", str(eval_run["raw_pii_leaks"]), eval_run["raw_pii_leaks"] == 0),
        ("Raw-PII hits in any fixture run's artifacts / manifest", "0", str(sum(r["raw_pii_leaks"] for r in fixture_results)), all(r["raw_pii_leaks"] == 0 for r in fixture_results)),
        ("Eval PII types match gold", f"{pii_result['eval_total']}/{pii_result['eval_total']}", f"{pii_result['eval_matches']}/{pii_result['eval_total']}", pii_result["eval_matches"] == pii_result["eval_total"]),
        ("Every fixture run ends with the expected exit code", f"{len(fixture_results)}/{len(fixture_results)}", f"{sum(r['exit_code'] == r['expected_exit'] for r in fixture_results)}/{len(fixture_results)}", all(r["exit_code"] == r["expected_exit"] for r in fixture_results)),
    ]
    all_green = all(ok for *_, ok in gates)
    lines = [
        "# Stage 1 — AI audit summary",
        "",
        f"- Generated: {datetime.now(UTC).strftime('%Y-%m-%d %H:%M UTC')} · git: `{git_sha()}` · Python {sys.version.split()[0]}",
        f"- Input hashes (sha256): `tickets.json` {sha256_file(ROOT / 'tickets.json')[:16]}… · `kb_articles.json` {sha256_file(ROOT / 'kb_articles.json')[:16]}… · `data/eval/tickets.json` {sha256_file(EVAL / 'tickets.json')[:16]}…",
        f"- **AI gates: {'ALL GREEN ✅' if all_green else 'NOT GREEN ❌'}** — the stage still needs human review and sign-off in `PLAN.md` before it is closed.",
        "",
        "## Hard gates",
        "",
        "| Gate | Threshold | Value | |",
        "|---|---|---|---|",
    ]
    lines += [f"| {name} | {threshold} | {value} | {'✅' if ok else '❌'} |" for name, threshold, value, ok in gates]
    lines += [
        "",
        "## Evals",
        "",
        "None. Stage 1 has no non-deterministic component: no LLM or network call is made (`llm_calls.jsonl` is empty in every run below), so there is nothing to evaluate with the two eval models.",
        "",
        "## Exit criteria — pipeline runs on root inputs and every fixture",
        "",
        "| Run | tickets | kb | Exit (expected) | Final stage | Accepted | `normalised_tickets.json` | Manifest | Raw-PII leaks |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for r in fixture_results:
        lines.append(
            f"| {r['name']} | `{r['tickets']}` | `{r['kb']}` | {r['exit_code']} ({r['expected_exit']}) | {r['final_stage']} | {r['accepted']} | "
            f"{'written' if r['normalised_written'] else 'not written'} | {'written' if r['manifest_written'] else '**missing**'} | {r['raw_pii_leaks']} |"
        )
    lines += [
        "",
        "Malformed inputs are expected to fail fatally (rule I1, exit 2) while still writing a manifest that records the error.",
        "",
        "## Reports for human review",
        "",
        "- `pytest_summary.md`, `coverage.txt`, `pytest.xml`",
        "- `pii_masking_report.md` — original vs masked text for every eval ticket, all detector fixtures incl. false-positive guards",
        "- `normalisation_report.md` — edge-case before/after, rejected/duplicate records",
        "",
        "## Known issues / notes for the reviewer",
        "",
        "- `KB_INDEXED` is a registered **placeholder** in Stage 1 (marked `placeholder: true` in the manifest stage trail); retrieval stages are built in Stage 2. `--until` beyond `TICKETS_NORMALISED` is refused with exit 2.",
        "- The PII hash salt defaults to a constant (`ticket-triage-pii-v1`) so reruns are byte-identical; set `PII_HASH_SALT` in production.",
        "- Credential detection is pattern-based (keyword + `is`/`:`/…); a password disclosed without a keyword (e.g. \"it's hunter2\") is not detected. Documented as a limitation in SPEC §7.6.",
    ]
    atomic_write_text(OUT / "AUDIT_SUMMARY.md", "\n".join(lines) + "\n")
    return all_green


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    test_result = run_pytest()
    write_pytest_summary(test_result)
    with tempfile.TemporaryDirectory() as workdir:
        fixture_results = run_fixtures(Path(workdir))
    pii_result = write_pii_report(fixture_results)
    write_normalisation_report(fixture_results)
    green = write_audit_summary(test_result, pii_result, fixture_results)
    print(f"Stage 1 audit written to {rel(OUT)} — AI gates {'green' if green else 'NOT green'}")
    return 0 if green else 1


if __name__ == "__main__":
    sys.exit(main())
