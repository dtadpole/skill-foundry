"""Core UserLedger — logs user-agent conversations to JSONL files."""

from __future__ import annotations

import json
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .record import MessageRecord, ConversationRecord

_DEFAULT_DIR = Path.home() / ".skillfoundry" / "user_ledger"


class UserLedger:
    """Thread-safe logger for user-agent conversations.

    Each message is immediately appended to a daily JSONL file.
    When the session is closed, a full ConversationRecord is written
    to a separate session summary file.

    Args:
        session_id: Unique session identifier. Auto-generated if not provided.
        channel: Platform channel (e.g. "cli", "telegram", "discord").
        user_id: Platform user ID.
        user_name: Display name.
        log_dir: Root directory for logs. Defaults to ~/.skillfoundry/user_ledger/.
            Files are organized into YYYY-MM subdirectories automatically.
    """

    def __init__(
        self,
        session_id: Optional[str] = None,
        channel: Optional[str] = None,
        user_id: Optional[str] = None,
        user_name: Optional[str] = None,
        log_dir: Optional[str | Path] = None,
    ) -> None:
        self._session_id = session_id or str(uuid.uuid4())
        self._channel = channel
        self._user_id = user_id
        self._user_name = user_name
        self._lock = threading.Lock()
        self._root_dir = Path(log_dir) if log_dir is not None else _DEFAULT_DIR

        now = datetime.now(timezone.utc)
        self._conversation = ConversationRecord(
            session_id=self._session_id,
            started_at=now.isoformat(),
            channel=self._channel,
            user_id=self._user_id,
            user_name=self._user_name,
        )

    def _month_dir(self) -> Path:
        """Return the current month's subdirectory."""
        return self._root_dir / datetime.now(timezone.utc).strftime("%Y-%m")

    def _daily_path(self) -> Path:
        """Return today's message log file path."""
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        return self._month_dir() / f"{today}.jsonl"

    def _session_path(self) -> Path:
        """Return the session summary file path."""
        return self._month_dir() / "sessions" / f"{self._session_id}.json"

    def log_message(
        self,
        role: str,
        content: str,
        sender_id: Optional[str] = None,
        sender_name: Optional[str] = None,
        attachments: Optional[list[dict]] = None,
        metadata: Optional[dict] = None,
    ) -> MessageRecord:
        """Log a single message and append it to the daily JSONL file.

        Args:
            role: Message role — "user", "assistant", or "system".
            content: Message text.
            sender_id: Platform-specific sender ID.
            sender_name: Human-readable sender name.
            attachments: List of attachment dicts [{type, name, size_bytes}].
            metadata: Extra platform-specific data.

        Returns:
            The created MessageRecord.
        """
        record = MessageRecord(
            role=role,
            content=content,
            channel=self._channel,
            sender_id=sender_id,
            sender_name=sender_name,
            attachments=attachments or [],
            metadata=metadata or {},
        )

        with self._lock:
            self._conversation.messages.append(record)
            # Count turns: a turn is a user message followed by an assistant message
            roles = [m.role for m in self._conversation.messages]
            turns = sum(
                1 for i in range(len(roles) - 1)
                if roles[i] == "user" and roles[i + 1] == "assistant"
            )
            self._conversation.total_turns = turns

            path = self._daily_path()
            path.parent.mkdir(parents=True, exist_ok=True)
            line = record.to_jsonl() + "\n"
            with open(path, "a", encoding="utf-8") as f:
                f.write(line)

        return record

    def close(self, summary: Optional[str] = None) -> ConversationRecord:
        """Close the session and write a ConversationRecord summary.

        Args:
            summary: Optional human/AI-generated summary of the conversation.

        Returns:
            The final ConversationRecord.
        """
        with self._lock:
            self._conversation.ended_at = datetime.now(timezone.utc).isoformat()
            self._conversation.summary = summary

            path = self._session_path()
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(self._conversation.to_dict(), f, ensure_ascii=False, indent=2)

        return self._conversation

    def get_session(self) -> ConversationRecord:
        """Return the current session state.

        Returns:
            A snapshot of the current ConversationRecord.
        """
        return self._conversation
