"""Core UserLedger — logs user-agent conversations to Markdown files."""

from __future__ import annotations

import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

_DEFAULT_DIR = Path.home() / ".blue_lantern" / "user_ledger"

_ROLE_ICONS = {
    "user": "👤 User",
    "assistant": "🤖 Assistant",
    "system": "⚙️ System",
}


class UserLedger:
    """Append-only Markdown logger for user-agent conversations.

    Each session produces one .md file at:
        ~/.blue_lantern/user_ledger/YYYY-MM-DD/{session_id}.md

    The file is written incrementally — header on init, each message
    appended via log_message(), and a footer appended via close().
    Once written, lines are never modified (immutable append-only).

    Args:
        session_id: Unique session ID. Auto-generated UUID4 if not provided.
        channel: Platform channel (e.g. "bluebubbles", "telegram").
        user_id: Platform user ID.
        user_name: Display name.
        root_dir: Root directory. Defaults to ~/.blue_lantern/user_ledger/.
    """

    def __init__(
        self,
        session_id: Optional[str] = None,
        channel: Optional[str] = None,
        user_id: Optional[str] = None,
        user_name: Optional[str] = None,
        root_dir: Optional[str | Path] = None,
    ) -> None:
        self._session_id = session_id or str(uuid.uuid4())
        self._channel = channel
        self._user_id = user_id
        self._user_name = user_name
        self._lock = threading.Lock()
        self._root_dir = Path(root_dir) if root_dir is not None else _DEFAULT_DIR
        self._message_count = 0

        now = datetime.now(timezone.utc)
        self._started_at = now.isoformat()

        # Create date directory and session file
        today = now.strftime("%Y-%m-%d")
        self._date_dir = self._root_dir / today
        self._file_path = self._date_dir / f"{self._session_id}.md"
        self._date_dir.mkdir(parents=True, exist_ok=True)

        # Write session header
        header = f"# Session: {self._session_id}\n\n"
        header += "| Field | Value |\n"
        header += "|-------|-------|\n"
        header += f"| Started | {self._started_at} |\n"
        if self._channel:
            header += f"| Channel | {self._channel} |\n"
        if self._user_name or self._user_id:
            user_display = self._user_name or ""
            if self._user_id:
                user_display += f" ({self._user_id})" if user_display else self._user_id
            header += f"| User | {user_display} |\n"
        header += "\n---\n\n## Messages\n"

        with open(self._file_path, "a", encoding="utf-8") as f:
            f.write(header)

    @property
    def session_id(self) -> str:
        return self._session_id

    def log_message(
        self,
        role: str,
        content: str,
        attachments: Optional[list[dict]] = None,
    ) -> dict:
        """Append a formatted message section to the session Markdown file.

        Args:
            role: Message role — "user", "assistant", or "system".
            content: Message text.
            attachments: Optional list of attachment dicts.

        Returns:
            A dict with message metadata.
        """
        self._message_count += 1
        timestamp = datetime.now(timezone.utc).isoformat()
        role_display = _ROLE_ICONS.get(role, role)

        section = f"\n### [{timestamp}] {role_display}\n{content}\n\n---\n"

        if attachments:
            att_lines = "\n".join(
                f"- {a.get('name', 'file')} ({a.get('type', 'unknown')})"
                for a in attachments
            )
            section = f"\n### [{timestamp}] {role_display}\n{content}\n\n**Attachments:**\n{att_lines}\n\n---\n"

        with self._lock:
            with open(self._file_path, "a", encoding="utf-8") as f:
                f.write(section)

        return {
            "message_number": self._message_count,
            "role": role,
            "content": content,
            "timestamp": timestamp,
            "attachments": attachments or [],
        }

    def close(self, summary: Optional[str] = None) -> dict:
        """Append the Session End section to the Markdown file.

        Args:
            summary: Optional summary of the conversation.

        Returns:
            A dict with session end metadata.
        """
        ended_at = datetime.now(timezone.utc).isoformat()

        footer = "\n## Session End\n\n"
        footer += "| Field | Value |\n"
        footer += "|-------|-------|\n"
        footer += f"| Ended | {ended_at} |\n"
        footer += f"| Total Messages | {self._message_count} |\n"
        if summary:
            footer += f"| Summary | {summary} |\n"

        with self._lock:
            with open(self._file_path, "a", encoding="utf-8") as f:
                f.write(footer)

        return {
            "session_id": self._session_id,
            "ended_at": ended_at,
            "total_messages": self._message_count,
            "summary": summary,
        }
