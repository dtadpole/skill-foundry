"""Auto-detect and build the active storage backend from environment or config.

Environment variables:
    SKILL_FOUNDRY_STORAGE        = "local" | "s3"  (default: "local")
    SKILL_FOUNDRY_S3_BUCKET      = bucket name
    SKILL_FOUNDRY_S3_REGION      = AWS region (default: "us-east-1")
    SKILL_FOUNDRY_S3_PREFIX      = key prefix  (default: "")
    SKILL_FOUNDRY_LOCAL_ROOT     = local root dir (default: ~/.blue_lantern)

Usage:
    from tools.storage.config import get_backend
    backend = get_backend()
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Optional

from .backend import StorageBackend

_CONFIG_FILE = Path.home() / ".skill-foundry.json"
_DEFAULT_LOCAL_ROOT = Path.home() / ".blue_lantern"

# Module-level cache so every caller shares the same backend instance.
_cached_backend: Optional[StorageBackend] = None


def get_backend(force_new: bool = False) -> StorageBackend:
    """Return the configured storage backend (cached singleton).

    Args:
        force_new: If True, bypass the cache and create a fresh instance
                   (useful in tests or after env changes).
    """
    global _cached_backend
    if _cached_backend is not None and not force_new:
        return _cached_backend
    _cached_backend = _build_backend()
    return _cached_backend


def _build_backend() -> StorageBackend:
    cfg = _load_config_file()

    storage_type = (
        os.environ.get("SKILL_FOUNDRY_STORAGE")
        or cfg.get("storage")
        or "local"
    ).lower()

    if storage_type == "s3":
        from .local import LocalBackend
        from .local_first import LocalFirstBackend
        from .s3 import S3Backend

        bucket = (
            os.environ.get("SKILL_FOUNDRY_S3_BUCKET")
            or cfg.get("s3_bucket")
            or ""
        )
        region = (
            os.environ.get("SKILL_FOUNDRY_S3_REGION")
            or cfg.get("s3_region")
            or "us-east-1"
        )
        prefix = (
            os.environ.get("SKILL_FOUNDRY_S3_PREFIX")
            or cfg.get("s3_prefix")
            or ""
        )
        local_root = (
            os.environ.get("SKILL_FOUNDRY_LOCAL_ROOT")
            or cfg.get("local_root")
            or str(_DEFAULT_LOCAL_ROOT)
        )

        if not bucket:
            raise RuntimeError(
                "S3 storage selected but SKILL_FOUNDRY_S3_BUCKET is not set. "
                "Set it via env var or ~/.skill-foundry.json."
            )

        local = LocalBackend(root=local_root)
        s3 = S3Backend(bucket=bucket, region=region, prefix=prefix)
        return LocalFirstBackend(local=local, s3=s3)

    else:
        from .local import LocalBackend

        root = (
            os.environ.get("SKILL_FOUNDRY_LOCAL_ROOT")
            or cfg.get("local_root")
            or str(_DEFAULT_LOCAL_ROOT)
        )
        return LocalBackend(root=root)


def _load_config_file() -> dict:
    if _CONFIG_FILE.exists():
        try:
            return json.loads(_CONFIG_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return {}
