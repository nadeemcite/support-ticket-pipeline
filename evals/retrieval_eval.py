"""Retrieval eval (PLAN Stage 2): scores both retrievers against ``gold.relevant_articles``.

Deterministic scoring; the embedding retriever calls the OpenAI embeddings API (masked text only),
cached under ``.cache/``. Also runs a threshold sweep and a no-cache stability check.

Usage: python -m evals.retrieval_eval [--out audit/stage-2]
"""

import argparse
import json
import sys
import tempfile
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from pipeline.cache import JsonCache
from pipeline.config import DEFAULT_MIN_SCORE
from pipeline.loader import load_inputs
from pipeline.normalise import normalise_article, normalise_tickets
from pipeline.orchestrator import utc_now
from pipeline.retrieval import CachedEmbedder, LiteLLMEmbedder, build_retriever, retrieve
from pipeline.schemas import NormalisedTicket

ROOT = Path(__file__).resolve().parent.parent
EVAL = ROOT / "data" / "eval"
EMBEDDING_MODEL = "text-embedding-3-small"
TOP_K = 3
SWEEP = {
    "embedding": [0.0, 0.15, 0.2, 0.22, 0.25, 0.28, 0.3, 0.35, 0.4],
    "tfidf": [0.0, 0.02, 0.05, 0.06, 0.07, 0.08, 0.1, 0.15, 0.2],
}
NON_ENGLISH_IDS = ("E-2004", "E-2005", "E-2006", "E-2017")
NO_MATCH_IDS = ("E-2010", "E-2011", "E-2012")


def load_eval_set() -> tuple[list[NormalisedTicket], list, dict[str, dict]]:
    loaded = load_inputs(EVAL / "tickets.json", EVAL / "kb_articles.json")
    tickets = normalise_tickets(loaded.tickets, 4000, "eval-salt")
    articles = [normalise_article(a) for a in loaded.articles]
    gold = {g["ticket_id"]: g for g in json.loads((EVAL / "gold.json").read_text())["expectations"]}
    return tickets, articles, gold


def make_retriever(method: str, articles: list, cache_dir: Path, read_cache: bool = True):
    if method == "tfidf":
        return build_retriever("tfidf", articles), None
    embedder = CachedEmbedder(LiteLLMEmbedder(EMBEDDING_MODEL), JsonCache(cache_dir, read_enabled=read_cache), clock=utc_now)
    return build_retriever("embedding", articles, embedder), embedder


def rank_all(retriever, tickets: list[NormalisedTicket]) -> dict[str, list[dict[str, Any]]]:
    """Full ranking per ticket (debug lists every candidate), so thresholds can be applied offline."""
    if hasattr(retriever, "prefetch"):
        retriever.prefetch(tickets)
    ranked = {}
    for ticket in tickets:
        _, debug = retrieve(retriever, ticket, top_k=TOP_K, min_score=0.0)
        ranked[ticket.ticket_id] = debug["candidates"]
    return ranked


def kept(candidates: list[dict], min_score: float) -> list[str]:
    return [c["article_id"] for c in candidates[:TOP_K] if c["score"] >= min_score]


def score(ranked: dict[str, list[dict]], gold: dict[str, dict], tickets: list[NormalisedTicket], min_score: float) -> dict[str, Any]:
    language = {t.ticket_id: t.language for t in tickets}
    per_ticket = {}
    for ticket_id, candidates in ranked.items():
        relevant = gold[ticket_id]["relevant_articles"]
        top = kept(candidates, min_score)
        hit = bool(set(top) & set(relevant)) if relevant else None
        rr = next((1 / (i + 1) for i, aid in enumerate(top) if aid in relevant), 0.0) if relevant else None
        per_ticket[ticket_id] = {
            "language": language[ticket_id],
            "relevant": relevant,
            "retrieved": top,
            "scores": [c["score"] for c in candidates[:TOP_K] if c["score"] >= min_score],
            "hit": hit,
            "reciprocal_rank": rr,
            "top1_correct": (top[:1] == relevant[:1] or (bool(top) and top[0] in relevant)) if relevant else None,
            "empty_ok": (not top) if not relevant else None,
        }

    def ratio(ids: list[str], key: str) -> tuple[int, int]:
        values = [per_ticket[i][key] for i in ids if per_ticket[i][key] is not None]
        return sum(bool(v) for v in values), len(values)

    with_relevant = [i for i in ranked if gold[i]["relevant_articles"]]
    english = [i for i in with_relevant if language[i] == "en"]
    non_english = [i for i in with_relevant if language[i] != "en"]
    mrr_values = [per_ticket[i]["reciprocal_rank"] for i in with_relevant]
    return {
        "min_score": min_score,
        "recall_at_3_english": ratio(english, "hit"),
        "recall_at_3_non_english": ratio(non_english, "hit"),
        "recall_at_3_all": ratio(with_relevant, "hit"),
        "top1_accuracy": ratio(with_relevant, "top1_correct"),
        "mrr": round(sum(mrr_values) / len(mrr_values), 4) if mrr_values else 0.0,
        "no_match_precision": ratio(list(NO_MATCH_IDS), "empty_ok"),
        "per_ticket": per_ticket,
    }


def stability(articles: list, tickets: list[NormalisedTicket], baseline: dict[str, list[dict]]) -> dict[str, Any]:
    """Re-embed everything with an empty cache and compare to the cached run."""
    with tempfile.TemporaryDirectory() as tmp:
        retriever, embedder = make_retriever("embedding", articles, Path(tmp), read_cache=False)
        fresh = rank_all(retriever, tickets)
    same_top3 = sum(
        [c["article_id"] for c in baseline[t][:TOP_K]] == [c["article_id"] for c in fresh[t][:TOP_K]] for t in baseline
    )
    max_diff = max(
        (abs(a["score"] - b["score"]) for t in baseline for a, b in zip(baseline[t], fresh[t]) if a["article_id"] == b["article_id"]),
        default=0.0,
    )
    identical = all(baseline[t] == fresh[t] for t in baseline)
    threshold = DEFAULT_MIN_SCORE["embedding"]
    margin = min((abs(c["score"] - threshold) for t in baseline for c in baseline[t][:TOP_K]), default=1.0)
    return {
        "tickets": len(baseline),
        "same_top3": same_top3,
        "max_score_diff": round(max_diff, 6),
        "byte_identical_rankings": identical,
        "closest_top3_score_to_threshold": round(margin, 4),
        "api_calls": embedder.api_calls,
    }


def run(cache_dir: Path) -> dict[str, Any]:
    tickets, articles, gold = load_eval_set()
    output: dict[str, Any] = {"embedding_model": EMBEDDING_MODEL, "top_k": TOP_K, "methods": {}}
    for method in ("embedding", "tfidf"):
        retriever, embedder = make_retriever(method, articles, cache_dir)
        ranked = rank_all(retriever, tickets)
        output["methods"][method] = {
            "default_min_score": DEFAULT_MIN_SCORE[method],
            "at_default": score(ranked, gold, tickets, DEFAULT_MIN_SCORE[method]),
            "sweep": [{k: v for k, v in score(ranked, gold, tickets, m).items() if k != "per_ticket"} for m in SWEEP[method]],
            "ranked": ranked,
        }
        if method == "embedding":
            output["stability"] = stability(articles, tickets, ranked)
            output["embedding_calls_logged"] = len(embedder.log)
    return output


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", default=str(ROOT / "audit" / "stage-2" / "evals"), help="directory for results JSON")
    args = parser.parse_args(argv)
    load_dotenv(ROOT / ".env", override=False)
    result = run(ROOT / ".cache")
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "retrieval_eval.json").write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n")
    for method, data in result["methods"].items():
        d = data["at_default"]
        print(
            f"{method:9} min_score={d['min_score']}: recall@3 en={d['recall_at_3_english']} "
            f"non-en={d['recall_at_3_non_english']} mrr={d['mrr']} no-match={d['no_match_precision']}"
        )
    print("stability:", result["stability"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
