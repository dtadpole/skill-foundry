"""LocalFirstBackend — write local first, then sync to S3.

All writes go to local filesystem first (source of truth), then the
same content is uploaded to S3 as a remote backup/replica.

Reads always come from local; S3 is only consulted as a fallback when
the local file is missing (e.g. on a fresh machine or after a local wipe).

Args:
    local:  A LocalBackend instance pointing at the local root.
    s3:     An S3Backend instance for the remote replica.
"""

from __future__ import annotations

from typing import Optional

from .backend import StorageBackend
from .local import LocalBackend
from .s3 import S3Backend


class LocalFirstBackend(StorageBackend):
    """Write-local-first, S3-as-backup storage backend.

    Flow:
        put / append  →  local first, then S3
        get           →  local first; fallback to S3 if missing
        exists        →  local first; fallback to S3
        list_prefix   →  local (merged with S3 for completeness)
        delete        →  both local and S3
    """

    def __init__(self, local: LocalBackend, s3: S3Backend) -> None:
        self.local = local
        self.s3 = s3

    # ------------------------------------------------------------------

    def get(self, key: str) -> Optional[str]:
        val = self.local.get(key)
        if val is not None:
            return val
        # Fallback: pull from S3 and cache locally
        val = self.s3.get(key)
        if val is not None:
            self.local.put(key, val)   # cache for next time
        return val

    def put(self, key: str, content: str) -> None:
        self.local.put(key, content)
        self.s3.put(key, content)

    def append(self, key: str, content: str) -> None:
        # Append to local file (fast, atomic-ish via OS)
        self.local.append(key, content)
        # Upload the full updated file to S3 so it stays in sync
        full = self.local.get(key) or ""
        self.s3.put(key, full)

    def exists(self, key: str) -> bool:
        if self.local.exists(key):
            return True
        return self.s3.exists(key)

    def list_prefix(self, prefix: str) -> list[str]:
        local_keys = set(self.local.list_prefix(prefix))
        s3_keys = set(self.s3.list_prefix(prefix))
        return sorted(local_keys | s3_keys)

    def delete(self, key: str) -> None:
        self.local.delete(key)
        self.s3.delete(key)
