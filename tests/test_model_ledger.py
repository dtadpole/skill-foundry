"""Tests for the model_ledger tool."""

import json
import os
import tempfile
from pathlib import Path

import pytest

from tools.model_ledger.record import ModelLedgerRecord
from tools.model_ledger.pricing import estimate_cost, PRICING
from tools.model_ledger.reader import read_log, filter_records, summarize
from tools.model_ledger.logger import ModelLedger


# ---------------------------------------------------------------
# ModelLedgerRecord serialization / deserialization
# ---------------------------------------------------------------

class TestModelLedgerRecord:
    def test_round_trip_defaults(self):
        """A default record survives a JSONL round-trip."""
        original = ModelLedgerRecord()
        line = original.to_jsonl()
        restored = ModelLedgerRecord.from_jsonl(line)
        assert restored.request_id == original.request_id
        assert restored.status == "success"

    def test_round_trip_full(self):
        """A fully-populated record survives a JSONL round-trip."""
        original = ModelLedgerRecord(
            session_id="sess-1",
            caller="test-script",
            latency_ms=123.45,
            provider="openai",
            model="gpt-4o",
            temperature=0.7,
            max_tokens=1024,
            top_p=0.9,
            extra_params={"seed": 42},
            system_prompt="You are helpful.",
            messages=[
                {"role": "user", "content": "Hi"},
                {"role": "assistant", "content": "Hello!"},
            ],
            response="Hello!",
            tool_calls=[{"name": "get_weather", "arguments": "{}", "result": "sunny"}],
            prompt_tokens=100,
            completion_tokens=50,
            total_tokens=150,
            cost_usd=0.001,
            status="success",
        )
        line = original.to_jsonl()
        restored = ModelLedgerRecord.from_jsonl(line)

        assert restored.session_id == "sess-1"
        assert restored.model == "gpt-4o"
        assert restored.temperature == 0.7
        assert restored.messages == original.messages
        assert restored.tool_calls == original.tool_calls
        assert restored.cost_usd == 0.001
        assert restored.extra_params == {"seed": 42}

    def test_to_jsonl_is_single_line(self):
        record = ModelLedgerRecord(response="line1\nline2")
        line = record.to_jsonl()
        assert "\n" not in line

    def test_to_jsonl_is_valid_json(self):
        record = ModelLedgerRecord(model="gpt-4o", response="hello")
        parsed = json.loads(record.to_jsonl())
        assert parsed["model"] == "gpt-4o"
        assert parsed["response"] == "hello"

    def test_error_record(self):
        record = ModelLedgerRecord(
            status="error",
            error_type="APIError",
            error_message="rate limited",
        )
        restored = ModelLedgerRecord.from_jsonl(record.to_jsonl())
        assert restored.status == "error"
        assert restored.error_type == "APIError"
        assert restored.error_message == "rate limited"


# ---------------------------------------------------------------
# Pricing
# ---------------------------------------------------------------

class TestPricing:
    def test_known_model(self):
        cost = estimate_cost("gpt-4o", prompt_tokens=1_000_000, completion_tokens=0)
        assert cost == 2.50

    def test_output_tokens(self):
        cost = estimate_cost("gpt-4o", prompt_tokens=0, completion_tokens=1_000_000)
        assert cost == 10.00

    def test_mixed_tokens(self):
        cost = estimate_cost("gpt-4o", prompt_tokens=500_000, completion_tokens=500_000)
        assert cost == pytest.approx(1.25 + 5.0)

    def test_unknown_model(self):
        assert estimate_cost("unknown-model", 100, 100) is None

    def test_all_models_have_two_prices(self):
        for model, prices in PRICING.items():
            assert len(prices) == 2, f"{model} should have (input, output) prices"
            assert prices[0] >= 0
            assert prices[1] >= 0

    def test_small_token_counts(self):
        cost = estimate_cost("gpt-4o", prompt_tokens=100, completion_tokens=50)
        assert cost is not None
        assert cost > 0
        assert cost < 0.01


# ---------------------------------------------------------------
# Filter & Summarize
# ---------------------------------------------------------------

def _make_records() -> list[ModelLedgerRecord]:
    return [
        ModelLedgerRecord(
            provider="openai", model="gpt-4o", status="success",
            latency_ms=100, prompt_tokens=500, completion_tokens=200,
            total_tokens=700, cost_usd=0.003,
            timestamp="2026-03-07T10:00:00+00:00",
        ),
        ModelLedgerRecord(
            provider="openai", model="gpt-4o-mini", status="success",
            latency_ms=50, prompt_tokens=200, completion_tokens=100,
            total_tokens=300, cost_usd=0.0001,
            timestamp="2026-03-07T11:00:00+00:00",
        ),
        ModelLedgerRecord(
            provider="anthropic", model="claude-sonnet-4-6", status="error",
            latency_ms=200, error_type="APIError", error_message="timeout",
            timestamp="2026-03-07T12:00:00+00:00",
        ),
    ]


class TestFilter:
    def test_filter_by_provider(self):
        records = _make_records()
        result = filter_records(records, provider="openai")
        assert len(result) == 2

    def test_filter_by_model(self):
        records = _make_records()
        result = filter_records(records, model="gpt-4o")
        assert len(result) == 1
        assert result[0].model == "gpt-4o"

    def test_filter_by_status(self):
        records = _make_records()
        result = filter_records(records, status="error")
        assert len(result) == 1

    def test_filter_by_since(self):
        records = _make_records()
        result = filter_records(records, since="2026-03-07T11:00:00+00:00")
        assert len(result) == 2

    def test_filter_combined(self):
        records = _make_records()
        result = filter_records(records, provider="openai", status="success")
        assert len(result) == 2

    def test_filter_no_match(self):
        records = _make_records()
        result = filter_records(records, provider="google")
        assert len(result) == 0


class TestSummarize:
    def test_summarize(self):
        records = _make_records()
        s = summarize(records)
        assert s["total_calls"] == 3
        assert s["total_prompt_tokens"] == 700
        assert s["total_completion_tokens"] == 300
        assert s["total_tokens"] == 1000
        assert s["total_cost_usd"] == pytest.approx(0.0031)
        assert s["avg_latency_ms"] == pytest.approx(116.67, rel=0.01)
        assert s["error_rate"] == pytest.approx(1 / 3, rel=0.01)

    def test_summarize_empty(self):
        s = summarize([])
        assert s["total_calls"] == 0
        assert s["total_cost_usd"] == 0.0
        assert s["avg_latency_ms"] == 0.0
        assert s["error_rate"] == 0.0


# ---------------------------------------------------------------
# ModelLedger — Markdown writes
# ---------------------------------------------------------------

class TestModelLedger:
    def test_creates_md_file(self, tmp_path):
        """Logger creates a .md file with session header."""
        logger = ModelLedger(
            root_dir=tmp_path, session_id="s1",
            model="gpt-4o", provider="openai",
        )
        logger.log_turn(
            messages=[{"role": "user", "content": "hello"}],
            response="hi there",
        )

        files = list(tmp_path.glob("**/*.md"))
        assert len(files) == 1
        content = files[0].read_text()
        assert "# ModelLedger Session" in content
        assert "gpt-4o" in content
        assert "hello" in content
        assert "hi there" in content

    def test_appends_turns(self, tmp_path):
        """Multiple log_turn calls append turn sections."""
        logger = ModelLedger(root_dir=tmp_path)
        logger.log_turn(
            messages=[{"role": "user", "content": "q1"}],
            response="a1",
        )
        logger.log_turn(
            messages=[{"role": "user", "content": "q2"}],
            response="a2",
        )

        content = logger.file_path.read_text()
        assert "## Turn 1" in content
        assert "## Turn 2" in content
        assert "q1" in content
        assert "a2" in content

    def test_system_message_blockquoted(self, tmp_path):
        """System messages are rendered as blockquotes."""
        logger = ModelLedger(root_dir=tmp_path)
        logger.log_turn(
            messages=[
                {"role": "system", "content": "You are helpful."},
                {"role": "user", "content": "hi"},
            ],
            response="hello!",
        )

        content = logger.file_path.read_text()
        assert "### 🔧 System" in content
        assert "> You are helpful." in content

    def test_tool_calls(self, tmp_path):
        """Tool calls and responses are rendered correctly."""
        logger = ModelLedger(root_dir=tmp_path)
        logger.log_turn(
            messages=[{"role": "user", "content": "run ls"}],
            tool_calls=[{
                "name": "exec",
                "input": {"command": "ls"},
                "output": "file1.py\nfile2.py",
            }],
            response="Here are the files.",
        )

        content = logger.file_path.read_text()
        assert "🛠️ Tool Call: `exec`" in content
        assert "↩️ Tool Response: `exec`" in content
        assert "🤖 Assistant (continued)" in content
        assert "Here are the files." in content

    def test_tool_error(self, tmp_path):
        """Tool errors are rendered with error icon."""
        logger = ModelLedger(root_dir=tmp_path)
        logger.log_turn(
            messages=[{"role": "user", "content": "run bad"}],
            tool_calls=[{
                "name": "exec",
                "input": {"command": "bad"},
                "error": "command not found",
            }],
        )

        content = logger.file_path.read_text()
        assert "❌ Tool Error: `exec`" in content
        assert "command not found" in content

    def test_multiple_tool_calls_numbered(self, tmp_path):
        """Multiple tool calls in one turn are numbered."""
        logger = ModelLedger(root_dir=tmp_path)
        logger.log_turn(
            messages=[{"role": "user", "content": "do stuff"}],
            tool_calls=[
                {"name": "exec", "input": {"command": "ls"}},
                {"name": "Read", "input": {"path": "foo.py"}},
            ],
        )

        content = logger.file_path.read_text()
        assert "Tool Call 1: `exec`" in content
        assert "Tool Call 2: `Read`" in content

    def test_close(self, tmp_path):
        """close() appends Session End section."""
        logger = ModelLedger(root_dir=tmp_path, model="gpt-4o")
        logger.log_turn(
            messages=[{"role": "user", "content": "hi"}],
            response="hello",
            usage={"input_tokens": 100, "output_tokens": 50},
        )
        result = logger.close(summary="Test session")

        content = logger.file_path.read_text()
        assert "## Session End" in content
        assert "Test session" in content
        assert "100" in content
        assert "50" in content
        assert result["total_turns"] == 1
        assert result["summary"] == "Test session"

    def test_close_with_override_tokens(self, tmp_path):
        """close() can override token counts."""
        logger = ModelLedger(root_dir=tmp_path, model="gpt-4o")
        logger.log_turn(messages=[{"role": "user", "content": "x"}], response="y")
        result = logger.close(input_tokens=999, output_tokens=111)
        assert result["input_tokens"] == 999
        assert result["output_tokens"] == 111

    def test_read_log_with_path(self, tmp_path):
        """read_log parses an MD file back into records."""
        logger = ModelLedger(
            root_dir=tmp_path, model="gpt-4o", provider="openai",
        )
        logger.log_turn(
            messages=[{"role": "user", "content": "q1"}],
            response="a1",
        )
        logger.log_turn(
            messages=[{"role": "user", "content": "q2"}],
            response="a2",
        )

        records = read_log(path=str(logger.file_path))
        assert len(records) == 2
        assert records[0].model == "gpt-4o"
        assert records[1].provider == "openai"

    def test_read_log_missing_file(self):
        """read_log returns empty list for non-existent file."""
        records = read_log(path="/tmp/nonexistent_audit_log.md")
        assert records == []

    def test_read_log_with_tool_calls(self, tmp_path):
        """read_log correctly parses tool calls from MD."""
        logger = ModelLedger(root_dir=tmp_path, model="gpt-4o", provider="openai")
        logger.log_turn(
            messages=[{"role": "user", "content": "list files"}],
            tool_calls=[{
                "name": "exec",
                "input": {"command": "ls"},
                "output": "a.py\nb.py",
            }],
            response="Found 2 files.",
        )

        records = read_log(path=str(logger.file_path))
        assert len(records) == 1
        assert len(records[0].tool_calls) == 1
        assert records[0].tool_calls[0]["name"] == "exec"
        assert "list files" in records[0].messages[0]["content"]

    def test_session_header_fields(self, tmp_path):
        """Session header contains all provided metadata."""
        logger = ModelLedger(
            root_dir=tmp_path,
            session_id="test-uuid",
            model="claude-sonnet-4-6",
            provider="anthropic",
            channel="bluebubbles",
            host="Test Host",
        )

        content = logger.file_path.read_text()
        assert "test-uuid" in content
        assert "claude-sonnet-4-6" in content
        assert "anthropic" in content
        assert "bluebubbles" in content
        assert "Test Host" in content
