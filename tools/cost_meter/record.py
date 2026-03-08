"""Data classes for cost tracking records and summaries."""

from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict

from tools.ulid_utils import new_ulid
from datetime import datetime, timezone
from typing import Optional


@dataclass
class CostRecord:
    """One record per logged session."""

    record_id: str = field(default_factory=new_ulid)
    session_id: str = ""
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    model: str = ""
    provider: str = ""
    channel: Optional[str] = None
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    cost_usd: float = 0.0
    session_summary: Optional[str] = None

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> CostRecord:
        known = {f.name for f in cls.__dataclass_fields__.values()}
        return cls(**{k: v for k, v in data.items() if k in known})

    def to_jsonl_line(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False)


@dataclass
class CostSummary:
    """Aggregated cost view for a given period."""

    period: str = "all-time"
    session_count: int = 0
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_tokens: int = 0
    total_cost_usd: float = 0.0
    by_model: dict[str, dict] = field(default_factory=dict)
    by_channel: dict[str, dict] = field(default_factory=dict)
    avg_cost_per_session: float = 0.0
    most_expensive_session: Optional[str] = None
