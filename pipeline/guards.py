"""Safety patterns S1-S3 (SPEC §7.4), shared by the drafter and the validator, plus PII/placeholder checks.

All checks are deterministic regex over single sentences. Negation is looked up in a short window
around the trigger, not across the whole sentence, so "we will not be able to help unless you send
your password" is still caught. Lexicons cover en with es/fr/de/pt equivalents.
"""

import re

from pipeline import pii
from pipeline.retrieval import split_sentences

_WORD_RE = re.compile(r"[\w']+", re.UNICODE)
NEGATIONS = frozenset(
    """not never no cannot can't cant won't don't dont doesn't didn't isn't aren't wouldn't shouldn't
    nunca jamais pas niemals nie nicht kein keine nenhum nem não nao sin evite evitar ne unable""".split()
)

_SECRET_NOUN = (
    r"(?:password|passcode|pin|otp|(?:(?:log[- ]?in|sign[- ]?in|account|access) (?:credentials?|details|info(?:rmation)?))|credentials?|one[- ]time (?:code|password|passcode)s?|2fa(?: code)?s?|verification codes?|"
    r"security codes?|recovery codes?|cvv|cvc|(?:full )?card number|"
    r"contrase[ñn]a|clave|c[oó]digo(?: de verificaci[oó]n| de seguridad)?|n[uú]mero de tarjeta|"
    r"mot de passe|code de v[eé]rification|code secret|num[eé]ro de carte|"
    r"passwort|kennwort|einmalcode|best[aä]tigungscode|kartennummer|"
    r"senha|c[oó]digo de verifica[cç][aã]o|n[uú]mero do cart[aã]o)"
)
_REQUEST_VERB = (
    r"(?:send|share|provide|give|tell|confirm|enter|type|submit|reply with|ask(?:ing)? (?:you )?for|let us know|"
    r"what(?:'s|\s+is|\s+are)|"
    r"env[ií](?:e|en|a|ar|enos|enme)|comparta|compartan|compartir|proporcione|proporcionen|proporciona|"
    r"indique|indiquen|facilite|faciliten|mande|manden|"
    r"communiquer|communiquez|envoyer|envoyez|partager|partagez|fournir|fournissez|donner|donnez|indiquer|indiquez|"
    r"transmettre|transmettez|"
    r"senden|schicken|schicke|mitteilen|nennen|nennt|geben|angeben|"
    r"compartilhe|compartilhar|informe|informar|forne[cç]a|fornecer|envie|enviar)"
)
_S1_VERB_RE = re.compile(rf"\b{_REQUEST_VERB}\b", re.IGNORECASE)
_S1_NOUN_RE = re.compile(rf"\b{_SECRET_NOUN}\b", re.IGNORECASE)
S1_MAX_GAP = 80

# D10 advice: a negated sharing verb + a credential noun ("never share your password").
_ADVICE_VERB_RE = re.compile(
    r"\b(?:share|send|give|disclose|reveal|tell|provide|compartir\w*|comparta\w*|envi\w*|partag\w*|communiqu\w*|"
    r"weitergeb\w*|teilen|nennen|compartilh\w*)\b",
    re.IGNORECASE,
)

_REFUND = r"(?:refund\w*|reembols\w*|rembours\w*|r[uü]ckerstatt\w*|erstatt\w*)"
_ISSUE_VERB = r"(?:issued|processed|reversed|approved|credited|sent|completed)"
_DONE_VERB = r"(?:issued|processed|reversed|approved|credited)"  # active voice: "we have issued the refund"
_S2_PATTERNS = [
    re.compile(rf"\b(?:we will|we'll|we are going to|you will|you'll|we shall)\s+(?:\w+\s+){{0,4}}?{_REFUND}\b", re.IGNORECASE),
    re.compile(rf"\b{_REFUND}\s+(?:has been|have been|was|were|is being|are being|will be|is going to be)\s+{_ISSUE_VERB}\b", re.IGNORECASE),
    re.compile(rf"\b{_DONE_VERB}\s+(?:\w+\s+){{0,3}}?{_REFUND}\b", re.IGNORECASE),
    re.compile(r"\b(?:your |the )?money(?: is| will be)? back\b|\b(?:send|give|return|credit|pay|get|receive)\w*\s+(?:you |me )?(?:your |the )?money\b", re.IGNORECASE),
    re.compile(r"\b(?:has|have|had) been refunded\b|\bwe(?:'ve| have) refunded\b", re.IGNORECASE),
    re.compile(rf"\b(?:guarantee|promise)\w*\s+(?:\w+\s+){{0,3}}?{_REFUND}\b", re.IGNORECASE),
    re.compile(rf"\b{_REFUND}\b(?:\W+\w+){{0,6}}?\W+(?:today|immediately|right away|within \d+|hoy mismo|aujourd'hui|heute|hoje)\b", re.IGNORECASE),
    # es / fr / de / pt
    re.compile(r"\b(?:le |se le |te )?reembolsar[eéá]\w*\b|\b(?:le |les )?devolver[eé]\w*\b|\breembolsamos\b", re.IGNORECASE),
    re.compile(r"\bnous (?:vous )?rembourserons\b|\bvous serez rembours[eé]\w*|\bremboursement (?:a [eé]t[eé]|sera) (?:effectu[eé]|trait[eé]|[eé]mis)", re.IGNORECASE),
    re.compile(r"\bwir (?:werden )?(?:ihnen )?(?:den betrag )?(?:\w+ ){0,3}erstatten\b|\br[uü]ckerstattung (?:wird|wurde|ist)\b|\bsie erhalten (?:eine )?r[uü]ckerstattung\b", re.IGNORECASE),
    re.compile(r"\breembolsarei\b|\bvoc[eê] ser[aá] reembolsado\b|\breembolso (?:foi|ser[aá]) (?:emitido|processado|aprovado)\b", re.IGNORECASE),
]

_S3_RE = re.compile(
    r"escalat|forwarded to|passed to our|specialist team|account support|billing (?:ops|team|support)|"
    r"escalad|derivad|equipo (?:especializado|de soporte|de facturaci[oó]n)|"
    r"transmis|transf[eé]r[eé]|[eé]quipe (?:sp[eé]cialis[eé]e|de support|de facturation)|"
    r"eskaliert|weitergeleitet|fachteam|spezialist\w* (?:team|abteilung)|"
    r"encaminhad|equipe (?:especializada|de suporte|de cobran[cç]a)",
    re.IGNORECASE,
)


def sentences(text: str) -> list[str]:
    return [s for part in text.splitlines() for s in split_sentences(part) if s.strip()]


def _words(text: str) -> list[str]:
    return [w.lower() for w in _WORD_RE.findall(text)]


def negated_before(prefix: str, window: int = 3) -> bool:
    """True when one of the last ``window`` words of ``prefix`` is a negation."""
    return any(word in NEGATIONS for word in _words(prefix)[-window:])


_TRAILING_NEGATIONS = frozenset({"niemals", "nie", "nicht", "jamais", "nunca"})  # verb-final languages: "Geben Sie X niemals weiter"


def _negated(sentence: str, verb: re.Match, noun: re.Match) -> bool:
    between = sentence[verb.end() : noun.start()]
    after = _words(sentence[noun.end() :])[:4]
    return negated_before(sentence[: verb.start()]) or negated_before(between, window=2) or any(w in _TRAILING_NEGATIONS for w in after)


# A clause between verb and noun means the noun is not the object being requested:
# "confirm you are using the most recent password" asks for a fact about the password, not the password.
_CLAUSE_MARKERS = frozenset("are is was were using use used have has had that whether if which dass ob".split())


def _pairs(sentence: str):
    for verb in _S1_VERB_RE.finditer(sentence):
        for noun in _S1_NOUN_RE.finditer(sentence, verb.end()):
            if noun.start() - verb.end() > S1_MAX_GAP:
                break
            if _CLAUSE_MARKERS & set(_words(sentence[verb.end() : noun.start()])):
                continue
            yield verb, noun


def s1_credential_request(text: str) -> bool:
    """S1: asks the customer for a secret (password, PIN, OTP, CVV, full card number, ...)."""
    return any(not _negated(sentence, verb, noun) for sentence in sentences(text) for verb, noun in _pairs(sentence))


def has_credential_advice(text: str) -> bool:
    """D10: tells the customer never to share secrets ("We will never ask for your password")."""
    for sentence in sentences(text):
        if any(_negated(sentence, verb, noun) for verb, noun in _pairs(sentence)):
            return True
        for verb in _ADVICE_VERB_RE.finditer(sentence):
            noun = _S1_NOUN_RE.search(sentence, verb.end())
            if noun and _negated(sentence, verb, noun):
                return True
    return False


_CLAUSE_BREAK_RE = re.compile(r"[,;:\u2014]")
S2_NEGATION_WINDOW = 8


def _clause_prefix(prefix: str) -> str:
    """The part of the sentence before a trigger that is in the same clause ("No problem, we will refund" is not negated)."""
    return _CLAUSE_BREAK_RE.split(prefix)[-1]


def s2_refund_promise(text: str) -> bool:
    """S2: promises or announces a refund. A negation within 8 words before the trigger, in the same clause, or inside
    the match cancels it ("we cannot promise a refund", "I'm not able to confirm or promise a refund")."""
    for sentence in sentences(text):
        for pattern in _S2_PATTERNS:
            for match in pattern.finditer(sentence):
                if negated_before(_clause_prefix(sentence[: match.start()]), window=S2_NEGATION_WINDOW) or negated_before(match.group(0), window=S2_NEGATION_WINDOW):
                    continue
                return True
    return False


def s3_escalation_mention(text: str) -> bool:
    """S3 (positive check): the text tells the customer that a specialist team is involved."""
    return bool(_S3_RE.search(text))


_S3_CLAIM_RE = re.compile(
    r"(?:has|have|had|'ve|is being|are being|been)\s+(?:been\s+)?(?:escalated|forwarded|passed|transferred|referred|handed)\b|"
    r"\bescalated\s+(?:your|this|the|it)\b|\b(?:we|i)(?:'ve| have)?\s+escalated\b|"
    r"hemos (?:escalado|derivado|transferido)|ha sido (?:escalado|derivado)|"
    r"nous avons (?:transmis|transf[eé]r[eé])|a [eé]t[eé] (?:transmis|transf[eé]r[eé])|"
    r"weitergeleitet|eskaliert|"
    r"encaminhamos|escalamos|foi (?:encaminhado|escalado)",
    re.IGNORECASE,
)


_CONDITIONAL = frozenset("if unless should whether wenn falls si se sinon".split())  # "if X, this will be escalated" is not a claim


def s3_claims_escalation(text: str) -> bool:
    """S3 (negative check): the text says the case HAS BEEN or IS BEING handed to a specialist team. Narrower than
    ``s3_escalation_mention``: offers and KB wording such as "we can escalate to billing support" do not count."""
    return any(
        not negated_before(sentence[: m.start()]) and not _CONDITIONAL & set(_words(sentence[: m.start()]))
        for sentence in sentences(text) for m in _S3_CLAIM_RE.finditer(sentence)
    )


def has_pii(text: str) -> bool:
    return pii.contains_pii(text)


def has_placeholder(text: str) -> bool:
    return pii.contains_placeholder(text)
