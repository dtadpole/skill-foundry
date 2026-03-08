"""Topic tracking models — status, events, and topic dataclasses."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional


class ThreadStatus(Enum):
    """Lifecycle states for a tracked topic."""

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    AWAITING_USER = "awaiting_user"
    AWAITING_AGENT = "awaiting_agent"
    AWAITING_VERIFICATION = "awaiting_verification"
    PAUSED = "paused"
    BLOCKED = "blocked"
    COMPLETED = "completed"


# Short display labels for snapshot output
_STATUS_LABEL = {
    ThreadStatus.PENDING: "pending",
    ThreadStatus.IN_PROGRESS: "in_progress",
    ThreadStatus.AWAITING_USER: "awaiting_user",
    ThreadStatus.AWAITING_AGENT: "awaiting_agent",
    ThreadStatus.AWAITING_VERIFICATION: "awaiting_verification",
    ThreadStatus.PAUSED: "paused",
    ThreadStatus.BLOCKED: "blocked",
    ThreadStatus.COMPLETED: "completed",
}


@dataclass
class ThreadEvent:
    """A single immutable entry in a topic's event log."""

    event_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    event_type: str = "note"  # created | status_changed | progress | pending_added | pending_resolved | blocked | completed | note
    description: str = ""
    actor: str = "assistant"  # "user" | "assistant"
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "event_id": self.event_id,
            "timestamp": self.timestamp,
            "event_type": self.event_type,
            "description": self.description,
            "actor": self.actor,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, d: dict) -> ThreadEvent:
        return cls(**d)


@dataclass
class Thread:
    """A tracked topic with status, progress, and an append-only event log."""

    topic_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    title: str = ""
    description: str = ""
    status: ThreadStatus = ThreadStatus.PENDING
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    updated_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    tags: list[str] = field(default_factory=list)
    original_request: Optional[str] = None   # user's exact words when topic was created
    current_action: Optional[str] = None
    done: list[str] = field(default_factory=list)
    pending: list[str] = field(default_factory=list)
    tool_calls: list[dict] = field(default_factory=list)  # all tool calls across this topic
    events: list[ThreadEvent] = field(default_factory=list)

    # -- helpers ---------------------------------------------------------

    def _touch(self) -> None:
        self.updated_at = datetime.now(timezone.utc).isoformat()

    def add_event(
        self,
        event_type: str,
        description: str,
        actor: str = "assistant",
        metadata: Optional[dict] = None,
    ) -> ThreadEvent:
        """Append a new event to the log and return it."""
        event = ThreadEvent(
            event_type=event_type,
            description=description,
            actor=actor,
            metadata=metadata or {},
        )
        self.events.append(event)
        self._touch()
        return event

    def set_status(
        self,
        status: ThreadStatus,
        note: Optional[str] = None,
        actor: str = "assistant",
    ) -> None:
        """Transition to a new status, logging the change."""
        old = self.status
        self.status = status
        desc = f"{old.value} → {status.value}"
        if note:
            desc += f": {note}"
        self.add_event("status_changed", desc, actor=actor)

    def add_progress(self, description: str) -> None:
        """Record a completed step."""
        self.done.append(description)
        self.add_event("progress", description)

    def add_pending(self, action: str) -> None:
        """Add an action to the pending list."""
        self.pending.append(action)
        self.add_event("pending_added", action)

    def log_tool_call(self, tool_name: str, arguments: dict = None, result: str = None) -> None:
        """Record a tool call made during this topic."""
        entry = {"tool": tool_name, "timestamp": datetime.now(timezone.utc).isoformat()}
        if arguments:
            entry["arguments"] = arguments
        if result:
            entry["result"] = result
        self.tool_calls.append(entry)
        self.add_event("tool_called", f"Called tool: {tool_name}", metadata={"tool": tool_name})

    def resolve_pending(self, action: str) -> None:
        """Move an action from pending to done."""
        if action in self.pending:
            self.pending.remove(action)
        self.done.append(action)
        self.add_event("pending_resolved", action)

    # -- serialization ---------------------------------------------------

    def to_dict(self) -> dict:
        return {
            "topic_id": self.topic_id,
            "title": self.title,
            "description": self.description,
            "status": self.status.value,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "tags": self.tags,
            "original_request": self.original_request,
            "current_action": self.current_action,
            "done": self.done,
            "pending": self.pending,
            "tool_calls": self.tool_calls,
            "events": [e.to_dict() for e in self.events],
        }

    @classmethod
    def from_dict(cls, d: dict) -> Thread:
        return cls(
            topic_id=d["topic_id"],
            title=d["title"],
            description=d.get("description", ""),
            status=ThreadStatus(d["status"]),
            created_at=d["created_at"],
            updated_at=d["updated_at"],
            tags=d.get("tags", []),
            original_request=d.get("original_request"),
            current_action=d.get("current_action"),
            done=d.get("done", []),
            pending=d.get("pending", []),
            tool_calls=d.get("tool_calls", []),
            events=[ThreadEvent.from_dict(e) for e in d.get("events", [])],
        )

    def summary(self) -> str:
        """One-line summary: '① Title [status] — currently: doing X'."""
        parts = [f"{self.title} [{self.status.value}]"]
        if self.current_action:
            parts.append(f"— {self.current_action}")
        return " ".join(parts)

# Backward compatibility alias
Topic = Thread
