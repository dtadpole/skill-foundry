"""Parsing helpers for ModelLedger Markdown files."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Optional


def parse_ledger_session(md_path: str | Path) -> Optional[dict]:
    """Extract session metadata and cost info from a ModelLedger MD file.

    Returns a dict with: session_id, model, provider, channel, input_tokens,
    output_tokens, cost_usd, summary, ended_at.  Returns None if parsing fails.
    """
    path = Path(md_path)
    if not path.exists():
        return None

    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None

    result: dict = {}

    # --- Session Header table ---
    _extract_header_field(text, "ID", "session_id", result)
    _extract_header_field(text, "Model", "model", result)
    _extract_header_field(text, "Provider", "provider", result)
    _extract_header_field(text, "Channel", "channel", result)

    if "session_id" not in result:
        return None

    # --- Session End table ---
    end_match = re.search(r"## Session End\s*\n(.*)", text, re.DOTALL)
    if not end_match:
        return None  # session not closed yet

    end_block = end_match.group(1)

    _extract_table_field(end_block, "Ended", "ended_at", result)
    _extract_table_int(end_block, "Input Tokens", "input_tokens", result)
    _extract_table_int(end_block, "Output Tokens", "output_tokens", result)
    _extract_table_cost(end_block, "Estimated Cost", "cost_usd", result)
    _extract_table_field(end_block, "Summary", "summary", result)

    return result


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_TABLE_ROW = re.compile(r"\|\s*{key}\s*\|\s*(.+?)\s*\|")


def _extract_header_field(text: str, key: str, dest: str, out: dict) -> None:
    m = re.search(rf"\|\s*{re.escape(key)}\s*\|\s*(.+?)\s*\|", text)
    if m:
        out[dest] = m.group(1).strip()


def _extract_table_field(block: str, key: str, dest: str, out: dict) -> None:
    m = re.search(rf"\|\s*{re.escape(key)}\s*\|\s*(.+?)\s*\|", block)
    if m:
        out[dest] = m.group(1).strip()


def _extract_table_int(block: str, key: str, dest: str, out: dict) -> None:
    m = re.search(rf"\|\s*{re.escape(key)}\s*\|\s*(.+?)\s*\|", block)
    if m:
        try:
            out[dest] = int(m.group(1).strip().replace(",", ""))
        except ValueError:
            pass


def _extract_table_cost(block: str, key: str, dest: str, out: dict) -> None:
    m = re.search(rf"\|\s*{re.escape(key)}\s*\|\s*\$?([\d.]+)\s*\|", block)
    if m:
        try:
            out[dest] = float(m.group(1))
        except ValueError:
            pass
