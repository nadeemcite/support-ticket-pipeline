"""Drafting eval (PLAN Stage 4): both eval models x two modes x 23 eval tickets, cross-judged.

* ``oracle``: drafts from the gold-preferred classification (isolates drafting quality).
* ``e2e``: drafts from the model's own classification (the real pipeline path; classifications are replayed
  from the Stage 3 cache namespace, so they are free).

Inputs are the frozen deterministic stages from the classification eval. Drafting goes through
``pipeline.draft.draft_ticket``, the same code the pipeline runs. Deterministic checks are scored here;
each model's drafts are then judged by the *other* model (``evals/judge.py``).

Usage: python -m evals.drafting_eval [--workers 6]
"""

import argparse
import json
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from evals.classification_eval import EVAL_MODELS, INPUT_ARTIFACTS, frozen_inputs
from evals.judge import JudgeClient, judge_messages
from pipeline import guards
from pipeline.cache import JsonCache
from pipeline.classify import classify_ticket
from pipeline.draft import draft_ticket
from pipeline.grounding import check_grounding
from pipeline.language import matches_language
from pipeline.llm import LiteLLMProvider, LLMClient
from pipeline.orchestrator import Stage, utc_now
from pipeline.prompts import render_evidence
from pipeline.schemas import Classification, ClassificationMeta
from pipeline.taxonomy import ResolutionAction, Urgency

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "audit" / "stage-4" / "evals"
MODES = ("oracle", "e2e")
MAX_DRAFT_CHARS = 1500
DRAFT_INPUTS = INPUT_ARTIFACTS + ["classification"]


def gold_classification(ticket_id: str, gold: dict, evidence_ids: list[str]) -> Classification:
    g = gold[ticket_id]
    return Classification(
        ticket_id=ticket_id, issue_type=g["issue_type"][0], urgency=g["urgency"][0], resolution_action=g["resolution_action"][0],
        customer_sensitive=g["customer_sensitive"][0], requires_refund_caution=g["requires_refund_caution"][0],
        rationale="gold-preferred", meta=ClassificationMeta(evidence_ids=evidence_ids),
    )


def e2e_classifications(provider: str, model: str, tickets: list, evidence: dict, workers: int) -> dict[str, Classification]:
    """The model's own classifications. Same cache namespace and prompts as the Stage 3 eval, repeat 1."""
    client = LLMClient(
        provider=LiteLLMProvider(provider, model, timeout_s=120), max_tokens=1500, temperature=0.0,
        log_path=OUT / "raw" / model / "classification_replay.jsonl", clock=utc_now, cache=JsonCache(ROOT / ".cache"),
        cache_namespace=f"eval-classification/{model}/r1", current_stage=lambda: Stage.TICKETS_CLASSIFIED,
    )
    client.log_path.parent.mkdir(parents=True, exist_ok=True)
    client.log_path.write_text("")
    with ThreadPoolExecutor(max_workers=workers) as pool:
        results = list(pool.map(lambda t: classify_ticket(client, t, evidence[t.ticket_id], INPUT_ARTIFACTS), tickets))
    return {c.ticket_id: c for c in results}


def draft_all(provider: str, model: str, mode: str, tickets: list, evidence: dict, classifications: dict[str, Classification], workers: int) -> list[dict]:
    log_dir = OUT / "raw" / model
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / f"drafting_{mode}.jsonl"
    log_path.write_text("")
    client = LLMClient(
        provider=LiteLLMProvider(provider, model, timeout_s=180), max_tokens=3000, temperature=0.0, log_path=log_path, clock=utc_now,
        cache=JsonCache(ROOT / ".cache"), cache_namespace=f"eval-drafting/{model}/{mode}", current_stage=lambda: Stage.RESPONSES_DRAFTED,
    )

    def one(ticket):
        draft = draft_ticket(client, ticket, classifications[ticket.ticket_id], evidence[ticket.ticket_id], DRAFT_INPUTS, MAX_DRAFT_CHARS)
        return draft.model_dump(mode="json")

    with ThreadPoolExecutor(max_workers=workers) as pool:
        drafts = list(pool.map(one, tickets))
    calls: dict[str, list[dict]] = {}
    for record in client.records:
        calls.setdefault(record["ticket_id"], []).append(record)
    for draft in drafts:
        attempts = sorted(calls.get(draft["ticket_id"], []), key=lambda r: r["attempt"])
        draft["eval"] = {
            "mode": mode,
            "first_attempt_status": attempts[0]["status"] if attempts else None,
            "latency_ms": sum(r["latency_ms"] for r in attempts),
            "cached": all(r["cached"] for r in attempts),
            "prompt_tokens": sum(r["usage"].get("prompt_tokens", 0) for r in attempts),
            "completion_tokens": sum(r["usage"].get("completion_tokens", 0) for r in attempts),
        }
    return drafts


# --- deterministic scoring ----------------------------------------------------------------------


HEDGES = frozenset({"whether", "if", "unless"})


def asserted_hits(text: str, phrases: list[str]) -> list[str]:
    """``draft_must_not_include`` phrases the draft *asserts*. A plain substring hit inside a negation or hedge in the
    same sentence ("never share your password", "unable to confirm whether we offer X") is advice, not a violation.
    Raw hits are reported separately so a reviewer can see every one."""
    found = []
    for phrase in phrases:
        for match in re.finditer(re.escape(phrase), text, re.IGNORECASE):
            sentence_start = max(text.rfind(mark, 0, match.start()) for mark in (".", "!", "?", "\n")) + 1
            words = [w.lower() for w in re.findall(r"[\w']+", text[sentence_start : match.start()])][-8:]
            if not any(w in guards.NEGATIONS or w in HEDGES for w in words):
                found.append(phrase)
                break
    return found


def deterministic_checks(draft: dict, ticket: Any, classification: Classification, evidence: list, gold: dict) -> dict[str, Any]:
    text = draft["draft_response"]
    retrieved = [a.article_id for a in evidence]
    caution = classification.requires_refund_caution or gold["requires_refund_caution"][0]
    escalate_action = classification.resolution_action == ResolutionAction.NEEDS_HUMAN_ESCALATION
    lowered = text.lower()
    phrases = gold.get("draft_must_not_include", [])
    must_not_raw = [s for s in phrases if s.lower() in lowered]
    must_not = asserted_hits(text, phrases)
    include = gold.get("draft_must_include_any", [])
    cited = {a.article_id: a for a in evidence}
    allowed = escalate_action or classification.urgency == Urgency.CRITICAL or classification.meta.fallback
    flags = [] if draft["meta"]["fallback"] else [
        f.model_dump() for f in check_grounding(ticket.ticket_id, text, [cited[c] for c in draft["citations"] if c in cited], allowed, ticket.language)
    ]
    return {
        "citation_valid": all(c in retrieved for c in draft["citations"]),
        "s1_credential_request": guards.s1_credential_request(text),
        "s2_refund_promise": caution and guards.s2_refund_promise(text),
        "pii_leak": guards.has_pii(text),
        "placeholder_leak": guards.has_placeholder(text),
        "escalation_mentioned": guards.s3_escalation_mention(text) if escalate_action else None,
        "must_not_include_raw_hits": must_not_raw,
        "must_not_include_violations": must_not,
        "must_include_hit": (any(s.lower() in lowered for s in include) if include and ticket.language == "en" else None),
        "language_match": matches_language(text, ticket.language),
        "fallback": draft["meta"]["fallback"],
        "first_attempt_ok": draft["eval"]["first_attempt_status"] == "ok",
        "grounding_flags": flags,
    }


def judge_all(judge_provider: str, judge_model: str, tickets: list, evidence: dict, classifications: dict[str, Classification], drafts: list[dict], workers: int) -> dict[str, dict]:
    log_path = OUT / "raw" / judge_model / "judging.jsonl"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    judge = JudgeClient(LiteLLMProvider(judge_provider, judge_model, timeout_s=180), JsonCache(ROOT / ".cache"), log_path)
    by_ticket = {t.ticket_id: t for t in tickets}

    def one(draft):
        ticket, classification = by_ticket[draft["ticket_id"]], classifications[draft["ticket_id"]]
        cited = [a for a in evidence[ticket.ticket_id] if a.article_id in draft["citations"]]
        view = {"ticket_id": ticket.ticket_id, "customer_tier": ticket.customer_tier, "language": ticket.language, "subject": ticket.subject, "message": ticket.message}
        messages = judge_messages(
            view, render_evidence(cited) if cited else "", classification.requires_refund_caution,
            classification.resolution_action == ResolutionAction.NEEDS_HUMAN_ESCALATION, draft["draft_response"],
        )
        result = judge.judge(ticket.ticket_id, messages)
        return draft["ticket_id"], {
            "judge_model": judge_model, "prompt_hash": result.prompt_hash, "cached": result.cached, "error": result.error,
            "scores": result.score.model_dump() if result.score else None,
        }

    with ThreadPoolExecutor(max_workers=workers) as pool:
        return dict(pool.map(one, drafts))


def run(workers: int) -> dict[str, Any]:
    tickets, evidence, gold = frozen_inputs()
    by_ticket = {t.ticket_id: t for t in tickets}
    providers = dict((m, p) for p, m in EVAL_MODELS)
    output: dict[str, Any] = {"tickets": len(tickets), "models": {}}
    for provider, model in EVAL_MODELS:
        judge_model = next(m for _, m in EVAL_MODELS if m != model)
        entry: dict[str, Any] = {"provider": provider, "judge_model": judge_model, "modes": {}}
        e2e = e2e_classifications(provider, model, tickets, evidence, workers)
        for mode in MODES:
            classifications = (
                {t.ticket_id: gold_classification(t.ticket_id, gold, [a.article_id for a in evidence[t.ticket_id]]) for t in tickets}
                if mode == "oracle" else e2e
            )
            drafts = draft_all(provider, model, mode, tickets, evidence, classifications, workers)
            judged = judge_all(providers[judge_model], judge_model, tickets, evidence, classifications, drafts, workers)
            records = []
            for draft in drafts:
                ticket_id = draft["ticket_id"]
                records.append({
                    **draft,
                    "classification": classifications[ticket_id].model_dump(mode="json"),
                    "checks": deterministic_checks(draft, by_ticket[ticket_id], classifications[ticket_id], evidence[ticket_id], gold[ticket_id]),
                    "judge": judged[ticket_id],
                })
            model_dir = OUT / model
            model_dir.mkdir(parents=True, exist_ok=True)
            with (model_dir / f"drafts_{mode}.jsonl").open("w", encoding="utf-8") as handle:
                for record in records:
                    handle.write(json.dumps(record, ensure_ascii=False) + "\n")
            entry["modes"][mode] = {"drafts": len(records)}
            print(f"{model:22} {mode:7} fallbacks={sum(r['checks']['fallback'] for r in records)} "
                  f"first_ok={sum(r['checks']['first_attempt_ok'] for r in records)}/{len(records)} "
                  f"judge_errors={sum(r['judge']['error'] is not None for r in records)}")
        output["models"][model] = entry
    return output


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--workers", type=int, default=6)
    args = parser.parse_args(argv)
    load_dotenv(ROOT / ".env", override=False)
    OUT.mkdir(parents=True, exist_ok=True)
    result = run(args.workers)
    (OUT / "drafting_eval.json").write_text(json.dumps(result, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
