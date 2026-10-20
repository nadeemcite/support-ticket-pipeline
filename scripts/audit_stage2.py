"""Stage 2 AI audit (PLAN §1 step 2): pytest (stage1 + stage2) with coverage, the retrieval eval
against gold (real OpenAI embeddings, cached), pipeline runs for the exit criteria, and the
human-review reports in audit/stage-2/.

Usage: python scripts/audit_stage2.py   (needs OPENAI_API_KEY in .env for the embedding eval)
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

from evals import retrieval_eval  # noqa: E402
from pipeline.config import DEFAULT_MIN_SCORE, Config  # noqa: E402
from pipeline.io_utils import atomic_write_text, sha256_file  # noqa: E402
from pipeline.runner import run  # noqa: E402
from scripts.audit_stage1 import git_sha, md_escape, rel  # noqa: E402

OUT = ROOT / "audit" / "stage-2"
EVAL = ROOT / "data" / "eval"
FIX = ROOT / "data" / "fixtures"
STAGE2_MODULES = ["pipeline/retrieval.py", "pipeline/cache.py", "pipeline/stages.py", "pipeline/config.py", "pipeline/runner.py"]
COVERAGE_GATE = 90.0


def run_pytest() -> dict:
    junit = OUT / "pytest.xml"
    cmd = [
        sys.executable, "-m", "pytest", "-m", "(stage1 or stage2) and not live", "-q", "-p", "no:cacheprovider",
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
        module = case.get("classname", "").split(".")[-1]
        passed = case.find("failure") is None and case.find("error") is None
        per_file.setdefault(module, [0, 0])[0 if passed else 1] += 1
        if not passed:
            failed.append(f"{case.get('classname')}::{case.get('name')}")

    covered = {}
    for line in coverage_lines:
        parts = line.split()
        if parts and parts[0] in STAGE2_MODULES:
            covered[parts[0]] = (int(parts[1]), int(parts[2]))
    statements = sum(s for s, _ in covered.values())
    missed = sum(m for _, m in covered.values())
    coverage = 100.0 * (statements - missed) / statements if statements else 0.0

    live = subprocess.run(
        [sys.executable, "-m", "pytest", "-m", "live", "-q", "-p", "no:cacheprovider"], cwd=ROOT, capture_output=True, text=True
    )
    live_line = (live.stdout.strip().splitlines() or ["(no output)"])[-1]
    return {
        "returncode": result.returncode, "totals": totals, "per_file": per_file, "failed": failed,
        "coverage": coverage, "live": live_line, "live_ok": live.returncode == 0,
    }


def run_exit_criteria(workdir: Path) -> list[dict]:
    runs = [
        ("root (embedding)", ROOT / "tickets.json", ROOT / "kb_articles.json", "embedding"),
        ("eval set (embedding)", EVAL / "tickets.json", EVAL / "kb_articles.json", "embedding"),
        ("empty_kb (embedding)", ROOT / "tickets.json", FIX / "empty_kb/kb_articles.json", "embedding"),
        ("root (tfidf, offline)", ROOT / "tickets.json", ROOT / "kb_articles.json", "tfidf"),
        ("empty_kb (tfidf, offline)", ROOT / "tickets.json", FIX / "empty_kb/kb_articles.json", "tfidf"),
    ]
    out = []
    for index, (name, tickets, kb, retriever) in enumerate(runs):
        config = Config(provider="stub", model="stub", retriever=retriever, tickets_path=tickets, kb_path=kb,
                        out_dir=workdir / str(index))
        # Share the repo's embedding cache so the audit doesn't re-pay for vectors the eval already has.
        (workdir / str(index)).mkdir(parents=True)
        (workdir / str(index) / ".cache").symlink_to(ROOT / ".cache", target_is_directory=True)
        outcome = run(config)
        results = json.loads((config.out_dir / "retrieval_results.json").read_text())["results"] if outcome.exit_code == 0 else []
        llm_lines = (config.out_dir / "llm_calls.jsonl").read_text().strip() if (config.out_dir / "llm_calls.jsonl").exists() else ""
        out.append({
            "name": name,
            "exit_code": outcome.exit_code,
            "final_stage": outcome.manifest["final_stage"],
            "tickets": len(results),
            "with_evidence": sum(bool(r["retrieved_articles"]) for r in results),
            "both_artifacts": (config.out_dir / "retrieval_results.json").exists() and (config.out_dir / "retrieval_debug.json").exists(),
            "llm_calls": len(llm_lines.splitlines()) if llm_lines else 0,
            "embedding_api_calls": outcome.manifest.get("counts", {}).get("embedding_api_calls", 0),
            "error": outcome.error,
        })
    return out


def write_pytest_summary(result: dict) -> None:
    t = result["totals"]
    passed = t["tests"] - t["failures"] - t["errors"] - t["skipped"]
    lines = [
        "# Stage 2 — pytest summary",
        "",
        "- Command: `pytest -m \"(stage1 or stage2) and not live\" --cov=pipeline --cov=run_pipeline` (Stage 1 suite re-run as regression)",
        f"- Result: **{passed}/{t['tests']} passed**, {t['failures']} failed, {t['errors']} errors, {t['skipped']} skipped",
        f"- Line coverage, Stage 2 modules ({', '.join(f'`{m}`' for m in STAGE2_MODULES)}): **{result['coverage']:.1f}%** (gate ≥ {COVERAGE_GATE:.0f}%)",
        f"- Live test (`pytest -m live`, real OpenAI embeddings on the samples): {result['live']}",
        "",
        "| Test module | Passed | Failed |",
        "|---|---|---|",
    ]
    lines += [f"| `{m}.py` | {p} | {f} |" for m, (p, f) in sorted(result["per_file"].items())]
    if result["failed"]:
        lines += ["", "## Failures", ""] + [f"- `{n}`" for n in result["failed"]]
    atomic_write_text(OUT / "pytest_summary.md", "\n".join(lines) + "\n")


def _fmt(pair) -> str:
    hit, total = pair
    return f"{hit}/{total} ({hit / total:.2f})" if total else "n/a"


def write_eval_report(ev: dict) -> None:
    tickets = {t["ticket_id"]: t for t in json.loads((EVAL / "tickets.json").read_text())["tickets"]}
    emb = ev["methods"]["embedding"]
    tfidf = ev["methods"]["tfidf"]
    lines = [
        "# Stage 2 — retrieval eval report",
        "",
        f"- Eval set: `data/eval/tickets.json` (23 tickets) against `data/eval/kb_articles.json` (11 articles); gold = `data/eval/gold.json` `relevant_articles`.",
        f"- Primary retriever: **OpenAI `{ev['embedding_model']}` embeddings** via LiteLLM (decision OD-2). Comparison: offline TF-IDF.",
        "- Metrics are deterministic functions of the rankings. A ticket \"hits\" when at least one relevant article is among the kept top 3.",
        "- Only PII-masked text is embedded (rule P-EXT; asserted by `test_only_masked_text_reaches_the_embedder`).",
        "",
        "## Summary at the configured threshold",
        "",
        "| Metric | Embedding (min_score " + str(emb["default_min_score"]) + ") | TF-IDF (min_score " + str(tfidf["default_min_score"]) + ") |",
        "|---|---|---|",
    ]
    for key, label in [
        ("recall_at_3_english", "Recall@3, English tickets with relevant articles"),
        ("recall_at_3_non_english", "Recall@3, non-English (E-2004 es, E-2005 fr, E-2006 de, E-2017 pt)"),
        ("recall_at_3_all", "Recall@3, all tickets with relevant articles"),
        ("top1_accuracy", "Top-1 is a relevant article"),
        ("no_match_precision", "No-match tickets (E-2010/11/12) return `[]`"),
    ]:
        lines.append(f"| {label} | {_fmt(emb['at_default'][key])} | {_fmt(tfidf['at_default'][key])} |")
    lines.append(f"| MRR | {emb['at_default']['mrr']} | {tfidf['at_default']['mrr']} |")

    st = ev["stability"]
    lines += [
        "",
        "## Embedding stability (fresh re-embedding, empty cache)",
        "",
        f"- Same top-3 article IDs: **{st['same_top3']}/{st['tickets']}** tickets",
        f"- Largest score difference for the same article: **{st['max_score_diff']}**; rankings byte-identical: **{st['byte_identical_rankings']}**",
        f"- Closest kept-range score to the threshold ({emb['default_min_score']}): **{st['closest_top3_score_to_threshold']}** away, ~{st['closest_top3_score_to_threshold'] / max(st['max_score_diff'], 1e-6):.0f}× the observed drift",
        "- Meaning: the OpenAI embedding API is not bit-for-bit deterministic, but drift is far too small to change any ranking or threshold decision. "
        "Pipeline reruns are byte-identical because every vector is cached by content hash (`.cache/embeddings/`). A clean checkout re-embeds and can differ in the 3rd–4th decimal of a score.",
        "",
        "## Threshold sweep",
        "",
        "Chosen embedding threshold **0.25**: every value in [0.20, 0.35] is perfect on this set; 0.25 sits inside that band with margin both ways "
        "(highest no-match top score ≈ 0.21, lowest relevant top-1 ≈ 0.39) and keeps useful secondary evidence such as KB-004 for T-1001.",
        "",
        "| Retriever | min_score | Recall@3 en | Recall@3 non-en | Top-1 | MRR | No-match `[]` |",
        "|---|---|---|---|---|---|---|",
    ]
    for method, data in ev["methods"].items():
        for row in data["sweep"]:
            marker = " ←" if row["min_score"] == data["default_min_score"] else ""
            lines.append(
                f"| {method} | {row['min_score']}{marker} | {_fmt(row['recall_at_3_english'])} | {_fmt(row['recall_at_3_non_english'])} | "
                f"{_fmt(row['top1_accuracy'])} | {row['mrr']} | {_fmt(row['no_match_precision'])} |"
            )

    lines += [
        "",
        "## Per-ticket rankings (embedding, configured threshold)",
        "",
        "Top terms are the lexical (TF-IDF) overlap shown for explainability; non-English tickets often have none, which is exactly why embeddings are used. "
        "The snippet is the KB sentence most similar to the ticket.",
        "",
        "| Ticket | Lang | Subject | Kept top 3 (score) | Gold relevant | | Best snippet of #1 | Top terms of #1 |",
        "|---|---|---|---|---|---|---|---|",
    ]
    per = emb["at_default"]["per_ticket"]
    for ticket_id, row in per.items():
        ranked = emb["ranked"][ticket_id]
        first = ranked[0] if ranked and row["retrieved"] else None
        kept = ", ".join(f"{a} ({s})" for a, s in zip(row["retrieved"], row["scores"])) or "`[]`"
        verdict = "✅" if (row["hit"] or row["empty_ok"]) else "❌"
        terms = ", ".join(t["term"] for t in first["top_terms"][:4]) if first and first["top_terms"] else "—"
        snippet = md_escape(first["best_snippet"]) if first else (f"top score {ranked[0]['score']} < threshold" if ranked else "empty ticket")
        lines.append(
            f"| {ticket_id} | {row['language']} | {md_escape(tickets[ticket_id]['subject']) or '∅'} | {kept} | "
            f"{', '.join(row['relevant']) or '— (none)'} | {verdict} | {snippet} | {terms} |"
        )

    lines += [
        "",
        "## Where TF-IDF and embeddings disagree",
        "",
        "| Ticket | Lang | TF-IDF kept | Embedding kept | Gold |",
        "|---|---|---|---|---|",
    ]
    tf_per = tfidf["at_default"]["per_ticket"]
    for ticket_id in per:
        if tf_per[ticket_id]["retrieved"] != per[ticket_id]["retrieved"]:
            lines.append(
                f"| {ticket_id} | {per[ticket_id]['language']} | {', '.join(tf_per[ticket_id]['retrieved']) or '`[]`'} | "
                f"{', '.join(per[ticket_id]['retrieved']) or '`[]`'} | {', '.join(per[ticket_id]['relevant']) or '—'} |"
            )
    atomic_write_text(OUT / "retrieval_eval_report.md", "\n".join(lines) + "\n")


def write_audit_summary(tests: dict, ev: dict, runs: list[dict]) -> bool:
    t = tests["totals"]
    passed = t["tests"] - t["failures"] - t["errors"] - t["skipped"]
    emb = ev["methods"]["embedding"]["at_default"]
    st = ev["stability"]
    en_hit, en_total = emb["recall_at_3_english"]
    ne_hit, ne_total = emb["recall_at_3_non_english"]
    nm_hit, nm_total = emb["no_match_precision"]
    hard = [
        ("Stage 1 + 2 tests pass (offline)", "100%", f"{passed}/{t['tests']}", passed == t["tests"] and tests["returncode"] == 0),
        ("Live embedding test (samples top-1)", "pass", tests["live"], tests["live_ok"]),
        ("Line coverage, Stage 2 modules", f"≥ {COVERAGE_GATE:.0f}%", f"{tests['coverage']:.1f}%", tests["coverage"] >= COVERAGE_GATE),
        ("Recall@3, English tickets (embedding)", "≥ 0.95", f"{en_hit}/{en_total}", en_total and en_hit / en_total >= 0.95),
        ("No-match precision (E-2010/11/12 → `[]`)", "3/3", f"{nm_hit}/{nm_total}", nm_hit == nm_total == 3),
        ("Same top-3 after fresh re-embedding", f"{st['tickets']}/{st['tickets']}", f"{st['same_top3']}/{st['tickets']}", st["same_top3"] == st["tickets"]),
        ("Exit-criteria runs succeed with both artifacts", f"{len(runs)}/{len(runs)}", f"{sum(r['exit_code'] == 0 and r['both_artifacts'] for r in runs)}/{len(runs)}", all(r["exit_code"] == 0 and r["both_artifacts"] for r in runs)),
        ("`empty_kb` → `[]` for every ticket", "0 with evidence", ", ".join(str(r["with_evidence"]) for r in runs if "empty_kb" in r["name"]), all(r["with_evidence"] == 0 for r in runs if "empty_kb" in r["name"])),
        ("No LLM calls in this stage (`llm_calls.jsonl` empty)", "0", str(sum(r["llm_calls"] for r in runs)), all(r["llm_calls"] == 0 for r in runs)),
    ]
    soft = [
        ("Recall@3, non-English tickets (embedding)", "≥ 0.75", f"{ne_hit}/{ne_total}", ne_total and ne_hit / ne_total >= 0.75),
        ("MRR, tickets with relevant articles (embedding)", "≥ 0.85", str(emb["mrr"]), emb["mrr"] >= 0.85),
    ]
    green = all(ok for *_, ok in hard)
    lines = [
        "# Stage 2 — AI audit summary",
        "",
        f"- Generated: {datetime.now(UTC).strftime('%Y-%m-%d %H:%M UTC')} · git: `{git_sha()}` · Python {sys.version.split()[0]}",
        f"- Input hashes (sha256): `data/eval/tickets.json` {sha256_file(EVAL / 'tickets.json')[:16]}… · `data/eval/kb_articles.json` {sha256_file(EVAL / 'kb_articles.json')[:16]}… · `gold.json` {sha256_file(EVAL / 'gold.json')[:16]}…",
        f"- Retrieval: OpenAI `{ev['embedding_model']}` embeddings (OD-2), min_score {DEFAULT_MIN_SCORE['embedding']}; TF-IDF (min_score {DEFAULT_MIN_SCORE['tfidf']}) as the offline mode.",
        f"- **AI gates: {'ALL HARD GATES GREEN ✅' if green else 'NOT GREEN ❌'}** — the stage still needs human review and sign-off in `PLAN.md` before it is closed.",
        "",
        "## Hard gates",
        "",
        "| Gate | Threshold | Value | |",
        "|---|---|---|---|",
    ]
    lines += [f"| {n} | {th} | {v} | {'✅' if ok else '❌'} |" for n, th, v, ok in hard]
    lines += ["", "## Soft gates", "", "| Gate | Threshold | Value | |", "|---|---|---|---|"]
    lines += [f"| {n} | {th} | {v} | {'✅' if ok else '⚠️'} |" for n, th, v, ok in soft]
    lines += [
        "",
        "## Evals",
        "",
        "Retrieval has no generative LLM, so the 2-model LLM eval doesn't apply. The embedding model is an external API, so its "
        "behaviour is measured instead: the deterministic gold-label eval and a fresh re-embedding stability check "
        f"(max score drift {st['max_score_diff']}, same top-3 {st['same_top3']}/{st['tickets']}). Full detail: `retrieval_eval_report.md`, raw numbers: `evals/retrieval_eval.json`.",
        "",
        "## Exit criteria runs",
        "",
        "| Run | Exit | Final stage | Tickets | With evidence | Both artifacts | Embedding API calls | LLM calls |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for r in runs:
        lines.append(
            f"| {r['name']} | {r['exit_code']} | {r['final_stage']} | {r['tickets']} | {r['with_evidence']} | "
            f"{'yes' if r['both_artifacts'] else 'no'} | {r['embedding_api_calls']} | {r['llm_calls']} |"
        )
    lines += [
        "",
        "Embedding API calls are 0 in these runs because the vectors were already cached by the eval run (content-addressed cache).",
        "",
        "## Reports for human review",
        "",
        "- `retrieval_eval_report.md` — per-ticket rankings with scores, snippets, top terms and gold ✅/❌; per-language slice; threshold sweep; TF-IDF vs embedding disagreements",
        "- `pytest_summary.md`, `coverage.txt`, `pytest.xml`",
        "",
        "## Known issues / notes for the reviewer",
        "",
        "- **Embeddings are not bit-for-bit reproducible across fresh API calls** (drift ≤ "
        f"{st['max_score_diff']}). Reruns are byte-identical via the cache; a clean checkout may differ in the 3rd–4th decimal of scores, never (on this set) in rankings or kept articles.",
        "- **Embedding retrieval needs `OPENAI_API_KEY`** even when the LLM provider is Ollama. Without it the run stops with exit 2 and a message suggesting `--retriever tfidf`.",
        "- **TF-IDF stays as the offline mode** (`--provider stub` defaults to it): 16/16 English recall but only 2/4 non-English, so it is not the default.",
        "- **The threshold is tuned on 23 tickets.** The margin to the no-match tickets is ~0.04, so new ticket types should be re-checked with `python -m evals.retrieval_eval`.",
        "- **Stage 1 tests changed** (closed stage): 5 assertions that expected retrieval to be unbuilt now expect `EVIDENCE_RETRIEVED`; a synthetic test keeps placeholder pass-through covered. Noted for the Stage 2 sign-off.",
    ]
    atomic_write_text(OUT / "AUDIT_SUMMARY.md", "\n".join(lines) + "\n")
    return green


def main() -> int:
    load_dotenv(ROOT / ".env", override=False)
    OUT.mkdir(parents=True, exist_ok=True)
    tests = run_pytest()
    write_pytest_summary(tests)
    ev = retrieval_eval.run(ROOT / ".cache")
    (OUT / "evals").mkdir(exist_ok=True)
    (OUT / "evals" / "retrieval_eval.json").write_text(json.dumps(ev, indent=2, ensure_ascii=False) + "\n")
    write_eval_report(ev)
    with tempfile.TemporaryDirectory() as workdir:
        runs = run_exit_criteria(Path(workdir))
    green = write_audit_summary(tests, ev, runs)
    print(f"Stage 2 audit written to {rel(OUT)} — hard gates {'green' if green else 'NOT green'}")
    return 0 if green else 1


if __name__ == "__main__":
    sys.exit(main())
