"""Atomic writes, canonical JSON and hashing.

Every artifact goes through ``atomic_write_json`` so a crash never leaves a half-written file:
the payload is written to a temp file in the same directory, fsynced, then ``os.replace``d.
"""

import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any


def canonical_json(obj: Any) -> str:
    """Key-order independent, whitespace-free JSON used for hashing."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_text(text: str) -> str:
    return sha256_bytes(text.encode("utf-8"))


def sha256_canonical(obj: Any) -> str:
    return sha256_text(canonical_json(obj))


def sha256_file(path: Path) -> str:
    return sha256_bytes(Path(path).read_bytes())


def dump_json(obj: Any) -> str:
    """Pretty, deterministic serialisation for human-readable artifacts."""
    return json.dumps(obj, indent=2, ensure_ascii=False) + "\n"


def atomic_write_text(path: Path, text: str) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, path)
    except BaseException:
        Path(tmp_name).unlink(missing_ok=True)
        raise


def atomic_write_json(path: Path, obj: Any) -> None:
    atomic_write_text(path, dump_json(obj))


def read_json(path: Path) -> Any:
    with Path(path).open(encoding="utf-8") as handle:
        return json.load(handle)


def artifact_parses(path: Path) -> bool:
    """True when the file exists and is valid JSON (or JSON Lines for ``.jsonl``)."""
    path = Path(path)
    if not path.is_file():
        return False
    try:
        if path.suffix == ".jsonl":
            for line in path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    json.loads(line)
        else:
            read_json(path)
    except (OSError, ValueError):
        return False
    return True
