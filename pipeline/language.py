"""Stopword-based language heuristic for en/es/fr/de/pt (D2, V09). Deterministic and dependency-free.

It is deliberately coarse: it answers "does this reply look like it is written in the ticket's language?",
not "what language is this?". Text that is too short or matches no language returns ``None``.
"""

import re

from pipeline.retrieval import fold

STOPWORDS: dict[str, frozenset[str]] = {
    "en": frozenset("the and you your for with this that have has are was will can please thank thanks we our not from be to of is it a an if on in by or".split()),
    "es": frozenset("el la los las de que y en un una para con por su sus es se no le lo nos hemos gracias favor si mas como del al esta este ha han".split()),
    "fr": frozenset("le la les des de du et en un une pour avec vous votre vos nous est que qui pas sur par merci ce cette au aux ont avons".split()),
    "de": frozenset("der die das und ist nicht sie ihr ihre mit fur wir haben den dem ein eine zu auf von bei wird bitte danke ich es im".split()),
    "pt": frozenset("o a os as de que e em um uma para com por seu sua nao nos obrigado favor se mais como do da no na foi ao ja sao esta este".split()),
}
_WORD_RE = re.compile(r"[a-z]+")
MIN_WORDS = 4


def detect_language(text: str) -> str | None:
    words = _WORD_RE.findall(fold(text))
    if len(words) < MIN_WORDS:
        return None
    scores = {lang: sum(w in vocab for w in words) for lang, vocab in STOPWORDS.items()}
    best = max(scores.values())
    if best < 2:
        return None
    winners = sorted(lang for lang, score in scores.items() if score == best)
    return winners[0] if len(winners) == 1 else None


def language_code(language: str) -> str:
    return language.lower().split("-")[0]


def is_supported(language: str) -> bool:
    """Whether the drafter, its safety patterns and the language check cover this ticket language."""
    return language_code(language) in STOPWORDS


def matches_language(text: str, language: str) -> bool | None:
    """True/False when decidable, None when the ticket language isn't supported or the text is too short."""
    code = language_code(language)
    if code not in STOPWORDS:
        return None
    detected = detect_language(text)
    return None if detected is None else detected == code
