"""Tests for the topics tool."""

import json
from pathlib import Path

import pytest

from tools.thread_tracker.models import Thread, ThreadStatus, ThreadEvent
from tools.thread_tracker.manager import ThreadManager


# ---------------------------------------------------------------
# ThreadEvent
# ---------------------------------------------------------------

class TestThreadEvent:
    def test_defaults(self):
        e = ThreadEvent()
        assert e.event_type == "note"
        assert e.actor == "assistant"
        assert e.metadata == {}
        assert len(e.event_id) == 26  # ULID

    def test_round_trip(self):
        e = ThreadEvent(event_type="progress", description="did stuff", actor="user")
        d = e.to_dict()
        restored = ThreadEvent.from_dict(d)
        assert restored.event_type == "progress"
        assert restored.description == "did stuff"
        assert restored.actor == "user"
        assert restored.event_id == e.event_id


# ---------------------------------------------------------------
# Thread creation & serialization
# ---------------------------------------------------------------

class TestThread:
    def test_creation_defaults(self):
        t = Thread(title="Test")
        assert t.title == "Test"
        assert t.status == ThreadStatus.PENDING
        assert t.done == []
        assert t.pending == []
        assert t.events == []
        assert t.current_action is None

    def test_round_trip(self):
        t = Thread(title="Round-trip", description="testing", tags=["a", "b"])
        t.add_event("note", "hello")
        d = t.to_dict()
        restored = Thread.from_dict(d)
        assert restored.topic_id == t.topic_id
        assert restored.title == "Round-trip"
        assert restored.description == "testing"
        assert restored.tags == ["a", "b"]
        assert restored.status == ThreadStatus.PENDING
        assert len(restored.events) == 1
        assert restored.events[0].description == "hello"

    def test_round_trip_all_statuses(self):
        for status in ThreadStatus:
            t = Thread(title=f"test-{status.value}", status=status)
            d = t.to_dict()
            restored = Thread.from_dict(d)
            assert restored.status == status


# ---------------------------------------------------------------
# Status transitions
# ---------------------------------------------------------------

class TestStatusTransitions:
    def test_set_status(self):
        t = Thread(title="S")
        t.set_status(ThreadStatus.IN_PROGRESS, note="starting")
        assert t.status == ThreadStatus.IN_PROGRESS
        assert len(t.events) == 1
        assert "pending → in_progress" in t.events[0].description
        assert "starting" in t.events[0].description

    def test_set_status_without_note(self):
        t = Thread(title="S")
        t.set_status(ThreadStatus.BLOCKED)
        assert t.status == ThreadStatus.BLOCKED
        assert len(t.events) == 1

    def test_multiple_transitions(self):
        t = Thread(title="S")
        t.set_status(ThreadStatus.IN_PROGRESS)
        t.set_status(ThreadStatus.AWAITING_USER)
        t.set_status(ThreadStatus.AWAITING_AGENT)
        t.set_status(ThreadStatus.COMPLETED)
        assert t.status == ThreadStatus.COMPLETED
        assert len(t.events) == 4


# ---------------------------------------------------------------
# Progress / pending
# ---------------------------------------------------------------

class TestProgress:
    def test_add_progress(self):
        t = Thread(title="P")
        t.add_progress("step 1")
        t.add_progress("step 2")
        assert t.done == ["step 1", "step 2"]
        assert len(t.events) == 2
        assert t.events[0].event_type == "progress"

    def test_add_pending(self):
        t = Thread(title="P")
        t.add_pending("task A")
        t.add_pending("task B")
        assert t.pending == ["task A", "task B"]
        assert len(t.events) == 2
        assert t.events[0].event_type == "pending_added"

    def test_resolve_pending(self):
        t = Thread(title="P")
        t.add_pending("task A")
        t.add_pending("task B")
        t.resolve_pending("task A")
        assert t.pending == ["task B"]
        assert t.done == ["task A"]
        assert t.events[-1].event_type == "pending_resolved"

    def test_resolve_pending_not_in_list(self):
        """Resolving something not in pending still adds to done."""
        t = Thread(title="P")
        t.resolve_pending("unknown")
        assert t.done == ["unknown"]
        assert t.pending == []


# ---------------------------------------------------------------
# Thread.summary()
# ---------------------------------------------------------------

class TestSummary:
    def test_summary_with_action(self):
        t = Thread(title="ModelLedger", current_action="renaming files")
        t.set_status(ThreadStatus.IN_PROGRESS)
        s = t.summary()
        assert "ModelLedger" in s
        assert "in_progress" in s
        assert "renaming files" in s

    def test_summary_without_action(self):
        t = Thread(title="Docs")
        s = t.summary()
        assert "Docs" in s
        assert "pending" in s


# ---------------------------------------------------------------
# ThreadManager CRUD
# ---------------------------------------------------------------

class TestThreadManager:
    def test_create(self, tmp_path):
        tm = ThreadManager(storage_dir=tmp_path)
        topic = tm.create("Test Thread", description="desc", tags=["code"])
        assert topic.title == "Test Thread"
        assert topic.description == "desc"
        assert topic.tags == ["code"]
        assert len(topic.events) == 1
        assert topic.events[0].event_type == "created"

    def test_get(self, tmp_path):
        tm = ThreadManager(storage_dir=tmp_path)
        topic = tm.create("A")
        fetched = tm.get(topic.topic_id)
        assert fetched is topic

    def test_get_missing(self, tmp_path):
        tm = ThreadManager(storage_dir=tmp_path)
        assert tm.get("nonexistent") is None

    def test_find_by_title(self, tmp_path):
        tm = ThreadManager(storage_dir=tmp_path)
        tm.create("ModelLedger", tags=["coding"])
        tm.create("UserLedger", tags=["coding"])
        tm.create("README update", tags=["docs"])
        results = tm.find("ledger")
        assert len(results) == 2

    def test_find_by_tag(self, tmp_path):
        tm = ThreadManager(storage_dir=tmp_path)
        tm.create("A", tags=["coding"])
        tm.create("B", tags=["docs"])
        results = tm.find("coding")
        assert len(results) == 1
        assert results[0].title == "A"

    def test_find_by_description(self, tmp_path):
        tm = ThreadManager(storage_dir=tmp_path)
        tm.create("A", description="building the audit logger")
        results = tm.find("audit")
        assert len(results) == 1

    def test_find_case_insensitive(self, tmp_path):
        tm = ThreadManager(storage_dir=tmp_path)
        tm.create("ModelLedger")
        assert len(tm.find("MODELLEDGER")) == 1
        assert len(tm.find("modelledger")) == 1

    def test_list_active(self, tmp_path):
        tm = ThreadManager(storage_dir=tmp_path)
        t1 = tm.create("Active")
        t2 = tm.create("Done")
        tm.close(t2.topic_id)
        active = tm.list_active()
        assert len(active) == 1
        assert active[0].topic_id == t1.topic_id

    def test_list_all(self, tmp_path):
        tm = ThreadManager(storage_dir=tmp_path)
        tm.create("A")
        tm.create("B")
        assert len(tm.list_all()) == 2

    def test_update_status(self, tmp_path):
        tm = ThreadManager(storage_dir=tmp_path)
        topic = tm.create("S")
        tm.update_status(topic.topic_id, ThreadStatus.IN_PROGRESS, note="go")
        assert topic.status == ThreadStatus.IN_PROGRESS

    def test_add_progress(self, tmp_path):
        tm = ThreadManager(storage_dir=tmp_path)
        topic = tm.create("P")
        tm.add_progress(topic.topic_id, "step 1")
        assert topic.done == ["step 1"]

    def test_add_pending(self, tmp_path):
        tm = ThreadManager(storage_dir=tmp_path)
        topic = tm.create("P")
        tm.add_pending(topic.topic_id, "task A")
        assert topic.pending == ["task A"]

    def test_resolve_pending(self, tmp_path):
        tm = ThreadManager(storage_dir=tmp_path)
        topic = tm.create("P")
        tm.add_pending(topic.topic_id, "task A")
        tm.resolve_pending(topic.topic_id, "task A")
        assert topic.pending == []
        assert "task A" in topic.done

    def test_set_current(self, tmp_path):
        tm = ThreadManager(storage_dir=tmp_path)
        topic = tm.create("C")
        tm.set_current(topic.topic_id, "working on it")
        assert topic.current_action == "working on it"

    def test_close(self, tmp_path):
        tm = ThreadManager(storage_dir=tmp_path)
        topic = tm.create("X")
        tm.close(topic.topic_id, summary="all done")
        assert topic.status == ThreadStatus.COMPLETED
        assert topic.current_action is None
        # Archive file exists
        archive = tmp_path / "archive" / f"{topic.topic_id}.json"
        assert archive.exists()

    def test_require_raises(self, tmp_path):
        tm = ThreadManager(storage_dir=tmp_path)
        with pytest.raises(KeyError):
            tm.update_status("bad-id", ThreadStatus.IN_PROGRESS)


# ---------------------------------------------------------------
# Snapshot output
# ---------------------------------------------------------------

class TestSnapshot:
    def test_snapshot_empty(self, tmp_path):
        tm = ThreadManager(storage_dir=tmp_path)
        assert "none" in tm.snapshot()

    def test_snapshot_format(self, tmp_path):
        tm = ThreadManager(storage_dir=tmp_path)
        t1 = tm.create("ModelLedger")
        tm.update_status(t1.topic_id, ThreadStatus.IN_PROGRESS)
        tm.set_current(t1.topic_id, "renaming files")
        tm.add_progress(t1.topic_id, "initial build")
        tm.add_pending(t1.topic_id, "run tests")

        t2 = tm.create("UserLedger")
        tm.update_status(t2.topic_id, ThreadStatus.AWAITING_VERIFICATION)
        tm.add_progress(t2.topic_id, "full build")
        tm.add_progress(t2.topic_id, "all tests pass")

        snap = tm.snapshot()
        assert "ACTIVE TOPICS" in snap
        assert "2 in progress" in snap
        assert "ModelLedger" in snap
        assert "renaming files" in snap
        assert "✓ Done:" in snap
        assert "initial build" in snap
        assert "⋯ Pending:" in snap
        assert "run tests" in snap
        assert "UserLedger" in snap
        assert "awaiting_verification" in snap

    def test_snapshot_circled_numbers(self, tmp_path):
        tm = ThreadManager(storage_dir=tmp_path)
        tm.create("A")
        tm.create("B")
        tm.create("C")
        snap = tm.snapshot()
        assert "①" in snap
        assert "②" in snap
        assert "③" in snap


# ---------------------------------------------------------------
# Save / load persistence
# ---------------------------------------------------------------

class TestPersistence:
    def test_save_creates_file(self, tmp_path):
        tm = ThreadManager(storage_dir=tmp_path)
        tm.create("Persist")
        assert (tmp_path / "active.json").exists()

    def test_save_load_round_trip(self, tmp_path):
        tm = ThreadManager(storage_dir=tmp_path)
        t = tm.create("Round-trip", description="testing persistence", tags=["x"])
        tm.update_status(t.topic_id, ThreadStatus.IN_PROGRESS, note="go")
        tm.add_progress(t.topic_id, "step 1")
        tm.add_pending(t.topic_id, "step 2")
        tm.set_current(t.topic_id, "working")

        # Load into a fresh manager
        tm2 = ThreadManager(storage_dir=tmp_path)
        loaded = tm2.get(t.topic_id)
        assert loaded is not None
        assert loaded.title == "Round-trip"
        assert loaded.description == "testing persistence"
        assert loaded.tags == ["x"]
        assert loaded.status == ThreadStatus.IN_PROGRESS
        assert loaded.done == ["step 1"]
        assert loaded.pending == ["step 2"]
        assert loaded.current_action == "working"
        assert len(loaded.events) == len(t.events)

    def test_archive_and_reload(self, tmp_path):
        tm = ThreadManager(storage_dir=tmp_path)
        t = tm.create("Archive")
        tid = t.topic_id
        tm.close(tid, summary="done")

        # Fresh manager should load the archived topic
        tm2 = ThreadManager(storage_dir=tmp_path)
        loaded = tm2.get(tid)
        assert loaded is not None
        assert loaded.status == ThreadStatus.COMPLETED

    def test_active_json_excludes_completed(self, tmp_path):
        tm = ThreadManager(storage_dir=tmp_path)
        t1 = tm.create("Active")
        t2 = tm.create("Done")
        tm.close(t2.topic_id)

        data = json.loads((tmp_path / "active.json").read_text())
        ids = [d["topic_id"] for d in data]
        assert t1.topic_id in ids
        assert t2.topic_id not in ids
