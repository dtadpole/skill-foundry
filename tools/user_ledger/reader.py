"""Reader utilities for querying and searching user-agent conversation logs."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .record import MessageRecord, ConversationRecord

_DEFAULT_DIR = Path.home() / ".blue_lantern" / "user_ledger"

# Regex to parse message headers like:  ### [2026-03-07T23:10:05Z] 👤 User
_MSG_HEADER_RE = re.compile(
    r"^### \[([^\]]+)\] (.+)$"
)

_ROLE_LOOKUP = {
    "👤 User": "user",
    "🤖 Assistant": "assistant",
    "⚙️ System": "system",
}


def _parse_md_messages(path: Path) -> list[MessageRecord]:
    """Parse message records from a session Markdown file."""
    text = path.read_text(encoding="utf-8")
    records: list[MessageRecord] = []

    # Split on message headers
    parts = re.split(r"(?=^### \[)", text, flags=re.MULTILINE)
    for part in parts:
        lines = part.strip().split("\n")
        if not lines:
            continue
        m = _MSG_HEADER_RE.match(lines[0])
        if not m:
            continue
        timestamp = m.group(1)
        role_display = m.group(2)
        role = _ROLE_LOOKUP.get(role_display, role_display.lower())

        # Content is everything after the header line until --- separator
        content_lines = []
        for line in lines[1:]:
            if line.strip() == "---":
                break
            if line.startswith("**Attachments:**"):
                break
            content_lines.append(line)
        content = "\n".join(content_lines).strip()

        # Extract session_id from the file name
        session_id = path.stem

        records.append(MessageRecord(
            role=role,
            content=content,
            timestamp=timestamp,
            channel=_extract_field(text, "Channel"),
        ))
    return records


def _extract_field(text: str, field: str) -> Optional[str]:
    """Extract a value from a Markdown table row."""
    m = re.search(rf"\| {re.escape(field)} \| (.+?) \|", text)
    return m.group(1).strip() if m else None


def _parse_md_session_info(path: Path) -> dict:
    """Parse session metadata from a Markdown file header."""
    text = path.read_text(encoding="utf-8")
    session_id = path.stem
    return {
        "session_id": session_id,
        "started_at": _extract_field(text, "Started"),
        "ended_at": _extract_field(text, "Ended"),
        "channel": _extract_field(text, "Channel"),
        "user_name": _extract_user_name(text),
        "total_messages": _extract_int_field(text, "Total Messages"),
        "summary": _extract_field(text, "Summary"),
    }


def _extract_user_name(text: str) -> Optional[str]:
    """Extract user name from the User field."""
    raw = _extract_field(text, "User")
    if not raw:
        return None
    # Strip phone/id in parens: "Zhen Chen (+19175455890)" → "Zhen Chen"
    m = re.match(r"^(.*?)\s*\(", raw)
    return m.group(1).strip() if m else raw.strip()


def _extract_int_field(text: str, field: str) -> int:
    raw = _extract_field(text, field)
    try:
        return int(raw) if raw else 0
    except ValueError:
        return 0


def read_messages(
    date: Optional[str] = None,
    channel: Optional[str] = None,
    user_id: Optional[str] = None,
    log_dir: Optional[str | Path] = None,
) -> list[MessageRecord]:
    """Read messages from session Markdown files, optionally filtered.

    Args:
        date: Date string in YYYY-MM-DD format. Defaults to today (UTC).
        channel: Filter to only messages from this channel.
        user_id: Filter to only messages from this sender_id.
        log_dir: Root log directory. Defaults to ~/.blue_lantern/user_ledger/.
    """
    if date is None:
        date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    root = Path(log_dir) if log_dir else _DEFAULT_DIR
    date_dir = root / date
    if not date_dir.exists():
        return []

    records: list[MessageRecord] = []
    for md_file in sorted(date_dir.glob("*.md")):
        msgs = _parse_md_messages(md_file)
        for rec in msgs:
            if channel and rec.channel != channel:
                continue
            if user_id and rec.sender_id != user_id:
                continue
            records.append(rec)
    return records


def read_session(
    session_id: str,
    log_dir: Optional[str | Path] = None,
) -> Optional[ConversationRecord]:
    """Read a session by session ID.

    Searches all date directories for the session file.

    Args:
        session_id: The UUID of the session.
        log_dir: Root log directory. Defaults to ~/.blue_lantern/user_ledger/.
    """
    root = Path(log_dir) if log_dir else _DEFAULT_DIR
    for date_dir in sorted(root.glob("*")):
        if not date_dir.is_dir():
            continue
        session_path = date_dir / f"{session_id}.md"
        if session_path.exists():
            messages = _parse_md_messages(session_path)
            info = _parse_md_session_info(session_path)
            return ConversationRecord(
                session_id=session_id,
                started_at=info.get("started_at", ""),
                ended_at=info.get("ended_at"),
                channel=info.get("channel"),
                user_name=info.get("user_name"),
                messages=messages,
                total_turns=info.get("total_messages", 0),
                summary=info.get("summary"),
            )
    return None


def list_sessions(
    date: Optional[str] = None,
    channel: Optional[str] = None,
    log_dir: Optional[str | Path] = None,
) -> list[dict]:
    """List session summaries as lightweight index entries.

    Args:
        date: Filter to sessions from this YYYY-MM-DD date.
        channel: Filter to sessions on this channel.
        log_dir: Root log directory. Defaults to ~/.blue_lantern/user_ledger/.

    Returns:
        List of dicts with keys: session_id, started_at, ended_at, channel,
        user_name, total_messages, summary.
    """
    root = Path(log_dir) if log_dir else _DEFAULT_DIR

    if date:
        date_dirs = [root / date]
    else:
        date_dirs = sorted(root.glob("*"))

    results: list[dict] = []
    for date_dir in date_dirs:
        if not date_dir.is_dir():
            continue
        for md_file in sorted(date_dir.glob("*.md")):
            info = _parse_md_session_info(md_file)
            if channel and info.get("channel") != channel:
                continue
            results.append(info)
    return results


def search(
    query: str,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    log_dir: Optional[str | Path] = None,
) -> list[MessageRecord]:
    """Simple substring search across session Markdown files.

    Args:
        query: Substring to search for (case-insensitive).
        date_from: Earliest date to search (YYYY-MM-DD).
        date_to: Latest date to search (YYYY-MM-DD).
        log_dir: Root log directory. Defaults to ~/.blue_lantern/user_ledger/.

    Returns:
        List of matching MessageRecords.
    """
    root = Path(log_dir) if log_dir else _DEFAULT_DIR
    query_lower = query.lower()
    results: list[MessageRecord] = []

    for date_dir in sorted(root.glob("*")):
        if not date_dir.is_dir():
            continue
        dir_date = date_dir.name
        if date_from and dir_date < date_from:
            continue
        if date_to and dir_date > date_to:
            continue
        for md_file in sorted(date_dir.glob("*.md")):
            msgs = _parse_md_messages(md_file)
            for rec in msgs:
                if query_lower in rec.content.lower():
                    results.append(rec)
    return results


def summarize(messages: list[MessageRecord]) -> dict:
    """Produce summary statistics from a list of messages.

    Returns:
        Dict with keys: total_messages, by_role, by_channel, avg_length.
    """
    total = len(messages)
    if total == 0:
        return {
            "total_messages": 0,
            "by_role": {},
            "by_channel": {},
            "avg_length": 0.0,
        }

    by_role: dict[str, int] = {}
    by_channel: dict[str, int] = {}
    total_length = 0

    for msg in messages:
        by_role[msg.role] = by_role.get(msg.role, 0) + 1
        ch = msg.channel or "unknown"
        by_channel[ch] = by_channel.get(ch, 0) + 1
        total_length += len(msg.content)

    return {
        "total_messages": total,
        "by_role": by_role,
        "by_channel": by_channel,
        "avg_length": round(total_length / total, 2),
    }
