"""Tests for the cost_meter tool."""

import json
from pathlib import Path

import pytest

from tools.cost_meter.record import CostRecord, CostSummary
from tools.cost_meter.meter import CostMeter
from tools.cost_meter.reader import parse_ledger_session


# ---------------------------------------------------------------
# CostRecord serialization
# ---------------------------------------------------------------

class TestCostRecord:
    def test_round_trip(self):
        """A CostRecord survives dict → JSONL → dict round-trip."""
        original = CostRecord(
            session_id="sess-1",
            model="claude-sonnet-4-6",
            provider="anthropic",
            channel="bluebubbles",
            input_tokens=1000,
            output_tokens=500,
            total_tokens=1500,
            cost_usd=0.0105,
            session_summary="Test session",
        )
        line = original.to_jsonl_line()
        restored = CostRecord.from_dict(json.loads(line))

        assert restored.session_id == "sess-1"
        assert restored.model == "claude-sonnet-4-6"
        assert restored.provider == "anthropic"
        assert restored.channel == "bluebubbles"
        assert restored.input_tokens == 1000
        assert restored.output_tokens == 500
        assert restored.total_tokens == 1500
        assert restored.cost_usd == 0.0105
        assert restored.session_summary == "Test session"

    def test_jsonl_is_single_line(self):
        rec = CostRecord(session_summary="line1\nline2")
        assert "\n" not in rec.to_jsonl_line()

    def test_defaults(self):
        rec = CostRecord()
        assert rec.record_id  # UUID generated
        assert rec.timestamp  # timestamp generated
        assert rec.input_tokens == 0
        assert rec.cost_usd == 0.0


# ---------------------------------------------------------------
# CostMeter.record()
# ---------------------------------------------------------------

class TestCostMeterRecord:
    def test_record_appends_to_jsonl(self, tmp_path):
        meter = CostMeter(root_dir=tmp_path)
        rec = meter.record("s1", "claude-sonnet-4-6", 1000, 500, provider="anthropic")

        assert rec.session_id == "s1"
        assert rec.total_tokens == 1500
        assert rec.cost_usd > 0

        lines = (tmp_path / "records.jsonl").read_text().strip().splitlines()
        assert len(lines) == 1

        data = json.loads(lines[0])
        assert data["session_id"] == "s1"

    def test_multiple_records(self, tmp_path):
        meter = CostMeter(root_dir=tmp_path)
        meter.record("s1", "claude-sonnet-4-6", 100, 50)
        meter.record("s2", "gpt-4o", 200, 100)

        lines = (tmp_path / "records.jsonl").read_text().strip().splitlines()
        assert len(lines) == 2

    def test_unknown_model_zero_cost(self, tmp_path):
        meter = CostMeter(root_dir=tmp_path)
        rec = meter.record("s1", "unknown-model", 100, 50)
        assert rec.cost_usd == 0.0


# ---------------------------------------------------------------
# CostMeter.daily()
# ---------------------------------------------------------------

class TestCostMeterDaily:
    def test_daily_correct_summary(self, tmp_path):
        meter = CostMeter(root_dir=tmp_path)
        meter.record("s1", "claude-sonnet-4-6", 1000, 500, timestamp="2026-03-07T10:00:00+00:00")
        meter.record("s2", "claude-sonnet-4-6", 2000, 1000, timestamp="2026-03-07T15:00:00+00:00")
        meter.record("s3", "gpt-4o", 500, 200, timestamp="2026-03-08T10:00:00+00:00")

        summary = meter.daily("2026-03-07")
        assert summary.period == "2026-03-07"
        assert summary.session_count == 2
        assert summary.total_input_tokens == 3000
        assert summary.total_output_tokens == 1500
        assert summary.total_tokens == 4500
        assert summary.total_cost_usd > 0

    def test_daily_no_records(self, tmp_path):
        meter = CostMeter(root_dir=tmp_path)
        summary = meter.daily("2026-01-01")
        assert summary.session_count == 0
        assert summary.total_cost_usd == 0.0


# ---------------------------------------------------------------
# CostMeter.monthly()
# ---------------------------------------------------------------

class TestCostMeterMonthly:
    def test_monthly_aggregates(self, tmp_path):
        meter = CostMeter(root_dir=tmp_path)
        meter.record("s1", "claude-sonnet-4-6", 1000, 500, timestamp="2026-03-01T10:00:00+00:00")
        meter.record("s2", "gpt-4o", 2000, 1000, timestamp="2026-03-15T10:00:00+00:00")
        meter.record("s3", "gpt-4o", 500, 200, timestamp="2026-04-01T10:00:00+00:00")

        summary = meter.monthly("2026-03")
        assert summary.period == "2026-03"
        assert summary.session_count == 2
        assert "claude-sonnet-4-6" in summary.by_model
        assert "gpt-4o" in summary.by_model


# ---------------------------------------------------------------
# CostMeter.sync_from_ledger()
# ---------------------------------------------------------------

def _write_ledger_md(path: Path, session_id: str, model: str = "claude-sonnet-4-6",
                     provider: str = "anthropic", channel: str = "bluebubbles",
                     input_tokens: int = 100, output_tokens: int = 50,
                     cost: float = 0.001, summary: str = "test") -> None:
    """Write a minimal ModelLedger MD file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"""# ModelLedger Session

| Field    | Value |
|----------|-------|
| ID       | {session_id} |
| Started  | 2026-03-08T01:00:00+00:00 |
| Model    | {model} |
| Provider | {provider} |
| Channel  | {channel} |
| Host     | Test |

---

## Turn 1 — 2026-03-08T01:00:01+00:00

### 👤 User

hello

### 🤖 Assistant

hi

---

## Session End

| Field              | Value |
|--------------------|-------|
| Ended              | 2026-03-08T01:00:02+00:00 |
| Total Turns        | 1 |
| Input Tokens       | {input_tokens} |
| Output Tokens      | {output_tokens} |
| Estimated Cost     | ${cost} |
| Summary            | {summary} |
""",
        encoding="utf-8",
    )


class TestSyncFromLedger:
    def test_imports_ledger_files(self, tmp_path):
        ledger_dir = tmp_path / "model_ledger" / "2026-03-08"
        cost_dir = tmp_path / "cost_meter"

        _write_ledger_md(ledger_dir / "sess-aaa.md", "sess-aaa")
        _write_ledger_md(ledger_dir / "sess-bbb.md", "sess-bbb")

        meter = CostMeter(root_dir=cost_dir)
        count = meter.sync_from_ledger(ledger_dir=tmp_path / "model_ledger")

        assert count == 2
        summary = meter.total()
        assert summary.session_count == 2

    def test_deduplication(self, tmp_path):
        """Importing the same session twice produces only one record."""
        ledger_dir = tmp_path / "model_ledger" / "2026-03-08"
        cost_dir = tmp_path / "cost_meter"

        _write_ledger_md(ledger_dir / "sess-aaa.md", "sess-aaa")

        meter = CostMeter(root_dir=cost_dir)
        first = meter.sync_from_ledger(ledger_dir=tmp_path / "model_ledger")
        second = meter.sync_from_ledger(ledger_dir=tmp_path / "model_ledger")

        assert first == 1
        assert second == 0
        assert meter.total().session_count == 1

    def test_empty_ledger(self, tmp_path):
        meter = CostMeter(root_dir=tmp_path / "cost_meter")
        count = meter.sync_from_ledger(ledger_dir=tmp_path / "nonexistent")
        assert count == 0


# ---------------------------------------------------------------
# Budget
# ---------------------------------------------------------------

class TestBudget:
    def test_budget_check(self, tmp_path):
        meter = CostMeter(root_dir=tmp_path, budget_usd=10.0)
        meter.record("s1", "claude-sonnet-4-6", 1000, 500, timestamp="2026-03-07T10:00:00+00:00")

        status = meter.check_budget()
        assert status is not None
        assert status["budget"] == 10.0
        assert status["spent"] > 0
        assert status["remaining"] > 0
        assert status["over_budget"] is False

    def test_no_budget(self, tmp_path):
        meter = CostMeter(root_dir=tmp_path)
        assert meter.check_budget() is None

    def test_budget_persists(self, tmp_path):
        CostMeter(root_dir=tmp_path, budget_usd=25.0)
        meter2 = CostMeter(root_dir=tmp_path)
        status = meter2.check_budget()
        assert status is not None
        assert status["budget"] == 25.0


# ---------------------------------------------------------------
# Reader — parse_ledger_session
# ---------------------------------------------------------------

class TestReader:
    def test_parse_valid_md(self, tmp_path):
        md = tmp_path / "test.md"
        _write_ledger_md(md, "sess-xyz", input_tokens=200, output_tokens=100, cost=0.005)

        result = parse_ledger_session(md)
        assert result is not None
        assert result["session_id"] == "sess-xyz"
        assert result["model"] == "claude-sonnet-4-6"
        assert result["provider"] == "anthropic"
        assert result["channel"] == "bluebubbles"
        assert result["input_tokens"] == 200
        assert result["output_tokens"] == 100
        assert result["cost_usd"] == 0.005
        assert result["summary"] == "test"

    def test_parse_nonexistent(self):
        assert parse_ledger_session("/tmp/nonexistent.md") is None

    def test_parse_no_session_end(self, tmp_path):
        """MD without Session End section returns None."""
        md = tmp_path / "incomplete.md"
        md.write_text(
            "# ModelLedger Session\n\n"
            "| Field | Value |\n|--|--|\n| ID | abc |\n",
            encoding="utf-8",
        )
        assert parse_ledger_session(md) is None


# ---------------------------------------------------------------
# format_summary
# ---------------------------------------------------------------

class TestFormatSummary:
    def test_format_output(self, tmp_path):
        meter = CostMeter(root_dir=tmp_path)
        meter.record("s1", "claude-sonnet-4-6", 1000, 500, channel="bluebubbles",
                      timestamp="2026-03-07T10:00:00+00:00")

        summary = meter.daily("2026-03-07")
        text = meter.format_summary(summary)

        assert "Cost Summary" in text
        assert "claude-sonnet-4-6" in text
        assert "bluebubbles" in text
        assert "$" in text
