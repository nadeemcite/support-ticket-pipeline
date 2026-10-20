"""Input loading and structural validation (SPEC §3.3, rules I1-I9).

Fatal problems (I1) raise ``InputError``. Per-record problems are collected, not raised:
a ticket without ``ticket_id`` is rejected (I3), a repeated ID keeps the first occurrence (I4).
"""

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pipeline.io_utils import sha256_bytes, sha256_canonical


class InputError(ValueError):
    """Input file missing, not JSON, or wrong top-level shape (I1). Fatal (exit 2)."""


@dataclass(frozen=True)
class InputFileInfo:
    path: str
    sha256: str
    canonical_sha256: str

    def as_dict(self) -> dict[str, str]:
        return {"path": self.path, "sha256": self.sha256, "canonical_sha256": self.canonical_sha256}


@dataclass
class LoadedInputs:
    tickets: list[dict[str, Any]]  # raw ticket dicts, each with "input_index" added
    articles: list[dict[str, Any]]
    tickets_file: InputFileInfo
    kb_file: InputFileInfo
    rejected_tickets: list[dict[str, Any]] = field(default_factory=list)
    duplicate_tickets: list[dict[str, Any]] = field(default_factory=list)
    rejected_articles: list[dict[str, Any]] = field(default_factory=list)
    duplicate_articles: list[dict[str, Any]] = field(default_factory=list)
    tickets_input_count: int = 0
    articles_input_count: int = 0


def _read_top_level(path: Path, key: str) -> tuple[list[Any], InputFileInfo]:
    path = Path(path)
    if not path.is_file():
        raise InputError(f"{path}: file not found")
    raw = path.read_bytes()
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise InputError(f"{path}: not valid JSON ({exc})") from exc
    if not isinstance(data, dict) or key not in data:
        raise InputError(f"{path}: expected a JSON object with a top-level '{key}' list")
    if not isinstance(data[key], list):
        raise InputError(f"{path}: '{key}' must be a list")
    info = InputFileInfo(path=str(path), sha256=sha256_bytes(raw), canonical_sha256=sha256_canonical(data))
    return data[key], info


def _dedupe(
    records: list[Any], id_field: str, kind: str
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    accepted: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    duplicates: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, record in enumerate(records):
        if not isinstance(record, dict):
            rejected.append({"input_index": index, "reason": f"{kind} is not a JSON object", "rule": "I3"})
            continue
        record_id = record.get(id_field)
        if not isinstance(record_id, str) or not record_id.strip():
            rejected.append({"input_index": index, "reason": f"missing {id_field}", "rule": "I3"})
            continue
        record_id = record_id.strip()
        if record_id in seen:
            duplicates.append({id_field: record_id, "input_index": index, "rule": "I4" if kind == "ticket" else "I9"})
            continue
        seen.add(record_id)
        accepted.append({**record, id_field: record_id, "input_index": index})
    return accepted, rejected, duplicates


def load_inputs(tickets_path: Path, kb_path: Path) -> LoadedInputs:
    raw_tickets, tickets_info = _read_top_level(tickets_path, "tickets")
    raw_articles, kb_info = _read_top_level(kb_path, "articles")

    tickets, rejected_t, duplicate_t = _dedupe(raw_tickets, "ticket_id", "ticket")
    articles, rejected_a, duplicate_a = _dedupe(raw_articles, "article_id", "article")

    return LoadedInputs(
        tickets=tickets,
        articles=articles,
        tickets_file=tickets_info,
        kb_file=kb_info,
        rejected_tickets=rejected_t,
        duplicate_tickets=duplicate_t,
        rejected_articles=rejected_a,
        duplicate_articles=duplicate_a,
        tickets_input_count=len(raw_tickets),
        articles_input_count=len(raw_articles),
    )
