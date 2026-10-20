"""Content-addressed JSON cache under ``.cache/`` (DESIGN §6.10, SPEC §10).

Keys are hashes of everything that affects a result, so a stale entry can never be returned for
changed inputs. ``read_enabled=False`` (``--no-cache``) bypasses reads but still writes.
"""

from pathlib import Path
from typing import Any

from pipeline.io_utils import atomic_write_json, read_json


class JsonCache:
    def __init__(self, root: Path, read_enabled: bool = True) -> None:
        self.root = Path(root)
        self.read_enabled = read_enabled
        self.hits = 0
        self.misses = 0

    def _path(self, *key_parts: str) -> Path:
        safe = [part.replace(":", "_").replace("/", "_") for part in key_parts]
        return self.root.joinpath(*safe[:-1], f"{safe[-1]}.json")

    def get(self, *key_parts: str) -> Any | None:
        path = self._path(*key_parts)
        if self.read_enabled and path.is_file():
            try:
                value = read_json(path)
            except ValueError:
                value = None  # a corrupt entry is treated as a miss and overwritten
            if value is not None:
                self.hits += 1
                return value
        self.misses += 1
        return None

    def put(self, value: Any, *key_parts: str) -> None:
        atomic_write_json(self._path(*key_parts), value)

    def stats(self) -> dict[str, int]:
        return {"hits": self.hits, "misses": self.misses}
