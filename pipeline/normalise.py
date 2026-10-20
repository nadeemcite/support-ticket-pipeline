"""Ticket and KB normalisation, including PII masking (DESIGN §6.1, SPEC §3.3 and §7.6).

Normalisation never changes meaning: it cleans text, defaults missing fields with a note, and
masks PII so that no later stage (or external API) ever sees raw values. It is idempotent:
normalising an already-normalised record returns an identical record.
"""

import re
import unicodedata
from typing import Any

from pipeline import pii
from pipeline.io_utils import canonical_json, sha256_canonical
from pipeline.schemas import KBArticle, NormalisedTicket, PIISummaryEntry
from pipeline.taxonomy import KNOWN_CUSTOMER_TIERS, PIIType

DEFAULT_LANGUAGE = "en"

_TICKET_FIELDS = {"ticket_id", "customer_tier", "language", "subject", "message", "created_at", "input_index"}
# Fields that only exist on already-normalised records (lets normalise() accept its own output).
_NORMALISED_FIELDS = {"insufficient_content", "truncated", "notes", "extra", "pii_summary", "content_hash"}
_WHITESPACE_RE = re.compile(r"\s+")


def clean_text(value: Any) -> str:
    """NFC, control characters removed, whitespace collapsed, trimmed."""
    if value is None:
        return ""
    text = unicodedata.normalize("NFC", str(value))
    text = "".join(" " if char in "\t\n\r\f\v" else char for char in text)
    text = "".join(char for char in text if unicodedata.category(char) != "Cc")
    return _WHITESPACE_RE.sub(" ", text).strip()


def normalise_language(value: Any) -> str | None:
    """``en-GB`` / ``EN`` -> ``en``. Returns None when blank or missing."""
    text = clean_text(value).lower()
    if not text:
        return None
    return re.split(r"[-_]", text, maxsplit=1)[0] or None


def _mask_extra(value: Any, mapping: dict[str, str]) -> Any:
    if isinstance(value, str):
        return pii.mask(value, mapping).text
    if isinstance(value, list):
        return [_mask_extra(item, mapping) for item in value]
    if isinstance(value, dict):
        return {key: _mask_extra(item, mapping) for key, item in value.items()}
    return value


def _pii_summary(
    mapping: dict[str, str], salt: str, previous: list[dict[str, Any]], masked_fields: list[str]
) -> list[PIISummaryEntry]:
    """One entry per placeholder, in first-occurrence order.

    ``previous`` carries entries from an already-normalised record (whose mapping is gone), which
    keeps normalisation idempotent; ``count`` is always recomputed from the masked text.
    """
    combined = " ".join(masked_fields)
    entries: dict[str, tuple[PIIType, str]] = {}
    for entry in previous:
        entries[entry["placeholder"]] = (PIIType(entry["type"]), entry["hash"])
    for placeholder, value in mapping.items():
        if placeholder not in entries:
            tag = pii.PLACEHOLDER_RE.fullmatch(placeholder).group(1)
            entries[placeholder] = (PIIType(tag.lower()), pii.pii_hash(salt, value))
    return [
        PIISummaryEntry(type=pii_type, placeholder=placeholder, count=combined.count(placeholder), hash=value_hash)
        for placeholder, (pii_type, value_hash) in entries.items()
    ]


def normalise_ticket(raw: dict[str, Any], max_chars: int, salt: str) -> NormalisedTicket:
    notes: list[str] = list(raw.get("notes") or [])

    def note(text: str) -> None:
        if text not in notes:
            notes.append(text)

    language = normalise_language(raw.get("language"))
    if language is None:
        language = DEFAULT_LANGUAGE
        note("language defaulted to 'en' (missing or blank)")

    tier = clean_text(raw.get("customer_tier")).lower()
    if not tier:
        tier = "unknown"
        note("customer_tier missing")
    if tier not in KNOWN_CUSTOMER_TIERS:
        note(f"unknown customer_tier '{tier}'")

    for name in ("subject", "message"):
        if name not in raw:
            note(f"{name} missing")
    if raw.get("created_at") in (None, ""):
        note("created_at missing")

    # Mask before truncation so a cut never splits a PII value and leaks part of it.
    mapping: dict[str, str] = {}
    subject = pii.mask(clean_text(raw.get("subject")), mapping).text
    message = pii.mask(clean_text(raw.get("message")), mapping).text

    truncated = bool(raw.get("truncated", False))
    if len(message) > max_chars:
        # Drop a placeholder cut in half by the limit so no "[EMAIL_" fragment remains.
        message = re.sub(r"\[[A-Z_0-9]*$", "", message[:max_chars]).rstrip()
        truncated = True
        note(f"message truncated to {max_chars} characters")

    extra = dict(raw.get("extra") or {})
    extra.update({k: v for k, v in raw.items() if k not in _TICKET_FIELDS | _NORMALISED_FIELDS})
    extra = _mask_extra(dict(sorted(extra.items())), mapping)

    summary = _pii_summary(
        mapping, salt, list(raw.get("pii_summary") or []), [subject, message, canonical_json(extra)]
    )

    content = {"subject": subject, "message": message, "language": language, "customer_tier": tier}
    return NormalisedTicket(
        ticket_id=clean_text(raw["ticket_id"]),
        input_index=int(raw.get("input_index", 0)),
        customer_tier=tier,
        language=language,
        subject=subject,
        message=message,
        created_at=clean_text(raw.get("created_at")) or None,
        insufficient_content=not subject and not message,
        truncated=truncated,
        notes=notes,
        extra=extra,
        pii_summary=summary,
        content_hash="sha256:" + sha256_canonical(content),
    )


def normalise_tickets(raw_tickets: list[dict[str, Any]], max_chars: int, salt: str) -> list[NormalisedTicket]:
    return [normalise_ticket(raw, max_chars, salt) for raw in raw_tickets]


def normalise_article(raw: dict[str, Any]) -> KBArticle:
    return KBArticle(
        article_id=clean_text(raw["article_id"]),
        title=clean_text(raw.get("title")),
        category=clean_text(raw.get("category")).lower(),
        updated_at=clean_text(raw.get("updated_at")) or None,
        content=clean_text(raw.get("content")),
    )
