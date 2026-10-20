"""Tokenisation, stemming and sentence splitting used by both retrievers."""

import pytest

from pipeline.retrieval import features, fold, split_sentences, stem, tokens

pytestmark = pytest.mark.stage2


@pytest.mark.parametrize(
    "words, expected",
    [
        (["charge", "charges", "charged", "charging"], "charg"),
        (["invoice", "invoices"], "invoic"),
        (["settle", "settled"], "settl"),
        (["cache", "cached"], "cach"),
    ],
)
def test_stem_conflates_word_forms(words, expected):
    assert {stem(w) for w in words} == {expected}


@pytest.mark.parametrize("word", ["access", "status", "password", "pin", "log"])
def test_stem_leaves_short_or_protected_words(word):
    assert stem(word) == word


def test_fold_strips_accents():
    assert fold("Contraseña Café ÜBER") == "contrasena cafe uber"


def test_tokens_drop_stopwords_placeholders_and_single_chars():
    assert tokens("My card is [CARD_NUMBER_1] and I was charged x") == ["card", "charg"]


def test_features_include_bigrams():
    assert features("pending charges") == ["pend", "charg", "pend charg"]


def test_split_sentences():
    text = "Invoices are under Billing > Documents. Filter by month! Missing? Escalate."
    assert split_sentences(text) == ["Invoices are under Billing > Documents.", "Filter by month!", "Missing?", "Escalate."]
    assert split_sentences("") == []
