"""Judge calibration (PLAN §4): 8 blind drafts for the human to score, then judge–human agreement.

``python -m evals.calibration build``  writes audit/stage-4/calibration_sheet.md (blind: no model, mode or judge
scores) and evals/raw key ``audit/stage-4/evals/calibration_key.json``. The human fills the 1–5 scores in the sheet.
``python -m evals.calibration score``   reads the filled sheet and reports % of scores within ±1 of the judge.
Do not open the key before scoring.
"""

import hashlib
import json
import re
import sys

from evals.classification_eval import EVAL_MODELS
from evals.drafting_eval import MODES, OUT
from evals.judge import CRITERIA
from evals.report_drafting import HUMAN_AGREEMENT_GATE, load
from evals.retrieval_eval import load_eval_set
from pipeline.io_utils import atomic_write_json, atomic_write_text
from pipeline.prompts import render_evidence

SHEET = OUT.parent / "calibration_sheet.md"
KEY = OUT / "calibration_key.json"
STRATA = ("non_english", "pii", "safety", "refund_caution", "escalation", "prompt_injection", "how_to", "billing")
SEED = "stage4-calibration"


def _rank(*parts: str) -> str:
    return hashlib.sha256((SEED + "|" + "|".join(parts)).encode()).hexdigest()


def select(data: dict, tags: dict[str, list[str]], size: int = 8) -> list[tuple[str, str, str]]:
    """Deterministic, stratified pick of (model, mode, ticket_id); one per stratum, no ticket twice."""
    pool = sorted(((m, mode, r["ticket_id"]) for m in data for mode in MODES for r in data[m][mode]), key=lambda x: _rank(*x))
    chosen: list[tuple[str, str, str]] = []
    for stratum in STRATA:
        pick = next((c for c in pool if stratum in tags[c[2]] and c[2] not in {x[2] for x in chosen}), None)
        if pick and len(chosen) < size:
            chosen.append(pick)
    for candidate in pool:
        if len(chosen) >= size:
            break
        if candidate[2] not in {x[2] for x in chosen}:
            chosen.append(candidate)
    return sorted(chosen, key=lambda x: _rank("order", *x))


def build() -> None:
    data = load()
    tickets, articles, gold = load_eval_set()
    by_ticket = {t.ticket_id: t for t in tickets}
    by_article = {a.article_id: a for a in articles}
    tags = {t: g.get("tags", []) for t, g in gold.items()}
    key, lines = {}, [
        "# Stage 4 — judge calibration sheet (blind)", "",
        "Score each draft 1–5 on the five criteria by replacing `_` with a digit. You do not see the model, the mode or the judge's scores.",
        "Rubric: **faithfulness** (claims supported by the cited KB), **helpfulness** (answers the ask, clear next step), **tone**, "
        "**policy** (no secrets requested, no refund promise when caution applies, escalation mentioned when required), **language** (ticket's language, fluent).", "",
        "Do not open `evals/calibration_key.json` before scoring. When done run `python -m evals.calibration score`.", "",
    ]
    for index, (model, mode, ticket_id) in enumerate(select(data, tags), start=1):
        record = next(r for r in data[model][mode] if r["ticket_id"] == ticket_id)
        ticket = by_ticket[ticket_id]
        cited = [by_article[c] for c in record["citations"] if c in by_article]
        cls = record["classification"]
        key[f"C{index}"] = {"model": model, "mode": mode, "ticket_id": ticket_id, "judge": record["judge"]["scores"]}
        lines += [f"### C{index}", "", f"**Ticket** (language `{ticket.language}`, tier `{ticket.customer_tier}`; personal data masked)", "",
                  f"> **{ticket.subject}**", "> " + ticket.message.replace("\n", "\n> "), "",
                  f"**Policy context:** refund caution = {cls['requires_refund_caution']}; escalation required = {cls['resolution_action'] == 'needs_human_escalation'}", "",
                  "**Cited KB text**", "", "```", render_evidence(cited) if cited else "(the reply cites no articles)", "```", "",
                  "**Reply**", "", "> " + record["draft_response"].replace("\n", "\n> "), "", "**Your scores**", "", "```"]
        lines += [f"{criterion}: _" for criterion in CRITERIA]
        lines += ["```", ""]
    atomic_write_text(SHEET, "\n".join(lines) + "\n")
    atomic_write_json(KEY, key)
    print(f"wrote {SHEET} and {KEY}")


def parse_sheet(text: str) -> dict[str, dict[str, int]]:
    scores: dict[str, dict[str, int]] = {}
    current = None
    for line in text.splitlines():
        if heading := re.match(r"^### (C\d+)\s*$", line):
            current = heading.group(1)
            scores[current] = {}
        elif current and (m := re.match(rf"^({'|'.join(CRITERIA)}):\s*([1-5])\s*$", line)):
            scores[current][m.group(1)] = int(m.group(2))
    return scores


def agreement(human: dict[str, dict[str, int]], key: dict) -> dict:
    pairs = [(human[c][k], key[c]["judge"][k]) for c in key if c in human for k in CRITERIA if k in human[c] and key[c]["judge"]]
    within = sum(abs(h - j) <= 1 for h, j in pairs)
    return {"pairs": len(pairs), "within_1": within, "agreement": round(within / len(pairs), 3) if pairs else None,
            "complete": len(pairs) == len(key) * len(CRITERIA)}


def score() -> int:
    result = agreement(parse_sheet(SHEET.read_text()), json.loads(KEY.read_text()))
    if not result["complete"]:
        print(f"sheet incomplete: {result['pairs']}/{8 * len(CRITERIA)} scores filled")
        return 1
    authoritative = result["agreement"] >= HUMAN_AGREEMENT_GATE
    result["judge_authority"] = "authoritative" if authoritative else "advisory (agreement below 75%)"
    atomic_write_json(OUT / "calibration_result.json", result)
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    command = sys.argv[1] if len(sys.argv) > 1 else ""
    if command == "build":
        build()
    elif command == "score":
        sys.exit(score())
    else:
        print(__doc__)
        sys.exit(2)
