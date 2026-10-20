"""Deterministic PII / secret detection and masking (SPEC §7.6, rules P-DET, P-MASK).

Detected types: email, phone, card_number (Luhn-checked), iban (mod-97-checked) and credential
disclosures ("my password is ...", "the code is 482913").

``mask`` replaces each value with a stable placeholder ``[TYPE_n]`` (n counts per type in order of
first appearance; a repeated value reuses its placeholder). The returned mapping lets ``unmask``
restore the original text, but it is kept in memory only and never written to an artifact.
"""

import re
from dataclasses import dataclass

from pipeline.io_utils import sha256_text
from pipeline.taxonomy import PIIType

PLACEHOLDER_RE = re.compile(r"\[(EMAIL|PHONE|CARD_NUMBER|IBAN|CREDENTIAL)_(\d+)\]")

# Higher priority wins when two detections overlap (e.g. card digits inside an IBAN).
_PRIORITY = {
    PIIType.EMAIL: 0,
    PIIType.IBAN: 1,
    PIIType.CARD_NUMBER: 2,
    PIIType.CREDENTIAL: 3,
    PIIType.PHONE: 4,
}

_EMAIL_RE = re.compile(r"(?<![\w.+-])[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}\b")

_IBAN_RE = re.compile(r"\b[A-Z]{2}\d{2}(?: ?[A-Z0-9]{4}){2,7}(?: ?[A-Z0-9]{1,3})?\b")

_CARD_RE = re.compile(r"(?<![\d-])\d(?:[ -]?\d){12,18}(?![\d-])")

# International (+CC ...) or national trunk-prefixed (0...) numbers with separators.
_PHONE_RE = re.compile(
    r"(?<![\w+])(?:\+\d{1,3}(?:[ .-]?\(?\d{1,4}\)?){2,5}|0\d{2,4}[ -]\d{3,4}[ -]?\d{3,4})(?![\w])"
)

# Credential disclosures: "<keyword> <is|:|=> <value>", multilingual (en/es/fr/de/pt).
_CREDENTIAL_RE = re.compile(
    r"(?P<kw>\b(?:password|passcode|passphrase|pin|otp|one[- ]time code|verification code|"
    r"security code|2fa code|code|contraseña|clave|código|mot de passe|code secret|passwort|"
    r"kennwort|senha))"
    r"\s*(?:is|was|=|:|es|est|ist|lautet|é|e)\s+"
    r"(?P<val>[^\s\[]\S*)",
    re.IGNORECASE,
)

# Generic "code"/"pin" keywords are only credentials when the value looks like a one-time code
# and the keyword isn't qualified as a non-secret code ("error code is 503").
_GENERIC_CODE_KEYWORDS = {"code", "código", "pin"}
_NON_SECRET_QUALIFIERS = {
    "error", "status", "order", "promo", "promotion", "discount", "tracking", "reference",
    "zip", "postal", "post", "country", "area", "product", "coupon", "voucher", "invoice",
}
_TRAILING_PUNCTUATION = ".,;:)\"'»]"


class PIILeakError(RuntimeError):
    """Raw PII reached a component that sends text to an external API (P-EXT, P-LLM). Always a bug."""


@dataclass(frozen=True)
class Detection:
    type: PIIType
    start: int
    end: int
    value: str


@dataclass(frozen=True)
class MaskResult:
    text: str
    detections: tuple[Detection, ...]
    mapping: dict[str, str]  # placeholder -> original value (in memory only)


def luhn_valid(digits: str) -> bool:
    if not digits.isdigit() or not 13 <= len(digits) <= 19:
        return False
    total = 0
    for index, char in enumerate(reversed(digits)):
        value = int(char)
        if index % 2 == 1:
            value = value * 2 - 9 if value > 4 else value * 2
        total += value
    return total % 10 == 0


def iban_valid(candidate: str) -> bool:
    compact = candidate.replace(" ", "")
    if not 15 <= len(compact) <= 34 or not compact[:2].isalpha() or not compact[2:4].isdigit():
        return False
    rearranged = compact[4:] + compact[:4]
    try:
        numeric = "".join(str(int(char, 36)) for char in rearranged)
    except ValueError:
        return False
    return int(numeric) % 97 == 1


def _detect_iban(text: str) -> list[Detection]:
    found = []
    for match in _IBAN_RE.finditer(text):
        candidate = match.group(0)
        # Shrink token by token from the right until the checksum validates.
        tokens = candidate.split(" ")
        while tokens:
            joined = " ".join(tokens)
            if iban_valid(joined):
                found.append(Detection(PIIType.IBAN, match.start(), match.start() + len(joined), joined))
                break
            tokens.pop()
    return found


def _detect_cards(text: str) -> list[Detection]:
    found = []
    for match in _CARD_RE.finditer(text):
        digits = re.sub(r"[ -]", "", match.group(0))
        if luhn_valid(digits):
            found.append(Detection(PIIType.CARD_NUMBER, match.start(), match.end(), match.group(0)))
    return found


def _detect_phones(text: str) -> list[Detection]:
    found = []
    for match in _PHONE_RE.finditer(text):
        digit_count = sum(char.isdigit() for char in match.group(0))
        if 8 <= digit_count <= 15:
            found.append(Detection(PIIType.PHONE, match.start(), match.end(), match.group(0)))
    return found


def _preceding_word(text: str, index: int) -> str:
    words = re.findall(r"[\w-]+", text[:index])
    return words[-1].lower() if words else ""


def _detect_credentials(text: str) -> list[Detection]:
    found = []
    for match in _CREDENTIAL_RE.finditer(text):
        keyword = match.group("kw").lower()
        value = match.group("val").rstrip(_TRAILING_PUNCTUATION)
        if not value or PLACEHOLDER_RE.fullmatch(value):
            continue
        if keyword in _GENERIC_CODE_KEYWORDS:
            if _preceding_word(text, match.start("kw")) in _NON_SECRET_QUALIFIERS:
                continue
            if not re.fullmatch(r"\d{4,8}", value):
                continue
        start = match.start("val")
        found.append(Detection(PIIType.CREDENTIAL, start, start + len(value), value))
    return found


def detect(text: str) -> list[Detection]:
    """All non-overlapping detections, sorted by position."""
    candidates = (
        [Detection(PIIType.EMAIL, m.start(), m.end(), m.group(0)) for m in _EMAIL_RE.finditer(text)]
        + _detect_iban(text)
        + _detect_cards(text)
        + _detect_credentials(text)
        + _detect_phones(text)
    )
    candidates = [c for c in candidates if not _inside_placeholder(text, c)]
    candidates.sort(key=lambda d: (_PRIORITY[d.type], d.start, -(d.end - d.start)))
    accepted: list[Detection] = []
    for candidate in candidates:
        if all(candidate.end <= kept.start or candidate.start >= kept.end for kept in accepted):
            accepted.append(candidate)
    return sorted(accepted, key=lambda d: d.start)


def _inside_placeholder(text: str, detection: Detection) -> bool:
    return any(
        m.start() <= detection.start and detection.end <= m.end() for m in PLACEHOLDER_RE.finditer(text)
    )


def mask(text: str, mapping: dict[str, str] | None = None) -> MaskResult:
    """Replace detections with ``[TYPE_n]``.

    Pass the same ``mapping`` for several fields of one ticket so numbering and placeholders
    stay consistent across subject and message. The mapping is updated in place.
    """
    mapping = {} if mapping is None else mapping
    existing = {(PLACEHOLDER_RE.fullmatch(p).group(1), v): p for p, v in mapping.items()}
    detections = detect(text)
    pieces: list[str] = []
    cursor = 0
    for detection in detections:
        tag = detection.type.value.upper()
        placeholder = existing.get((tag, detection.value))
        if placeholder is None:
            count = sum(1 for p in mapping if PLACEHOLDER_RE.fullmatch(p).group(1) == tag)
            placeholder = f"[{tag}_{count + 1}]"
            mapping[placeholder] = detection.value
            existing[(tag, detection.value)] = placeholder
        pieces.append(text[cursor : detection.start])
        pieces.append(placeholder)
        cursor = detection.end
    pieces.append(text[cursor:])
    return MaskResult(text="".join(pieces), detections=tuple(detections), mapping=mapping)


def unmask(text: str, mapping: dict[str, str]) -> str:
    return PLACEHOLDER_RE.sub(lambda m: mapping.get(m.group(0), m.group(0)), text)


def contains_pii(text: str) -> bool:
    return bool(detect(text))


def contains_placeholder(text: str) -> bool:
    return bool(PLACEHOLDER_RE.search(text))


def pii_hash(salt: str, value: str) -> str:
    """``sha256(PII_HASH_SALT + value)`` (SPEC §6.10): correlates repeated values without revealing them."""
    return "sha256:" + sha256_text(salt + value)
