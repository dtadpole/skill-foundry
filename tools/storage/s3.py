"""Amazon S3 storage backend."""

from __future__ import annotations

import threading
from typing import Optional

import boto3
from botocore.exceptions import ClientError

from .backend import StorageBackend


class S3Backend(StorageBackend):
    """Stores data as S3 objects in a bucket.

    Key "a/b/c.json" maps to s3://<bucket>/<prefix>a/b/c.json.

    Args:
        bucket:  S3 bucket name (e.g. "third.lantern").
        region:  AWS region (e.g. "us-east-1").
        prefix:  Optional key prefix applied to every key (e.g. "blue-lantern/").
    """

    def __init__(
        self,
        bucket: str,
        region: str = "us-east-1",
        prefix: str = "",
    ) -> None:
        self.bucket = bucket
        self.prefix = prefix
        self._s3 = boto3.client("s3", region_name=region)
        self._append_lock = threading.Lock()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _full_key(self, key: str) -> str:
        return f"{self.prefix}{key}"

    def _object_body(self, full_key: str) -> Optional[str]:
        """Download an object and return its body as a string, or None."""
        try:
            resp = self._s3.get_object(Bucket=self.bucket, Key=full_key)
            return resp["Body"].read().decode("utf-8")
        except ClientError as e:
            if e.response["Error"]["Code"] in ("NoSuchKey", "404"):
                return None
            raise

    def _put_object(self, full_key: str, content: str) -> None:
        self._s3.put_object(
            Bucket=self.bucket,
            Key=full_key,
            Body=content.encode("utf-8"),
            ContentType="text/plain; charset=utf-8",
        )

    # ------------------------------------------------------------------
    # StorageBackend interface
    # ------------------------------------------------------------------

    def get(self, key: str) -> Optional[str]:
        return self._object_body(self._full_key(key))

    def put(self, key: str, content: str) -> None:
        self._put_object(self._full_key(key), content)

    def append(self, key: str, content: str) -> None:
        """Append content to an S3 object (GET → concat → PUT).

        Uses a per-key lock so concurrent appends within the same process
        are serialized and won't clobber each other.
        """
        full_key = self._full_key(key)
        with self._append_lock:
            existing = self._object_body(full_key) or ""
            self._put_object(full_key, existing + content)

    def exists(self, key: str) -> bool:
        try:
            self._s3.head_object(Bucket=self.bucket, Key=self._full_key(key))
            return True
        except ClientError as e:
            if e.response["Error"]["Code"] in ("404", "NoSuchKey"):
                return False
            raise

    def list_prefix(self, prefix: str) -> list[str]:
        full_prefix = self._full_key(prefix)
        paginator = self._s3.get_paginator("list_objects_v2")
        keys: list[str] = []
        for page in paginator.paginate(Bucket=self.bucket, Prefix=full_prefix):
            for obj in page.get("Contents", []):
                k = obj["Key"]
                # Strip the backend prefix so callers see clean relative keys
                if k.startswith(self.prefix):
                    k = k[len(self.prefix):]
                keys.append(k)
        return sorted(keys)

    def delete(self, key: str) -> None:
        try:
            self._s3.delete_object(Bucket=self.bucket, Key=self._full_key(key))
        except ClientError:
            pass
