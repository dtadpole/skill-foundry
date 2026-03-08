"""Reader utilities for querying and summarizing model ledger logs."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .record import ModelLedgerRecord

_DEFAULT_DIR = Path.home() / ".blue_lantern" / "model_ledger"


def read_log(
    date: Optional[str] = None, path: Optional[str] = None
) -> list[ModelLedgerRecord]:
    """Read audit log records and return a list of ModelLedgerRecords.

    Args:
        date: Date string in YYYY-MM-DD format. Defaults to today (UTC).
        path: Explicit file path. If given, ``date`` is ignored.
    """
    if path:
        log_path = Path(path)
        if not log_path.exists():
            return []
        return _read_md_file(log_path)

    if date is None:
        date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    date_dir = _DEFAULT_DIR / date
    if not date_dir.exists():
        return []

    records: list[ModelLedgerRecord] = []
    for md_file in sorted(date_dir.glob("*.md")):
        records.extend(_read_md_file(md_file))
    return records


# ------------------------------------------------------------------
# Markdown parsing
# ------------------------------------------------------------------

def _extract_table_field(text: str, field: str) -> Optional[str]:
    """Extract a value from a Markdown table row."""
    m = re.search(rf"\|\s*{re.escape(field)}\s*\|\s*(.+?)\s*\|", text)
    return m.group(1).strip() if m else None


def _read_md_file(path: Path) -> list[ModelLedgerRecord]:
    """Read a Markdown session file and return ModelLedgerRecords (one per turn)."""
    text = path.read_text(encoding="utf-8")
    records: list[ModelLedgerRecord] = []

    # Extract session metadata from header
    model = _extract_table_field(text, "Model") or ""
    provider = _extract_table_field(text, "Provider") or ""
    session_id = _extract_table_field(text, "ID") or path.stem

    # Split into turn sections
    turn_pattern = re.compile(r"^## Turn \d+ — (.+)$", re.MULTILINE)
    turn_starts = list(turn_pattern.finditer(text))

    for i, match in enumerate(turn_starts):
        timestamp = match.group(1).strip()
        start = match.end()
        if i + 1 < len(turn_starts):
            end = turn_starts[i + 1].start()
        else:
            session_end = text.find("## Session End", start)
            end = session_end if session_end != -1 else len(text)

        turn_text = text[start:end]
        messages = _parse_messages(turn_text)
        response_text = _extract_last_assistant(turn_text)
        tool_calls = _parse_tool_calls(turn_text)

        records.append(ModelLedgerRecord(
            session_id=session_id,
            timestamp=timestamp,
            provider=provider,
            model=model,
            messages=[{"role": m["role"], "content": m["content"]} for m in messages],
            response=response_text,
            tool_calls=tool_calls,
        ))

    return records


def _parse_messages(turn_text: str) -> list[dict]:
    """Extract messages from a turn section."""
    messages: list[dict] = []
    role_map = {
        "🔧 System": "system",
        "👤 User": "user",
        "🤖 Assistant": "assistant",
    }
    msg_pattern = re.compile(
        r"### (🔧 System|👤 User|🤖 Assistant(?:\s*\(continued\))?)\n\n(.*?)(?=\n### |\Z)",
        re.DOTALL,
    )
    for m in msg_pattern.finditer(turn_text):
        header = m.group(1).strip()
        content = m.group(2).strip()
        role = "assistant"
        for k, v in role_map.items():
            if header.startswith(k):
                role = v
                break
        if role == "system":
            content = re.sub(r"^> ?", "", content, flags=re.MULTILINE).strip()
        messages.append({"role": role, "content": content})
    return messages


def _extract_last_assistant(turn_text: str) -> str:
    """Extract the last assistant response text from a turn."""
    pattern = re.compile(
        r"### 🤖 Assistant(?:\s*\(continued\))?\n\n(.*?)(?=\n### |\Z)",
        re.DOTALL,
    )
    matches = list(pattern.finditer(turn_text))
    if matches:
        return matches[-1].group(1).strip()
    return ""


def _parse_tool_calls(turn_text: str) -> list[dict]:
    """Extract tool calls from a turn section."""
    tool_calls: list[dict] = []
    sections = re.split(r"(?=### )", turn_text)

    current_tc: Optional[dict] = None
    for section in sections:
        if "🛠️ Tool Call" in section and section.startswith("### 🛠️"):
            name_match = re.search(r"`([^`]+)`", section)
            name = name_match.group(1) if name_match else "unknown"
            input_match = re.search(r"```json\n(.*?)\n```", section, re.DOTALL)
            tc_input: Any = {}
            if input_match:
                try:
                    tc_input = json.loads(input_match.group(1))
                except json.JSONDecodeError:
                    tc_input = input_match.group(1)
            current_tc = {"name": name, "input": tc_input}
            tool_calls.append(current_tc)

        elif section.startswith("### ↩️ Tool Response") and current_tc is not None:
            output_match = re.search(r"```\n(.*?)\n```", section, re.DOTALL)
            if output_match:
                current_tc["output"] = output_match.group(1)
            current_tc = None

        elif section.startswith("### ❌ Tool Error") and current_tc is not None:
            error_match = re.search(r"```\n(.*?)\n```", section, re.DOTALL)
            if error_match:
                current_tc["error"] = error_match.group(1)
            current_tc = None

    return tool_calls


# ------------------------------------------------------------------
# Filter & Summarize (unchanged)
# ------------------------------------------------------------------

def filter_records(
    records: list[ModelLedgerRecord],
    *,
    provider: Optional[str] = None,
    model: Optional[str] = None,
    status: Optional[str] = None,
    since: Optional[str] = None,
) -> list[ModelLedgerRecord]:
    """Filter a list of ModelLedgerRecords by provider, model, status, or timestamp.

    Args:
        records: List of records to filter.
        provider: Keep only records matching this provider.
        model: Keep only records matching this model.
        status: Keep only records matching this status.
        since: ISO 8601 timestamp — keep only records at or after this time.
    """
    result = records
    if provider is not None:
        result = [r for r in result if r.provider == provider]
    if model is not None:
        result = [r for r in result if r.model == model]
    if status is not None:
        result = [r for r in result if r.status == status]
    if since is not None:
        result = [r for r in result if r.timestamp >= since]
    return result


def summarize(records: list[ModelLedgerRecord]) -> dict:
    """Produce a summary dict from a list of ModelLedgerRecords.

    Returns:
        Dict with keys: total_calls, total_prompt_tokens, total_completion_tokens,
        total_tokens, total_cost_usd, avg_latency_ms, error_rate.
    """
    total = len(records)
    if total == 0:
        return {
            "total_calls": 0,
            "total_prompt_tokens": 0,
            "total_completion_tokens": 0,
            "total_tokens": 0,
            "total_cost_usd": 0.0,
            "avg_latency_ms": 0.0,
            "error_rate": 0.0,
        }

    prompt_tokens = sum(r.prompt_tokens or 0 for r in records)
    completion_tokens = sum(r.completion_tokens or 0 for r in records)
    total_tokens = sum(r.total_tokens or 0 for r in records)
    total_cost = sum(r.cost_usd or 0.0 for r in records)
    avg_latency = sum(r.latency_ms for r in records) / total
    errors = sum(1 for r in records if r.status == "error")

    return {
        "total_calls": total,
        "total_prompt_tokens": prompt_tokens,
        "total_completion_tokens": completion_tokens,
        "total_tokens": total_tokens,
        "total_cost_usd": round(total_cost, 8),
        "avg_latency_ms": round(avg_latency, 2),
        "error_rate": round(errors / total, 4),
    }
