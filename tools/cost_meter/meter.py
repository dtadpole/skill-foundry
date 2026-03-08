"""CostMeter — track token usage and API costs across ModelLedger sessions."""

from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from tools.model_ledger.pricing import estimate_cost
from tools.storage import get_backend
from tools.storage.backend import StorageBackend

from .record import CostRecord, CostSummary
from .reader import parse_ledger_content

_RECORDS_KEY = "cost_meter/records.jsonl"
_BUDGET_KEY = "cost_meter/budget.json"
_LEDGER_PREFIX = "model_ledger/"


class CostMeter:
    """Track token usage and API costs across all ModelLedger sessions."""

    def __init__(
        self,
        root_dir: str | Path | None = None,
        budget_usd: float | None = None,
        backend: Optional[StorageBackend] = None,
    ) -> None:
        if backend is not None:
            self._backend = backend
            self._records_key = _RECORDS_KEY
            self._budget_key = _BUDGET_KEY
            self._ledger_prefix = _LEDGER_PREFIX
        elif root_dir is not None:
            from tools.storage.local import LocalBackend
            self._backend = LocalBackend(root=str(root_dir))
            # Legacy: files live directly in root_dir (no namespace prefix)
            self._records_key = "records.jsonl"
            self._budget_key = "budget.json"
            self._ledger_prefix = ""
        else:
            self._backend = get_backend()
            self._records_key = _RECORDS_KEY
            self._budget_key = _BUDGET_KEY
            self._ledger_prefix = _LEDGER_PREFIX

        self._lock = threading.Lock()

        if budget_usd is not None:
            self._save_budget(budget_usd)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def record(
        self,
        session_id: str,
        model: str,
        input_tokens: int,
        output_tokens: int,
        *,
        provider: str = "",
        channel: str | None = None,
        timestamp: str | None = None,
        session_summary: str | None = None,
    ) -> CostRecord:
        """Record a session's token usage and cost.  Append-only."""
        cost = estimate_cost(model, input_tokens, output_tokens)

        rec = CostRecord(
            session_id=session_id,
            timestamp=timestamp or datetime.now(timezone.utc).isoformat(),
            model=model,
            provider=provider,
            channel=channel,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=input_tokens + output_tokens,
            cost_usd=cost if cost is not None else 0.0,
            session_summary=session_summary,
        )

        with self._lock:
            self._backend.append(self._records_key, rec.to_jsonl_line() + "\n")

        return rec

    def sync_from_ledger(
        self,
        ledger_prefix: Optional[str] = None,
        ledger_dir: Optional[Path | str] = None,
    ) -> int:
        """Import sessions from ModelLedger MD objects that aren't yet recorded.

        Args:
            ledger_prefix: Storage key prefix to scan (new API).
            ledger_dir: Local directory path to scan (legacy API, takes precedence).
        """
        if ledger_dir is not None:
            # Legacy path-based scanning
            from tools.storage.local import LocalBackend
            local = LocalBackend(root=str(ledger_dir))
            keys = local.list_prefix("")
            md_keys = sorted(k for k in keys if k.endswith(".md"))
            read_content = local.get
        else:
            prefix = ledger_prefix if ledger_prefix is not None else self._ledger_prefix
            keys = self._backend.list_prefix(prefix)
            md_keys = sorted(k for k in keys if k.endswith(".md"))
            read_content = self._backend.get

        if not md_keys:
            return 0

        existing_ids = self._existing_session_ids()
        imported = 0

        for key in md_keys:
            content = read_content(key)
            if not content:
                continue
            parsed = parse_ledger_content(content)
            if parsed is None:
                continue
            sid = parsed.get("session_id", "")
            if not sid or sid in existing_ids:
                continue

            self.record(
                session_id=sid,
                model=parsed.get("model", ""),
                input_tokens=parsed.get("input_tokens", 0),
                output_tokens=parsed.get("output_tokens", 0),
                provider=parsed.get("provider", ""),
                channel=parsed.get("channel"),
                timestamp=parsed.get("ended_at"),
                session_summary=parsed.get("summary"),
            )
            existing_ids.add(sid)
            imported += 1

        return imported

    def daily(self, date: str | None = None) -> CostSummary:
        """Cost summary for a single day (YYYY-MM-DD)."""
        if date is None:
            date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        records = [r for r in self._load_records() if r.timestamp.startswith(date)]
        return self._aggregate(records, period=date)

    def monthly(self, month: str | None = None) -> CostSummary:
        """Cost summary for a month (YYYY-MM)."""
        if month is None:
            month = datetime.now(timezone.utc).strftime("%Y-%m")
        records = [r for r in self._load_records() if r.timestamp[:7] == month]
        return self._aggregate(records, period=month)

    def total(self) -> CostSummary:
        """All-time cost summary."""
        return self._aggregate(self._load_records(), period="all-time")

    def check_budget(self) -> Optional[dict]:
        """Check current month's spend vs budget.  None if no budget set."""
        budget = self._load_budget()
        if budget is None:
            return None
        summary = self.monthly()
        spent = summary.total_cost_usd
        return {
            "budget": budget,
            "spent": round(spent, 6),
            "remaining": round(max(budget - spent, 0), 6),
            "over_budget": spent > budget,
        }

    def format_summary(self, summary: CostSummary) -> str:
        """Return a human-readable Markdown summary."""
        lines = [
            f"## Cost Summary — {summary.period}",
            "",
            "| Metric | Value |",
            "|--------|-------|",
            f"| Sessions | {summary.session_count} |",
            f"| Input Tokens | {summary.total_input_tokens:,} |",
            f"| Output Tokens | {summary.total_output_tokens:,} |",
            f"| Total Tokens | {summary.total_tokens:,} |",
            f"| Total Cost | ${summary.total_cost_usd:.4f} |",
            f"| Avg / Session | ${summary.avg_cost_per_session:.4f} |",
        ]

        if summary.by_model:
            lines += ["", "### By Model", "", "| Model | Sessions | Cost |", "|-------|----------|------|"]
            for model, info in sorted(summary.by_model.items()):
                lines.append(f"| {model} | {info['count']} | ${info['cost']:.4f} |")

        if summary.by_channel:
            lines += ["", "### By Channel", "", "| Channel | Sessions | Cost |", "|---------|----------|------|"]
            for ch, info in sorted(summary.by_channel.items()):
                lines.append(f"| {ch} | {info['count']} | ${info['cost']:.4f} |")

        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _load_records(self) -> list[CostRecord]:
        raw = self._backend.get(self._records_key)
        if not raw:
            return []
        records = []
        for line in raw.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                records.append(CostRecord.from_dict(json.loads(line)))
            except (json.JSONDecodeError, TypeError):
                continue
        return records

    def _existing_session_ids(self) -> set[str]:
        return {r.session_id for r in self._load_records()}

    def _aggregate(self, records: list[CostRecord], period: str) -> CostSummary:
        if not records:
            return CostSummary(period=period)

        by_model: dict[str, dict] = {}
        by_channel: dict[str, dict] = {}
        most_expensive_id: str | None = None
        most_expensive_cost = -1.0

        total_input = 0
        total_output = 0
        total_cost = 0.0

        for r in records:
            total_input += r.input_tokens
            total_output += r.output_tokens
            total_cost += r.cost_usd

            # per-model
            if r.model:
                bucket = by_model.setdefault(r.model, {"count": 0, "cost": 0.0, "tokens": 0})
                bucket["count"] += 1
                bucket["cost"] += r.cost_usd
                bucket["tokens"] += r.total_tokens

            # per-channel
            ch = r.channel or "unknown"
            bucket = by_channel.setdefault(ch, {"count": 0, "cost": 0.0, "tokens": 0})
            bucket["count"] += 1
            bucket["cost"] += r.cost_usd
            bucket["tokens"] += r.total_tokens

            if r.cost_usd > most_expensive_cost:
                most_expensive_cost = r.cost_usd
                most_expensive_id = r.session_id

        n = len(records)
        return CostSummary(
            period=period,
            session_count=n,
            total_input_tokens=total_input,
            total_output_tokens=total_output,
            total_tokens=total_input + total_output,
            total_cost_usd=round(total_cost, 8),
            by_model=by_model,
            by_channel=by_channel,
            avg_cost_per_session=round(total_cost / n, 8) if n else 0.0,
            most_expensive_session=most_expensive_id,
        )

    def _load_budget(self) -> Optional[float]:
        raw = self._backend.get(self._budget_key)
        if not raw:
            return None
        try:
            data = json.loads(raw)
            return float(data.get("monthly_budget_usd", 0))
        except (json.JSONDecodeError, TypeError, ValueError):
            return None

    def _save_budget(self, budget_usd: float) -> None:
        self._backend.put(
            self._budget_key,
            json.dumps({"monthly_budget_usd": budget_usd}, indent=2) + "\n",
        )
