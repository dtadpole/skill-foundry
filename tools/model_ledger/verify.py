"""ModelLedger verification — check completeness and integrity of session logs.

Usage:
    from tools.model_ledger.verify import verify_session
    result = verify_session("model_ledger/2026-03-08/01KK5XYZ.jsonl")
    print(result.ok, result.errors)
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Optional

from tools.storage import get_backend
from tools.storage.backend import StorageBackend


@dataclass
class VerifyResult:
    """Result of a session verification."""

    ok: bool
    session_id: str = ""
    total_turns: int = 0
    verified_turns: int = 0
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    session_hash: Optional[str] = None

    def summary(self) -> str:
        status = "✅ PASS" if self.ok else "❌ FAIL"
        lines = [
            f"{status}  session={self.session_id}",
            f"  Turns: {self.verified_turns}/{self.total_turns} verified",
        ]
        if self.session_hash:
            lines.append(f"  Session hash: {self.session_hash[:16]}…")
        for e in self.errors:
            lines.append(f"  ❌ {e}")
        for w in self.warnings:
            lines.append(f"  ⚠️  {w}")
        return "\n".join(lines)


def verify_session(
    jsonl_key: str,
    backend: Optional[StorageBackend] = None,
) -> VerifyResult:
    """Verify a ModelLedger JSONL session file for completeness and integrity.

    Checks:
    1. Session starts with a 'session_start' record
    2. Each 'turn' record's hash matches its content
    3. Turns are sequential (no gaps, no duplicates)
    4. Each turn has non-empty messages and response
    5. Session ends with a 'session_end' record
    6. Session-level hash matches all turn hashes chained

    Args:
        jsonl_key: Storage key for the .jsonl file
        backend: Storage backend (defaults to get_backend())

    Returns:
        VerifyResult with ok=True if all checks pass
    """
    b = backend or get_backend()
    result = VerifyResult(ok=False)
    errors = result.errors
    warnings = result.warnings

    raw = b.get(jsonl_key)
    if not raw:
        errors.append(f"JSONL file not found: {jsonl_key}")
        return result

    records = []
    for i, line in enumerate(raw.splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError as e:
            errors.append(f"Line {i}: invalid JSON — {e}")

    if not records:
        errors.append("JSONL file is empty")
        return result

    # ── Check 1: session_start ──────────────────────────────────────
    if records[0].get("type") != "session_start":
        errors.append("First record is not 'session_start'")
    else:
        result.session_id = records[0].get("session_id", "")

    # ── Check 2: session_end ────────────────────────────────────────
    if records[-1].get("type") != "session_end":
        errors.append("Last record is not 'session_end' — session may be incomplete")
        session_end = None
    else:
        session_end = records[-1]
        result.total_turns = session_end.get("total_turns", 0)

    # ── Check 3: turn records ───────────────────────────────────────
    turn_records = [r for r in records if r.get("type") == "turn"]
    turn_hashes: list[str] = []
    expected_turn = 1

    for rec in turn_records:
        tn = rec.get("turn_number", -1)

        # Sequential order
        if tn != expected_turn:
            errors.append(f"Turn sequence gap: expected {expected_turn}, got {tn}")
        expected_turn = tn + 1

        # Hash verification
        stored_hash = rec.get("hash", "")
        payload = {k: v for k, v in rec.items() if k != "hash"}
        computed = hashlib.sha256(
            json.dumps(payload, ensure_ascii=False, sort_keys=True).encode()
        ).hexdigest()
        if stored_hash != computed:
            errors.append(
                f"Turn {tn}: hash mismatch — stored={stored_hash[:16]}…, computed={computed[:16]}…"
            )
        else:
            result.verified_turns += 1
            turn_hashes.append(stored_hash)

        # Content completeness
        messages = rec.get("messages", [])
        response = rec.get("response", "")
        tool_calls = rec.get("tool_calls", [])

        if not messages:
            warnings.append(f"Turn {tn}: no messages recorded")
        if not response and not tool_calls:
            warnings.append(f"Turn {tn}: no response and no tool_calls")

        # Check tool_calls have both input and output
        for tc in tool_calls:
            name = tc.get("name", "?")
            if "input" not in tc:
                errors.append(f"Turn {tn}: tool '{name}' missing input")
            if "output" not in tc and "error" not in tc:
                warnings.append(f"Turn {tn}: tool '{name}' has no output or error recorded")

        # Content size sanity (exclude metadata fields, same as logger)
        recorded_chars = rec.get("content_chars", 0)
        _meta = {"content_chars", "hash"}
        content_only = {k: v for k, v in rec.items() if k not in _meta}
        actual_chars = len(json.dumps(content_only, ensure_ascii=False, sort_keys=True))
        if recorded_chars > 0 and abs(actual_chars - recorded_chars) > 2:
            warnings.append(
                f"Turn {tn}: content_chars mismatch (recorded={recorded_chars}, actual={actual_chars})"
            )

    # ── Check 4: session-level hash chain ───────────────────────────
    if session_end and turn_hashes:
        expected_session_hash = hashlib.sha256(
            "".join(turn_hashes).encode()
        ).hexdigest()
        stored_session_hash = session_end.get("session_hash", "")
        if stored_session_hash != expected_session_hash:
            errors.append(
                f"Session hash mismatch — stored={stored_session_hash[:16]}…, "
                f"computed={expected_session_hash[:16]}…"
            )
        else:
            result.session_hash = stored_session_hash

    # ── Check 5: turn count consistency ─────────────────────────────
    if session_end:
        declared = session_end.get("total_turns", 0)
        actual = len(turn_records)
        if declared != actual:
            errors.append(
                f"Turn count mismatch: session_end says {declared}, found {actual} turn records"
            )

    result.ok = len(errors) == 0
    return result
