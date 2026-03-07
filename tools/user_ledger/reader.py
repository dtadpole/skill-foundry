"""Reader utilities for querying and searching user-agent conversation logs."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .record import MessageRecord, ConversationRecord

_DEFAULT_DIR = Path.home() / ".skillfoundry" / "user_ledger"


def read_messages(
    date: Optional[str] = None,
    channel: Optional[str] = None,
    user_id: Optional[str] = None,
    log_dir: Optional[str | Path] = None,
) -> list[MessageRecord]:
    """Read messages from a daily log file, optionally filtered.

    Args:
        date: Date string in YYYY-MM-DD format. Defaults to today (UTC).
        channel: Filter to only messages from this channel.
        user_id: Filter to only messages from this sender_id.
        log_dir: Root log directory. Defaults to ~/.skillfoundry/user_ledger/.
    """
    if date is None:
        date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    root = Path(log_dir) if log_dir else _DEFAULT_DIR
    # Derive the YYYY-MM subdirectory from the date
    month_dir = root / date[:7]
    log_path = month_dir / f"{date}.jsonl"

    if not log_path.exists():
        return []

    records: list[MessageRecord] = []
    with open(log_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            rec = MessageRecord.from_jsonl(line)
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
    """Read a session summary by session ID.

    Searches all month directories for the session file.

    Args:
        session_id: The UUID of the session.
        log_dir: Root log directory. Defaults to ~/.skillfoundry/user_ledger/.
    """
    root = Path(log_dir) if log_dir else _DEFAULT_DIR
    # Search all month directories
    for month_dir in sorted(root.glob("*")):
        session_path = month_dir / "sessions" / f"{session_id}.json"
        if session_path.exists():
            with open(session_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return ConversationRecord.from_dict(data)
    return None


def list_sessions(
    date: Optional[str] = None,
    channel: Optional[str] = None,
    log_dir: Optional[str | Path] = None,
) -> list[dict]:
    """List session summaries as lightweight index entries.

    Args:
        date: Filter to sessions from this YYYY-MM month prefix or YYYY-MM-DD date.
        channel: Filter to sessions on this channel.
        log_dir: Root log directory. Defaults to ~/.skillfoundry/user_ledger/.

    Returns:
        List of dicts with keys: session_id, started_at, ended_at, channel,
        user_name, total_turns, summary.
    """
    root = Path(log_dir) if log_dir else _DEFAULT_DIR

    if date and len(date) == 7:
        month_dirs = [root / date]
    elif date and len(date) == 10:
        month_dirs = [root / date[:7]]
    else:
        month_dirs = sorted(root.glob("*"))

    results: list[dict] = []
    for month_dir in month_dirs:
        sessions_dir = month_dir / "sessions"
        if not sessions_dir.exists():
            continue
        for session_file in sorted(sessions_dir.glob("*.json")):
            with open(session_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            if channel and data.get("channel") != channel:
                continue
            if date and len(date) == 10:
                started = data.get("started_at", "")
                if not started.startswith(date):
                    continue
            results.append({
                "session_id": data.get("session_id"),
                "started_at": data.get("started_at"),
                "ended_at": data.get("ended_at"),
                "channel": data.get("channel"),
                "user_name": data.get("user_name"),
                "total_turns": data.get("total_turns", 0),
                "summary": data.get("summary"),
            })
    return results


def search(
    query: str,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    log_dir: Optional[str | Path] = None,
) -> list[MessageRecord]:
    """Simple substring search across message logs.

    Args:
        query: Substring to search for (case-insensitive).
        date_from: Earliest date to search (YYYY-MM-DD). Defaults to searching all.
        date_to: Latest date to search (YYYY-MM-DD). Defaults to searching all.
        log_dir: Root log directory. Defaults to ~/.skillfoundry/user_ledger/.

    Returns:
        List of matching MessageRecords.
    """
    root = Path(log_dir) if log_dir else _DEFAULT_DIR
    query_lower = query.lower()
    results: list[MessageRecord] = []

    for month_dir in sorted(root.glob("*")):
        if not month_dir.is_dir():
            continue
        for log_file in sorted(month_dir.glob("*.jsonl")):
            # Extract date from filename
            file_date = log_file.stem  # YYYY-MM-DD
            if date_from and file_date < date_from:
                continue
            if date_to and file_date > date_to:
                continue
            with open(log_file, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    rec = MessageRecord.from_jsonl(line)
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
