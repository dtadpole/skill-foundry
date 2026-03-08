"""ULID utility — drop-in replacement for uuid4() ID generation.

ULIDs are 26-character, lexicographically sortable, URL-safe identifiers.
Format: TTTTTTTTTTEEEEEEEEEEEEEEEE (10-char timestamp + 16-char entropy).

Usage:
    from tools.ulid_utils import new_ulid
    id = new_ulid()  # e.g. "01HXYZ3NDEKTSV4RRFFQ69G5FAV"
"""

from __future__ import annotations

from ulid import ULID


def new_ulid() -> str:
    """Return a new ULID as a 26-character uppercase string."""
    return str(ULID())
