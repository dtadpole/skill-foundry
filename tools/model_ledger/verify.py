"""ModelLedger verification — check completeness and integrity of JSONL session logs.

JSONL format (OpenAI-compatible):
    {"role": "metadata", "type": "session_start", ...}  ← first line
    {"role": "system",    "content": "..."}
    {"role": "user",      "content": "..."}
    {"role": "assistant", "content": null, "tool_calls": [...]}
    {"role": "tool",      "tool_call_id": "...", "name": "...", "content": "..."}
    {"role": "assistant", "content": "final response"}
    {"role": "metadata", "type": "session_end", ..., "session_hash": "..."}  ← last line

Usage:
    from tools.model_ledger.verify import verify_session
    result = verify_session("model_ledger/2026-03-08/01KK5XYZ.jsonl")
    print(result.summary())
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Optional

from tools.storage import get_backend
from tools.storage.backend import StorageBackend

VALID_ROLES = {"system", "user", "assistant", "tool", "metadata"}


@dataclass
class VerifyResult:
    ok: bool
    session_id: str = ""
    total_messages: int = 0
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    session_hash: Optional[str] = None

    def summary(self) -> str:
        status = "✅ PASS" if self.ok else "❌ FAIL"
        lines = [f"{status}  session={self.session_id}  messages={self.total_messages}"]
        if self.session_hash:
            lines.append(f"  Session hash: {self.session_hash[:32]}…")
        for e in self.errors:
            lines.append(f"  ❌ {e}")
        for w in self.warnings:
            lines.append(f"  ⚠️  {w}")
        return "\n".join(lines)


def verify_session(
    jsonl_key: str,
    backend: Optional[StorageBackend] = None,
) -> VerifyResult:
    """Verify a ModelLedger JSONL session for completeness and integrity.

    Checks:
    1. First line is metadata/session_start
    2. Last line is metadata/session_end
    3. All lines are valid JSON with a 'role' field
    4. All roles are valid OpenAI roles (or 'metadata')
    5. Every tool call (assistant with tool_calls) has matching tool result(s)
    6. Session hash in session_end matches hash of all content lines
    7. No empty assistant or user messages
    """
    b = backend or get_backend()
    result = VerifyResult(ok=False)
    errors = result.errors
    warnings = result.warnings

    raw = b.get(jsonl_key)
    if not raw:
        errors.append(f"JSONL file not found: {jsonl_key}")
        return result

    records: list[dict] = []
    for i, line in enumerate(raw.splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError as e:
            errors.append(f"Line {i}: invalid JSON — {e}")

    if not records:
        errors.append("JSONL is empty")
        return result

    result.total_messages = len(records)

    # ── Check 1: session_start ────────────────────────────────────────
    first = records[0]
    if not (first.get("role") == "metadata" and first.get("type") == "session_start"):
        errors.append("First line is not metadata/session_start")
    else:
        result.session_id = first.get("session_id", "")

    # ── Check 2: session_end ─────────────────────────────────────────
    last = records[-1]
    if not (last.get("role") == "metadata" and last.get("type") == "session_end"):
        errors.append("Last line is not metadata/session_end — session may be incomplete")
        session_end = None
    else:
        session_end = last

    # ── Check 3 & 4: valid roles, non-empty content ───────────────────
    content_lines: list[str] = []  # all non-metadata lines, for hash
    pending_tool_call_ids: list[str] = []  # ids needing a tool result

    for i, rec in enumerate(records):
        role = rec.get("role", "")
        if role not in VALID_ROLES:
            errors.append(f"Line {i+1}: unknown role '{role}'")
            continue

        if role == "metadata":
            continue  # metadata lines excluded from content hash

        line_str = json.dumps(rec, ensure_ascii=False)
        content_lines.append(line_str)

        if role == "user" and not rec.get("content"):
            warnings.append(f"Line {i+1}: user message has empty content")

        if role == "assistant":
            tool_calls = rec.get("tool_calls")
            content = rec.get("content")
            if not tool_calls and not content:
                warnings.append(f"Line {i+1}: assistant message has no content and no tool_calls")
            if tool_calls:
                for tc in tool_calls:
                    tc_id = tc.get("id", "")
                    if not tc_id:
                        errors.append(f"Line {i+1}: tool_call missing 'id'")
                    else:
                        pending_tool_call_ids.append(tc_id)
                    fn = tc.get("function", {})
                    if not fn.get("name"):
                        errors.append(f"Line {i+1}: tool_call missing function name")
                    if not fn.get("arguments"):
                        warnings.append(f"Line {i+1}: tool_call '{fn.get('name', '?')}' has empty arguments")

        if role == "tool":
            tc_id = rec.get("tool_call_id", "")
            if tc_id in pending_tool_call_ids:
                pending_tool_call_ids.remove(tc_id)
            else:
                warnings.append(f"Line {i+1}: tool result references unknown tool_call_id '{tc_id}'")
            if not rec.get("content") and rec.get("content") != "":
                warnings.append(f"Line {i+1}: tool result has no content")

    # ── Check 5: unmatched tool calls ────────────────────────────────
    for tc_id in pending_tool_call_ids:
        errors.append(f"Tool call '{tc_id[:16]}…' has no matching tool result")

    # ── Check 6: session hash ────────────────────────────────────────
    if session_end:
        stored_hash = session_end.get("session_hash", "")
        computed_hash = hashlib.sha256("\n".join(content_lines).encode()).hexdigest()
        if stored_hash != computed_hash:
            errors.append(
                f"Session hash mismatch — stored={stored_hash[:16]}…, computed={computed_hash[:16]}…"
            )
        else:
            result.session_hash = stored_hash

    result.ok = len(errors) == 0
    return result
