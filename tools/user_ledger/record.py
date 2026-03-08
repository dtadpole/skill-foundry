"""Dataclasses for user-agent conversation records."""

from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict

from tools.ulid_utils import new_ulid
from datetime import datetime, timezone
from typing import Optional


@dataclass
class MessageRecord:
    """A single message in a user-agent conversation."""

    message_id: str = field(default_factory=new_ulid)
    role: str = ""  # "user" | "assistant" | "system"
    content: str = ""
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    channel: Optional[str] = None  # "bluebubbles" | "telegram" | "discord" | "cli"
    sender_id: Optional[str] = None
    sender_name: Optional[str] = None
    attachments: list[dict] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)

    def to_jsonl(self) -> str:
        """Serialize to a single JSON line."""
        return json.dumps(asdict(self), ensure_ascii=False, separators=(",", ":"))

    @classmethod
    def from_jsonl(cls, line: str) -> MessageRecord:
        """Deserialize from a single JSON line."""
        data = json.loads(line.strip())
        return cls(**data)

    def to_dict(self) -> dict:
        """Convert to plain dictionary."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> MessageRecord:
        """Create from a dictionary."""
        return cls(**data)


@dataclass
class ConversationRecord:
    """A full conversation session between user and agent."""

    session_id: str = field(default_factory=new_ulid)
    started_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    ended_at: Optional[str] = None
    channel: Optional[str] = None
    user_id: Optional[str] = None
    user_name: Optional[str] = None
    messages: list[MessageRecord] = field(default_factory=list)
    total_turns: int = 0
    tags: list[str] = field(default_factory=list)
    summary: Optional[str] = None

    def to_jsonl(self) -> str:
        """Serialize to a single JSON line."""
        d = asdict(self)
        return json.dumps(d, ensure_ascii=False, separators=(",", ":"))

    @classmethod
    def from_jsonl(cls, line: str) -> ConversationRecord:
        """Deserialize from a single JSON line."""
        data = json.loads(line.strip())
        messages = [MessageRecord(**m) for m in data.pop("messages", [])]
        return cls(messages=messages, **data)

    def to_dict(self) -> dict:
        """Convert to plain dictionary."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> ConversationRecord:
        """Create from a dictionary."""
        messages = [MessageRecord(**m) for m in data.pop("messages", [])]
        return cls(messages=messages, **data)
