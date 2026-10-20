"""Gold-preferred classifications + (offline TF-IDF) retrieval must reproduce the gold-preferred escalation for all 23 tickets."""

import pytest

from pipeline.escalate import decide
from pipeline.loader import load_inputs
from pipeline.normalise import normalise_article, normalise_tickets
from pipeline.retrieval import build_retriever, retrieve
from pipeline.schemas import Classification
from tests.conftest import EVAL, eval_gold

pytestmark = pytest.mark.stage4


@pytest.fixture(scope="module")
def setup():
    loaded = load_inputs(EVAL / "tickets.json", EVAL / "kb_articles.json")
    articles = [normalise_article(a) for a in loaded.articles]
    retriever = build_retriever("tfidf", articles, None)
    by_id = {a.article_id: a for a in articles}
    tickets = normalise_tickets(loaded.tickets, 4000, "salt")
    return tickets, retriever, by_id


def test_all_23_match_gold(setup):
    tickets, retriever, by_id = setup
    gold = eval_gold()
    assert len(tickets) == 23
    mismatches = []
    for ticket in tickets:
        g = gold[ticket.ticket_id]
        evidence = [by_id[h.article_id] for h in retrieve(retriever, ticket, 3, 0.05)[0].retrieved_articles]
        classification = Classification(
            ticket_id=ticket.ticket_id, issue_type=g["issue_type"][0], urgency=g["urgency"][0],
            resolution_action=g["resolution_action"][0], customer_sensitive=g["customer_sensitive"][0],
            requires_refund_caution=g["requires_refund_caution"][0], rationale="gold",
        )
        result = decide(classification, evidence)
        if (result.escalate, result.target_queue.value) != (g["escalate"][0], g["target_queue"][0]):
            mismatches.append((ticket.ticket_id, result.escalate, result.target_queue.value))
    assert mismatches == []
