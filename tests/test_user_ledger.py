"""Tests for the user_ledger tool."""

import json
import tempfile
from pathlib import Path

import pytest

from tools.user_ledger.record import MessageRecord, ConversationRecord
from tools.user_ledger.logger import UserLedger
from tools.user_ledger.reader import (
    read_messages,
    read_session,
    list_sessions,
    search,
    summarize,
)


# ---------------------------------------------------------------
# MessageRecord serialization / deserialization
# ---------------------------------------------------------------

class TestMessageRecord:
    def test_round_trip_defaults(self):
        """A default MessageRecord survives a JSONL round-trip."""
        original = MessageRecord(role="user", content="hello")
        line = original.to_jsonl()
        restored = MessageRecord.from_jsonl(line)
        assert restored.message_id == original.message_id
        assert restored.role == "user"
        assert restored.content == "hello"

    def test_round_trip_full(self):
        """A fully-populated MessageRecord survives a round-trip."""
        original = MessageRecord(
            role="assistant",
            content="Sure, I can help!",
            channel="telegram",
            sender_id="bot-1",
            sender_name="OpenClaw",
            attachments=[{"type": "image", "name": "screenshot.png", "size_bytes": 1024}],
            metadata={"reply_to": "msg-123"},
        )
        line = original.to_jsonl()
        restored = MessageRecord.from_jsonl(line)
        assert restored.role == "assistant"
        assert restored.channel == "telegram"
        assert restored.sender_name == "OpenClaw"
        assert len(restored.attachments) == 1
        assert restored.attachments[0]["type"] == "image"
        assert restored.metadata == {"reply_to": "msg-123"}

    def test_to_jsonl_is_single_line(self):
        record = MessageRecord(content="line1\nline2")
        line = record.to_jsonl()
        assert "\n" not in line

    def test_to_jsonl_is_valid_json(self):
        record = MessageRecord(role="user", content="hello")
        parsed = json.loads(record.to_jsonl())
        assert parsed["role"] == "user"
        assert parsed["content"] == "hello"

    def test_to_dict_from_dict(self):
        original = MessageRecord(role="system", content="init", channel="cli")
        d = original.to_dict()
        assert isinstance(d, dict)
        restored = MessageRecord.from_dict(d)
        assert restored.message_id == original.message_id
        assert restored.role == "system"
        assert restored.channel == "cli"


# ---------------------------------------------------------------
# ConversationRecord serialization / deserialization
# ---------------------------------------------------------------

class TestConversationRecord:
    def test_round_trip_defaults(self):
        """A default ConversationRecord survives a JSONL round-trip."""
        original = ConversationRecord()
        line = original.to_jsonl()
        restored = ConversationRecord.from_jsonl(line)
        assert restored.session_id == original.session_id
        assert restored.messages == []

    def test_round_trip_with_messages(self):
        """A ConversationRecord with messages survives a round-trip."""
        msg1 = MessageRecord(role="user", content="Hi")
        msg2 = MessageRecord(role="assistant", content="Hello!")
        original = ConversationRecord(
            channel="discord",
            user_name="Zhen",
            messages=[msg1, msg2],
            total_turns=1,
            tags=["greeting"],
            summary="Brief hello exchange",
        )
        line = original.to_jsonl()
        restored = ConversationRecord.from_jsonl(line)
        assert restored.channel == "discord"
        assert restored.user_name == "Zhen"
        assert len(restored.messages) == 2
        assert restored.messages[0].role == "user"
        assert restored.messages[1].content == "Hello!"
        assert restored.total_turns == 1
        assert restored.tags == ["greeting"]
        assert restored.summary == "Brief hello exchange"

    def test_to_dict_from_dict(self):
        msg = MessageRecord(role="user", content="test")
        original = ConversationRecord(
            channel="cli",
            messages=[msg],
            total_turns=0,
        )
        d = original.to_dict()
        assert isinstance(d, dict)
        assert isinstance(d["messages"], list)
        restored = ConversationRecord.from_dict(d)
        assert restored.session_id == original.session_id
        assert len(restored.messages) == 1
        assert restored.messages[0].content == "test"


# ---------------------------------------------------------------
# UserLedger — message logging
# ---------------------------------------------------------------

class TestUserLedger:
    def test_log_message_creates_file(self, tmp_path):
        """Logging a message creates a JSONL file with the record."""
        ledger = UserLedger(channel="cli", log_dir=tmp_path)
        rec = ledger.log_message("user", "hello there")

        assert rec.role == "user"
        assert rec.content == "hello there"
        assert rec.channel == "cli"

        files = list(tmp_path.glob("**/*.jsonl"))
        assert len(files) == 1
        content = files[0].read_text()
        lines = [l for l in content.strip().split("\n") if l]
        assert len(lines) == 1
        restored = MessageRecord.from_jsonl(lines[0])
        assert restored.content == "hello there"

    def test_log_message_appends(self, tmp_path):
        """Multiple messages append to the same daily file."""
        ledger = UserLedger(log_dir=tmp_path)
        ledger.log_message("user", "msg1")
        ledger.log_message("assistant", "msg2")
        ledger.log_message("user", "msg3")

        files = list(tmp_path.glob("**/*.jsonl"))
        lines = [l for l in files[0].read_text().strip().split("\n") if l]
        assert len(lines) == 3

    def test_log_message_with_attachments(self, tmp_path):
        """Attachments are persisted correctly."""
        ledger = UserLedger(log_dir=tmp_path)
        rec = ledger.log_message(
            "user", "see this image",
            attachments=[{"type": "image", "name": "pic.png", "size_bytes": 2048}],
        )
        assert len(rec.attachments) == 1
        assert rec.attachments[0]["name"] == "pic.png"

    def test_session_tracking(self, tmp_path):
        """get_session returns current conversation state."""
        ledger = UserLedger(channel="telegram", user_name="Zhen", log_dir=tmp_path)
        ledger.log_message("user", "hi", sender_name="Zhen")
        ledger.log_message("assistant", "hello!")

        session = ledger.get_session()
        assert session.channel == "telegram"
        assert session.user_name == "Zhen"
        assert len(session.messages) == 2
        assert session.total_turns == 1

    def test_turn_counting(self, tmp_path):
        """total_turns counts user->assistant pairs."""
        ledger = UserLedger(log_dir=tmp_path)
        ledger.log_message("user", "q1")
        ledger.log_message("assistant", "a1")
        ledger.log_message("user", "q2")
        ledger.log_message("assistant", "a2")
        ledger.log_message("user", "q3")  # no response yet

        session = ledger.get_session()
        assert session.total_turns == 2

    def test_close_writes_session(self, tmp_path):
        """close() marks session ended and writes a session summary file."""
        ledger = UserLedger(log_dir=tmp_path)
        ledger.log_message("user", "help me")
        ledger.log_message("assistant", "sure!")

        conversation = ledger.close(summary="Quick help session")

        assert conversation.ended_at is not None
        assert conversation.summary == "Quick help session"

        # Session file should exist
        session_files = list(tmp_path.glob("**/sessions/*.json"))
        assert len(session_files) == 1

        with open(session_files[0], "r") as f:
            data = json.load(f)
        assert data["summary"] == "Quick help session"
        assert len(data["messages"]) == 2

    def test_close_produces_correct_record(self, tmp_path):
        """close() returns a ConversationRecord with all fields set."""
        ledger = UserLedger(
            channel="discord", user_id="u123", user_name="Zhen", log_dir=tmp_path,
        )
        ledger.log_message("user", "hey")
        ledger.log_message("assistant", "hi!")
        conv = ledger.close(summary="Greeting")

        assert conv.channel == "discord"
        assert conv.user_id == "u123"
        assert conv.user_name == "Zhen"
        assert conv.total_turns == 1
        assert conv.ended_at is not None
        assert conv.summary == "Greeting"
        assert len(conv.messages) == 2


# ---------------------------------------------------------------
# Reader functions
# ---------------------------------------------------------------

def _setup_ledger(tmp_path: Path) -> UserLedger:
    """Helper: create a ledger, log some messages, and close it."""
    ledger = UserLedger(channel="cli", user_name="Zhen", log_dir=tmp_path)
    ledger.log_message("user", "What is Python?", sender_name="Zhen")
    ledger.log_message("assistant", "Python is a programming language.")
    ledger.log_message("user", "How do I install it?", sender_name="Zhen")
    ledger.log_message("assistant", "Use your package manager or python.org.")
    ledger.close(summary="Python intro questions")
    return ledger


class TestReader:
    def test_read_messages(self, tmp_path):
        """read_messages returns all messages from a daily file."""
        _setup_ledger(tmp_path)
        messages = read_messages(log_dir=tmp_path)
        assert len(messages) == 4
        assert messages[0].role == "user"
        assert "Python" in messages[0].content

    def test_read_messages_filter_channel(self, tmp_path):
        """read_messages can filter by channel."""
        ledger = UserLedger(channel="telegram", log_dir=tmp_path)
        ledger.log_message("user", "tg message")
        ledger.close()

        ledger2 = UserLedger(channel="discord", log_dir=tmp_path)
        ledger2.log_message("user", "dc message")
        ledger2.close()

        msgs = read_messages(channel="telegram", log_dir=tmp_path)
        assert len(msgs) == 1
        assert msgs[0].content == "tg message"

    def test_read_session(self, tmp_path):
        """read_session loads a full session by ID."""
        ledger = _setup_ledger(tmp_path)
        session_id = ledger.get_session().session_id

        session = read_session(session_id, log_dir=tmp_path)
        assert session is not None
        assert session.session_id == session_id
        assert len(session.messages) == 4
        assert session.summary == "Python intro questions"

    def test_read_session_not_found(self, tmp_path):
        """read_session returns None for unknown session."""
        result = read_session("nonexistent-id", log_dir=tmp_path)
        assert result is None

    def test_list_sessions(self, tmp_path):
        """list_sessions returns lightweight session index."""
        _setup_ledger(tmp_path)
        sessions = list_sessions(log_dir=tmp_path)
        assert len(sessions) == 1
        assert sessions[0]["user_name"] == "Zhen"
        assert sessions[0]["summary"] == "Python intro questions"

    def test_list_sessions_filter_channel(self, tmp_path):
        """list_sessions can filter by channel."""
        _setup_ledger(tmp_path)  # channel="cli"
        sessions = list_sessions(channel="telegram", log_dir=tmp_path)
        assert len(sessions) == 0
        sessions = list_sessions(channel="cli", log_dir=tmp_path)
        assert len(sessions) == 1

    def test_search(self, tmp_path):
        """search finds messages containing a substring."""
        _setup_ledger(tmp_path)
        results = search("Python", log_dir=tmp_path)
        assert len(results) >= 2  # "What is Python?" and "Python is a..."

    def test_search_case_insensitive(self, tmp_path):
        """search is case-insensitive."""
        _setup_ledger(tmp_path)
        results = search("python", log_dir=tmp_path)
        assert len(results) >= 2

    def test_search_no_match(self, tmp_path):
        """search returns empty list when nothing matches."""
        _setup_ledger(tmp_path)
        results = search("xyznonexistent", log_dir=tmp_path)
        assert len(results) == 0

    def test_summarize(self):
        """summarize produces correct statistics."""
        messages = [
            MessageRecord(role="user", content="short", channel="cli"),
            MessageRecord(role="assistant", content="a longer reply here", channel="cli"),
            MessageRecord(role="user", content="ok thanks", channel="telegram"),
        ]
        stats = summarize(messages)
        assert stats["total_messages"] == 3
        assert stats["by_role"] == {"user": 2, "assistant": 1}
        assert stats["by_channel"] == {"cli": 2, "telegram": 1}
        assert stats["avg_length"] > 0

    def test_summarize_empty(self):
        """summarize handles empty input."""
        stats = summarize([])
        assert stats["total_messages"] == 0
        assert stats["by_role"] == {}
        assert stats["by_channel"] == {}
        assert stats["avg_length"] == 0.0
