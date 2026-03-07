"""Reader utilities for querying and summarizing audit logs."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .record import ModelLedgerRecord

_DEFAULT_DIR = Path.home() / ".skillfoundry" / "audit"


def read_log(
    date: Optional[str] = None, path: Optional[str] = None
) -> list[ModelLedgerRecord]:
    """Read a day's audit log and return a list of ModelLedgerRecords.

    Args:
        date: Date string in YYYY-MM-DD format. Defaults to today (UTC).
        path: Explicit file path. If given, ``date`` is ignored.
    """
    if path:
        log_path = Path(path)
    else:
        if date is None:
            date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        log_path = _DEFAULT_DIR / f"llm_{date}.jsonl"

    if not log_path.exists():
        return []

    records: list[ModelLedgerRecord] = []
    with open(log_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(ModelLedgerRecord.from_jsonl(line))
    return records


def filter_records(
    records: list[ModelLedgerRecord],
    *,
    provider: Optional[str] = None,
    model: Optional[str] = None,
    status: Optional[str] = None,
    since: Optional[str] = None,
) -> list[ModelLedgerRecord]:
    """Filter a list of ModelLedgerRecords by provider, model, status, or timestamp.

    Args:
        records: List of records to filter.
        provider: Keep only records matching this provider.
        model: Keep only records matching this model.
        status: Keep only records matching this status.
        since: ISO 8601 timestamp — keep only records at or after this time.
    """
    result = records
    if provider is not None:
        result = [r for r in result if r.provider == provider]
    if model is not None:
        result = [r for r in result if r.model == model]
    if status is not None:
        result = [r for r in result if r.status == status]
    if since is not None:
        result = [r for r in result if r.timestamp >= since]
    return result


def summarize(records: list[ModelLedgerRecord]) -> dict:
    """Produce a summary dict from a list of ModelLedgerRecords.

    Returns:
        Dict with keys: total_calls, total_prompt_tokens, total_completion_tokens,
        total_tokens, total_cost_usd, avg_latency_ms, error_rate.
    """
    total = len(records)
    if total == 0:
        return {
            "total_calls": 0,
            "total_prompt_tokens": 0,
            "total_completion_tokens": 0,
            "total_tokens": 0,
            "total_cost_usd": 0.0,
            "avg_latency_ms": 0.0,
            "error_rate": 0.0,
        }

    prompt_tokens = sum(r.prompt_tokens or 0 for r in records)
    completion_tokens = sum(r.completion_tokens or 0 for r in records)
    total_tokens = sum(r.total_tokens or 0 for r in records)
    total_cost = sum(r.cost_usd or 0.0 for r in records)
    avg_latency = sum(r.latency_ms for r in records) / total
    errors = sum(1 for r in records if r.status == "error")

    return {
        "total_calls": total,
        "total_prompt_tokens": prompt_tokens,
        "total_completion_tokens": completion_tokens,
        "total_tokens": total_tokens,
        "total_cost_usd": round(total_cost, 8),
        "avg_latency_ms": round(avg_latency, 2),
        "error_rate": round(errors / total, 4),
    }
