"""Local filesystem storage backend."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from .backend import StorageBackend


class LocalBackend(StorageBackend):
    """Stores data as files under a root directory.

    Key "a/b/c.json" maps to <root>/a/b/c.json.
    """

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).expanduser()

    def _path(self, key: str) -> Path:
        return self.root / key

    def get(self, key: str) -> Optional[str]:
        p = self._path(key)
        if not p.exists():
            return None
        return p.read_text(encoding="utf-8")

    def put(self, key: str, content: str) -> None:
        p = self._path(key)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")

    def append(self, key: str, content: str) -> None:
        p = self._path(key)
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "a", encoding="utf-8") as f:
            f.write(content)

    def exists(self, key: str) -> bool:
        return self._path(key).exists()

    def list_prefix(self, prefix: str) -> list[str]:
        base = self.root / prefix
        # If prefix points to a directory, list all files under it
        if base.is_dir():
            return sorted(
                str(p.relative_to(self.root))
                for p in base.rglob("*")
                if p.is_file()
            )
        # Otherwise match as a path prefix
        parent = base.parent
        stem = base.name
        if not parent.exists():
            return []
        return sorted(
            str(p.relative_to(self.root))
            for p in parent.rglob("*")
            if p.is_file() and str(p.relative_to(self.root)).startswith(prefix)
        )

    def delete(self, key: str) -> None:
        p = self._path(key)
        if p.exists():
            p.unlink()
