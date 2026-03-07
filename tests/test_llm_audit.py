"""Tests for the llm_audit tool."""

import json
import os
import tempfile
from pathlib import Path

import pytest

from tools.llm_audit.record import AuditRecord
from tools.llm_audit.pricing import estimate_cost, PRICING
from tools.llm_audit.reader import read_log, filter_records, summarize
from tools.llm_audit.logger import AuditLogger


# ---------------------------------------------------------------
# AuditRecord serialization / deserialization
# ---------------------------------------------------------------

class TestAuditRecord:
    def test_round_trip_defaults(self):
        """A default record survives a JSONL round-trip."""
        original = AuditRecord()
        line = original.to_jsonl()
        restored = AuditRecord.from_jsonl(line)
        assert restored.request_id == original.request_id
        assert restored.status == "success"

    def test_round_trip_full(self):
        """A fully-populated record survives a JSONL round-trip."""
        original = AuditRecord(
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
        restored = AuditRecord.from_jsonl(line)

        assert restored.session_id == "sess-1"
        assert restored.model == "gpt-4o"
        assert restored.temperature == 0.7
        assert restored.messages == original.messages
        assert restored.tool_calls == original.tool_calls
        assert restored.cost_usd == 0.001
        assert restored.extra_params == {"seed": 42}

    def test_to_jsonl_is_single_line(self):
        record = AuditRecord(response="line1\nline2")
        line = record.to_jsonl()
        assert "\n" not in line

    def test_to_jsonl_is_valid_json(self):
        record = AuditRecord(model="gpt-4o", response="hello")
        parsed = json.loads(record.to_jsonl())
        assert parsed["model"] == "gpt-4o"
        assert parsed["response"] == "hello"

    def test_error_record(self):
        record = AuditRecord(
            status="error",
            error_type="APIError",
            error_message="rate limited",
        )
        restored = AuditRecord.from_jsonl(record.to_jsonl())
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

def _make_records() -> list[AuditRecord]:
    return [
        AuditRecord(
            provider="openai", model="gpt-4o", status="success",
            latency_ms=100, prompt_tokens=500, completion_tokens=200,
            total_tokens=700, cost_usd=0.003,
            timestamp="2026-03-07T10:00:00+00:00",
        ),
        AuditRecord(
            provider="openai", model="gpt-4o-mini", status="success",
            latency_ms=50, prompt_tokens=200, completion_tokens=100,
            total_tokens=300, cost_usd=0.0001,
            timestamp="2026-03-07T11:00:00+00:00",
        ),
        AuditRecord(
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
# AuditLogger JSONL writes
# ---------------------------------------------------------------

class TestAuditLogger:
    def test_log_creates_file(self, tmp_path):
        logger = AuditLogger(log_dir=tmp_path, session_id="s1", caller="test")
        record = AuditRecord(provider="openai", model="gpt-4o", response="hi")
        logger.log(record)

        files = list(tmp_path.glob("llm_*.jsonl"))
        assert len(files) == 1

        content = files[0].read_text()
        lines = [l for l in content.strip().split("\n") if l]
        assert len(lines) == 1
        restored = AuditRecord.from_jsonl(lines[0])
        assert restored.model == "gpt-4o"
        assert restored.response == "hi"

    def test_log_appends(self, tmp_path):
        logger = AuditLogger(log_dir=tmp_path)
        logger.log(AuditRecord(model="a"))
        logger.log(AuditRecord(model="b"))

        files = list(tmp_path.glob("llm_*.jsonl"))
        lines = [l for l in files[0].read_text().strip().split("\n") if l]
        assert len(lines) == 2

    def test_read_log_with_path(self, tmp_path):
        logger = AuditLogger(log_dir=tmp_path)
        logger.log(AuditRecord(model="gpt-4o", provider="openai"))
        logger.log(AuditRecord(model="claude-sonnet-4-6", provider="anthropic"))

        log_file = list(tmp_path.glob("llm_*.jsonl"))[0]
        records = read_log(path=str(log_file))
        assert len(records) == 2
        assert records[0].model == "gpt-4o"
        assert records[1].provider == "anthropic"

    def test_read_log_missing_file(self):
        records = read_log(path="/tmp/nonexistent_audit_log.jsonl")
        assert records == []
