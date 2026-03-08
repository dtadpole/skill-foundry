"""ThreadManager — CRUD, persistence, and snapshot for tracked topics."""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Optional

from .models import Topic, ThreadStatus, ThreadEvent


_DEFAULT_STORAGE = Path.home() / ".blue_lantern" / "thread_tracker"


class ThreadManager:
    """Manages the lifecycle and persistence of conversation topics."""

    def __init__(self, storage_dir: Optional[str | Path] = None) -> None:
        self.storage_dir = Path(storage_dir) if storage_dir else _DEFAULT_STORAGE
        self._topics: dict[str, Topic] = {}
        self._lock = threading.Lock()
        self.load()

    # -- CRUD ------------------------------------------------------------

    def create(
        self,
        title: str,
        description: str = "",
        tags: Optional[list[str]] = None,
    ) -> Thread:
        """Create a new topic and persist it."""
        topic = Topic(title=title, description=description, tags=tags or [])
        topic.add_event("created", f"Topic created: {title}")
        self._topics[topic.topic_id] = topic
        self.save()
        return topic

    def get(self, topic_id: str) -> Optional[Thread]:
        """Return a topic by ID, or None."""
        return self._topics.get(topic_id)

    def find(self, query: str) -> list[Thread]:
        """Search topics by title, description, or tags (case-insensitive substring)."""
        q = query.lower()
        results = []
        for t in self._topics.values():
            if (
                q in t.title.lower()
                or q in t.description.lower()
                or any(q in tag.lower() for tag in t.tags)
            ):
                results.append(t)
        return results

    def list_active(self) -> list[Thread]:
        """Return all non-completed topics."""
        return [t for t in self._topics.values() if t.status != ThreadStatus.COMPLETED]

    def list_all(self) -> list[Thread]:
        """Return every topic (active + archived in memory)."""
        return list(self._topics.values())

    # -- mutations -------------------------------------------------------

    def update_status(
        self,
        topic_id: str,
        status: ThreadStatus,
        note: Optional[str] = None,
    ) -> Thread:
        """Change a topic's status."""
        topic = self._require(topic_id)
        topic.set_status(status, note=note)
        self.save()
        return topic

    def add_progress(self, topic_id: str, description: str) -> Thread:
        """Record a completed step on a topic."""
        topic = self._require(topic_id)
        topic.add_progress(description)
        self.save()
        return topic

    def add_pending(self, topic_id: str, action: str) -> Thread:
        """Add a pending action to a topic."""
        topic = self._require(topic_id)
        topic.add_pending(action)
        self.save()
        return topic

    def resolve_pending(self, topic_id: str, action: str) -> Thread:
        """Move a pending action to done."""
        topic = self._require(topic_id)
        topic.resolve_pending(action)
        self.save()
        return topic

    def set_current(self, topic_id: str, action: str) -> Thread:
        """Set the current action for a topic."""
        topic = self._require(topic_id)
        topic.current_action = action
        topic._touch()
        self.save()
        return topic

    def close(self, topic_id: str, summary: Optional[str] = None) -> Thread:
        """Mark a topic COMPLETED and archive it."""
        topic = self._require(topic_id)
        topic.set_status(ThreadStatus.COMPLETED, note=summary)
        topic.current_action = None
        self._archive(topic)
        self.save()
        return topic

    # -- snapshot --------------------------------------------------------

    def snapshot(self) -> str:
        """Compact text summary of all active topics for prompt injection."""
        active = self.list_active()
        if not active:
            return "[ACTIVE TOPICS — none]"

        lines = [f"[ACTIVE TOPICS — {len(active)} in progress]"]
        for i, t in enumerate(active, 1):
            circled = _circled_number(i)
            lines.append(
                f"{circled} {t.title} [{t.status.value}]"
                + (f" — {t.current_action}" if t.current_action else "")
            )
            if t.done:
                lines.append(f"  ✓ Done: {', '.join(t.done)}")
            if t.pending:
                lines.append(f"  ⋯ Pending: {', '.join(t.pending)}")
        return "\n".join(lines)

    # -- persistence -----------------------------------------------------

    def save(self) -> None:
        """Persist active topics to disk (thread-safe)."""
        with self._lock:
            self.storage_dir.mkdir(parents=True, exist_ok=True)
            active_path = self.storage_dir / "active.json"
            active = [
                t.to_dict()
                for t in self._topics.values()
                if t.status != ThreadStatus.COMPLETED
            ]
            active_path.write_text(
                json.dumps(active, indent=2, ensure_ascii=False)
            )

    def load(self) -> None:
        """Load topics from storage."""
        active_path = self.storage_dir / "active.json"
        if active_path.exists():
            data = json.loads(active_path.read_text())
            for d in data:
                topic = Topic.from_dict(d)
                self._topics[topic.topic_id] = topic

        # Also load archived topics into memory
        archive_dir = self.storage_dir / "archive"
        if archive_dir.exists():
            for f in archive_dir.glob("*.json"):
                data = json.loads(f.read_text())
                topic = Topic.from_dict(data)
                self._topics[topic.topic_id] = topic

    # -- internals -------------------------------------------------------

    def _require(self, topic_id: str) -> Thread:
        topic = self._topics.get(topic_id)
        if topic is None:
            raise KeyError(f"Topic not found: {topic_id}")
        return topic

    def _archive(self, topic: Thread) -> None:
        """Write a completed topic to the archive directory."""
        with self._lock:
            archive_dir = self.storage_dir / "archive"
            archive_dir.mkdir(parents=True, exist_ok=True)
            path = archive_dir / f"{topic.topic_id}.json"
            path.write_text(
                json.dumps(topic.to_dict(), indent=2, ensure_ascii=False)
            )


def _circled_number(n: int) -> str:
    """Return a circled-digit character for 1-20, fallback to (n)."""
    if 1 <= n <= 20:
        return chr(0x2460 + n - 1)  # ① ② ③ ...
    return f"({n})"
