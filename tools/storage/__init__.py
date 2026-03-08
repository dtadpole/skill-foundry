"""skill-foundry storage backends.

Quick start:
    from tools.storage import get_backend
    backend = get_backend()
    backend.put("my/key.json", '{"hello": "world"}')
    data = backend.get("my/key.json")
"""

from .backend import StorageBackend
from .config import get_backend
from .local import LocalBackend
from .s3 import S3Backend

__all__ = ["StorageBackend", "LocalBackend", "S3Backend", "get_backend"]
