"""Grounding guard G1-G3 (SPEC §7.5): flags claims in a draft that its *cited* KB text does not support.

Flags never block a draft. They are written to ``grounding_flags.json`` for review and counted as a V12
warning. Only the text of the articles the draft cites counts as support (G-11), and a KB sentence that
contains a negation never supports a commitment (G-05).
"""

import re

from pipeline.guards import s3_escalation_mention, sentences
from pipeline.retrieval import split_sentences, tokens
from pipeline.schemas import GroundingFlag, KBArticle

NUMBER_WORDS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9,
    "ten": 10, "twelve": 12, "fifteen": 15, "twenty": 20, "thirty": 30, "forty": 40, "sixty": 60,
    "forty-eight": 48, "seventy-two": 72,
}
_NUM = r"(?:\d[\d,]*(?:\.\d+)?|" + "|".join(sorted(NUMBER_WORDS, key=len, reverse=True)) + r")"
_UNIT = r"(?:minutes?|mins?|hours?|hrs?|days?|business days?|working days?|weeks?|months?|years?|rows?|%|percent|usd|eur|gbp)"
# number or range ("3-5", "3 to 5") followed by a unit
_G1_RE = re.compile(rf"(?<![\w.])({_NUM}(?:\s*(?:-|–|to)\s*{_NUM})?)\s*({_UNIT})(?!\w)", re.IGNORECASE)
_PATH_WORD = r"[A-Z][A-Za-z]+(?: [A-Z][A-Za-z]+)*"
_G2_PATH_RE = re.compile(rf"{_PATH_WORD}(?:\s*>\s*{_PATH_WORD})+|\b(?:Settings|Billing|Reports|Account|Profile)(?:/\w+)+")
_G2_UNDER_RE = re.compile(rf"\bunder\s+({_PATH_WORD})")
_G3_RE = re.compile(
    r"\b(?:we will|we'll|we are going to|our [a-z ]{1,30}? will|you will|you'll|"
    r"can be|could be|is available|are available|will be available|has been (?:done|processed|completed))\b",
    re.IGNORECASE,
)
# Courtesy phrases and empathy are not claims about the product.
_COURTESY_RE = re.compile(
    r"follow up|get back to you|keep you (?:posted|updated)|be in touch|happy to help|let you know|look into|"
    r"\breview\w*|investigat\w*|contact you|reach out|let us know|assist\b|glad to|happy to|be glad",
    re.IGNORECASE,
)
_EMPATHY_RE = re.compile(r"\bunderstand\b|\bsorry\b|\bapologi[sz]\w*|\bworr(?:y|ying|ied)\b|\bfrustrat\w*|\bconcern\w*", re.IGNORECASE)
_NEGATION_RE = re.compile(r"\b(?:not|never|cannot|can't|unable)\b|n't\b", re.IGNORECASE)
OVERLAP_THRESHOLD = 0.5
_ID_RE = re.compile(r"\bKB-\w+\b")


def _digits(text: str) -> str:
    """Normalise number words, thousands separators and dashes so '3–5', 'three' and '3,000' compare equal."""
    text = text.lower().replace("–", "-")
    text = re.sub(r"(?<=\d),(?=\d{3}\b)", "", text)
    for word in sorted(NUMBER_WORDS, key=len, reverse=True):
        text = re.sub(rf"\b{word}\b", str(NUMBER_WORDS[word]), text)
    return re.sub(r"\s*(?:-|to)\s*", "-", re.sub(r"(?<=\d)\s*(?:-|to)\s*(?=\d)", "-", text))


_UNIT_FAMILIES = {
    "time": r"(?:minutes?|mins?|hours?|hrs?|days?|business days?|working days?|weeks?|months?|years?)",
    "rows": r"rows?",
    "percent": r"(?:%|percent)",
    "money": r"(?:usd|eur|gbp)",
}


def _family(unit: str) -> str:
    unit = unit.lower()
    return next((name for name, pattern in _UNIT_FAMILIES.items() if re.fullmatch(pattern, unit)), "time")


def _content_has_number(number: str, unit: str, content: str) -> bool:
    """The same number (or range) followed by a unit of the same kind appears in the cited text."""
    wanted = _digits(number)
    family = _UNIT_FAMILIES[_family(unit)]
    # a single number is also supported when it is an end of a range ("5 business days" vs "3-5 business days")
    ends = r"" if "-" in wanted else r"(?:\d+(?:\.\d+)?-)?"
    tail = r"" if "-" in wanted else r"(?:-\d+(?:\.\d+)?)?"
    return re.search(rf"(?<![\d.]){ends}{re.escape(wanted)}{tail}\s*{family}(?!\w)", _digits(content)) is not None


def _best_overlap(sentence: str, cited: list[KBArticle]) -> float:
    """Fraction of the sentence's content words found in the best-matching non-negated cited sentence."""
    own = set(tokens(_G3_RE.sub(" ", sentence)))
    if not own:
        return 1.0
    best = 0.0
    for article in cited:
        for kb_sentence in split_sentences(article.content):
            if _NEGATION_RE.search(kb_sentence):
                continue
            best = max(best, len(own & set(tokens(kb_sentence))) / len(own))
    return round(best, 2)


def check_grounding(
    ticket_id: str, draft: str, cited: list[KBArticle], escalation_allowed: bool = False, language: str = "en"
) -> list[GroundingFlag]:
    cited_ids = [a.article_id for a in cited]
    content = "\n".join(a.content for a in cited)
    flat_content = re.sub(r"\s+", " ", content).lower()
    flags: list[GroundingFlag] = []
    for sentence in sentences(_ID_RE.sub("", draft)):
        overlap = _best_overlap(sentence, cited)

        def flag(check: str, claim_type: str, unsupported: list[str]) -> None:
            flags.append(GroundingFlag(
                ticket_id=ticket_id, check=check, claim_type=claim_type, sentence=sentence,
                unsupported_tokens=unsupported, cited_articles_checked=cited_ids, overlap=overlap,
            ))

        numbers = [f"{m.group(1)} {m.group(2)}" for m in _G1_RE.finditer(sentence) if not _content_has_number(m.group(1), m.group(2), content)]
        if numbers:
            flag("G1", "number_or_duration", numbers)

        paths = [m.group(0) for m in _G2_PATH_RE.finditer(sentence)]
        heads = {re.split(r"\s*[>/]", p)[0].strip() for p in paths}
        paths += [m.group(0) for m in _G2_UNDER_RE.finditer(sentence) if m.group(1) not in heads]
        # translated menu labels can't be matched exactly: outside English, the final label of a KB path is enough
        kb_labels = {re.split(r"\s*>\s*", m.group(0))[-1].lower() for m in _G2_PATH_RE.finditer(content)}
        missing = [
            p for p in paths
            if re.sub(r"\s*>\s*", " > ", p).lower() not in re.sub(r"\s*>\s*", " > ", flat_content)
            and not (language.split("-")[0] != "en" and re.split(r"\s*>\s*", p)[-1].lower() in kb_labels)
        ]
        if missing:
            flag("G2", "ui_path", missing)

        if _G3_RE.search(sentence) and not _COURTESY_RE.search(sentence) and not _EMPATHY_RE.search(sentence):
            # an escalation statement is supported when E1-E3 allow it, or when a cited article itself prescribes escalation
            allowed = s3_escalation_mention(sentence) and (escalation_allowed or "escalat" in flat_content)
            if overlap < OVERLAP_THRESHOLD and not allowed:
                flag("G3", "commitment", [m.group(0) for m in _G3_RE.finditer(sentence)])
    return flags
