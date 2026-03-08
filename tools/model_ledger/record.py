"""Audit record dataclass for LLM call logging."""

from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict

from tools.ulid_utils import new_ulid
from datetime import datetime, timezone
from typing import Optional


@dataclass
class ModelLedgerRecord:
    """Structured record of a single LLM API call."""

    # Identity & Timing
    request_id: str = field(default_factory=new_ulid)
    session_id: Optional[str] = None
    caller: Optional[str] = None
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    latency_ms: float = 0.0

    # Model Info
    provider: str = "custom"
    model: str = ""
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None
    top_p: Optional[float] = None
    extra_params: dict = field(default_factory=dict)

    # The Conversation
    system_prompt: Optional[str] = None
    messages: list[dict] = field(default_factory=list)
    response: str = ""
    tool_calls: list[dict] = field(default_factory=list)

    # Token & Cost
    prompt_tokens: Optional[int] = None
    completion_tokens: Optional[int] = None
    total_tokens: Optional[int] = None
    cost_usd: Optional[float] = None

    # Status
    status: str = "success"
    error_type: Optional[str] = None
    error_message: Optional[str] = None

    def to_jsonl(self) -> str:
        """Serialize this record to a single JSON line."""
        return json.dumps(asdict(self), ensure_ascii=False, separators=(",", ":"))

    @classmethod
    def from_jsonl(cls, line: str) -> ModelLedgerRecord:
        """Deserialize a single JSON line into an ModelLedgerRecord."""
        data = json.loads(line.strip())
        return cls(**data)
