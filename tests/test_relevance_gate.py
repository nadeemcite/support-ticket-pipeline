"""X6: an article is evidence only if it shares a topical word with an English ticket; off-topic tickets get []."""

from dataclasses import dataclass

import pytest

from pipeline.loader import load_inputs
from pipeline.normalise import normalise_article, normalise_tickets
from pipeline.retrieval import Candidate, TfidfRetriever, build_retriever, retrieve, shared_terms
from tests.conftest import EVAL, ROOT

pytestmark = pytest.mark.stage2


def load(tickets, kb):
    loaded = load_inputs(tickets, kb)
    return normalise_tickets(loaded.tickets, 4000, "salt"), [normalise_article(a) for a in loaded.articles]


def ask(text, language="en"):
    tickets, articles = load(ROOT / "tickets.json", ROOT / "kb_articles.json")
    return tickets[0].model_copy(update={"ticket_id": "Z-1", "subject": text, "message": text, "language": language}), articles


@pytest.mark.parametrize(
    "text",
    ["How do I change my shipping address?", "Do you have a good recipe for pizza dough?", "What are your office opening hours?", "Where is my package?"],
)
def test_off_topic_tickets_get_nothing_with_tfidf(text):
    ticket, articles = ask(text)
    result, debug = retrieve(TfidfRetriever(articles), ticket, top_k=3, min_score=0.05)
    assert result.retrieved_articles == [] and "note" in debug


@dataclass
class Noisy:
    """An embedder stand-in that gives every article a decent score, like embedding noise on an unrelated text."""

    method = "embedding"
    articles: list

    def candidates(self, ticket):
        return [Candidate(a.article_id, a.title, 0.40 - i * 0.01, 0.0, [], "") for i, a in enumerate(self.articles)]


def test_gate_removes_high_scoring_articles_that_share_no_word():
    ticket, articles = ask("How do I change my shipping address?")
    result, debug = retrieve(Noisy(articles), ticket, top_k=3, min_score=0.25)
    assert result.retrieved_articles == []
    assert "relevance gate" in debug["note"] and all(c["shared_terms"] == [] for c in debug["candidates"])


def test_gate_keeps_the_article_that_shares_a_word_and_reports_what_it_blocked():
    ticket, articles = ask("I need a refund for my order")
    result, debug = retrieve(Noisy(articles), ticket, top_k=3, min_score=0.25)
    assert [a.article_id for a in result.retrieved_articles] == ["KB-001", "KB-004"]  # "refund" is in both; the gate runs before the top-k cut
    assert debug["gate_blocked"] == ["KB-002", "KB-003"]
    assert next(c for c in debug["candidates"] if c["article_id"] == "KB-004")["shared_terms"] == ["refund"]


def test_gate_does_not_apply_to_other_languages():
    ticket, articles = ask("Mi aplicación se cierra al abrirla y no puedo exportar mis datos", language="es")
    result, _ = retrieve(Noisy(articles), ticket, top_k=3, min_score=0.25)
    assert len(result.retrieved_articles) == 3


def test_generic_words_do_not_count_as_a_shared_term():
    ticket, articles = ask("Thank you for the great service, please help")
    assert all(shared_terms(ticket, a) == [] for a in articles)


def test_sample_tickets_still_get_their_articles():
    """T-1001 -> KB-001 and KB-004, T-1002 -> KB-002, T-1003 -> KB-003 (root data) at the default TF-IDF threshold.
    The embedding equivalent needs the real API: ``python -m evals.retrieval_eval``."""
    from pipeline.config import DEFAULT_MIN_SCORE

    tickets, articles = load(ROOT / "tickets.json", ROOT / "kb_articles.json")
    retriever = build_retriever("tfidf", articles)
    got = {t.ticket_id: [h.article_id for h in retrieve(retriever, t, 3, DEFAULT_MIN_SCORE["tfidf"])[0].retrieved_articles] for t in tickets}
    assert {"KB-001", "KB-004"} <= set(got["T-1001"]) and "KB-002" in got["T-1002"] and "KB-003" in got["T-1003"]


def test_eval_set_no_match_tickets_stay_empty_with_tfidf():
    tickets, articles = load(EVAL / "tickets.json", EVAL / "kb_articles.json")
    retriever = TfidfRetriever(articles)
    for t in tickets:
        if t.ticket_id in ("E-2010", "E-2011", "E-2012"):
            assert retrieve(retriever, t, 3, 0.05)[0].retrieved_articles == []
