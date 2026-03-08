"""Core ModelLedger — session-based Markdown logger under ~/.blue_lantern/model_ledger/."""

from __future__ import annotations

import json
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from tools.storage import get_backend
from tools.storage.backend import StorageBackend
from tools.ulid_utils import new_ulid

from .pricing import estimate_cost

_DEFAULT_DIR = Path.home() / ".blue_lantern" / "model_ledger"

_ROLE_ICONS = {
    "system": "🔧 System",
    "user": "👤 User",
    "assistant": "🤖 Assistant",
}


class ModelLedger:
    """Session-based logger writing events to a per-session Markdown file.

    Storage: ~/.blue_lantern/model_ledger/YYYY-MM-DD/{session_id}.md
    Each file contains: session header, turn sections, session end.
    All writes are append-only and immutable.

    Args:
        session_id: Unique session ID. Auto-generated UUID4 if not provided.
        model: Model name (e.g. "claude-sonnet-4-6").
        provider: Provider name (e.g. "anthropic").
        channel: Channel name (e.g. "bluebubbles").
        host: Host name. Defaults to "Blue Lantern".
        root_dir: Root directory. Defaults to ~/.blue_lantern/model_ledger/.
    """

    def __init__(
        self,
        session_id: Optional[str] = None,
        model: Optional[str] = None,
        provider: Optional[str] = None,
        channel: Optional[str] = None,
        host: str = "Blue Lantern",
        root_dir: Optional[str | Path] = None,
        backend: Optional[StorageBackend] = None,
    ) -> None:
        self._session_id = session_id or new_ulid()
        self._model = model
        self._provider = provider
        self._channel = channel
        self._host = host
        self._lock = threading.Lock()
        self._turn_count = 0
        self._total_input_tokens = 0
        self._total_output_tokens = 0

        now = datetime.now(timezone.utc)
        self._started_at = now.isoformat()
        today = now.strftime("%Y-%m-%d")

        # Storage backend — three cases:
        #   1. explicit backend arg
        #   2. legacy root_dir arg → LocalBackend scoped to that dir (no namespace prefix)
        #   3. default → global configured backend with "model_ledger/" prefix
        if backend is not None:
            self._backend = backend
            self._key = f"model_ledger/{today}/{self._session_id}.md"
        elif root_dir is not None:
            from tools.storage.local import LocalBackend
            self._backend = LocalBackend(root=str(root_dir))
            self._key = f"{today}/{self._session_id}.md"
        else:
            self._backend = get_backend()
            self._key = f"model_ledger/{today}/{self._session_id}.md"

        # file_path for backwards compat (.file_path property)
        if root_dir is not None:
            self._root_dir = Path(root_dir)
        else:
            self._root_dir = _DEFAULT_DIR
        self._date_dir = self._root_dir / today
        self._file_path = self._date_dir / f"{self._session_id}.md"

        # Write session header
        header = "# ModelLedger Session\n\n"
        header += "| Field    | Value |\n"
        header += "|----------|-------|\n"
        header += f"| ID       | {self._session_id} |\n"
        header += f"| Started  | {self._started_at} |\n"
        if self._model:
            header += f"| Model    | {self._model} |\n"
        if self._provider:
            header += f"| Provider | {self._provider} |\n"
        if self._channel:
            header += f"| Channel  | {self._channel} |\n"
        header += f"| Host     | {self._host} |\n"

        self._append(header)

    @property
    def session_id(self) -> str:
        return self._session_id

    @property
    def file_path(self) -> Path:
        return self._file_path

    def _append(self, text: str) -> None:
        """Append text to the session file (append-only)."""
        with self._lock:
            self._backend.append(self._key, text)

    def log_turn(
        self,
        turn_number: Optional[int] = None,
        messages: Optional[list[dict]] = None,
        response: Optional[str] = None,
        tool_calls: Optional[list[dict]] = None,
        usage: Optional[dict] = None,
        timestamp: Optional[str] = None,
    ) -> None:
        """Log a single LLM turn as a Markdown section.

        Args:
            turn_number: Turn number (auto-increments if not provided).
            messages: List of message dicts [{role, content}, ...].
            response: Assistant response text. If tool_calls are present,
                      rendered as "Assistant (continued)" after tool results.
            tool_calls: List of tool call dicts
                        [{name, input, output, error}, ...].
            usage: Dict {input_tokens, output_tokens}.
            timestamp: ISO timestamp (defaults to now).
        """
        self._turn_count += 1
        tn = turn_number if turn_number is not None else self._turn_count

        if usage:
            self._total_input_tokens += usage.get("input_tokens", 0)
            self._total_output_tokens += usage.get("output_tokens", 0)

        ts = timestamp or datetime.now(timezone.utc).isoformat()

        section = f"\n---\n\n## Turn {tn} — {ts}\n"

        # Render messages (content may be str or list of Anthropic blocks)
        if messages:
            for msg in messages:
                role = msg.get("role", "user")
                raw_content = msg.get("content", "")
                icon = _ROLE_ICONS.get(role, role)

                if isinstance(raw_content, list):
                    # Anthropic structured content blocks
                    for block in raw_content:
                        btype = block.get("type") if isinstance(block, dict) else getattr(block, "type", "text")
                        if btype == "tool_result":
                            tid = block.get("tool_use_id", "") if isinstance(block, dict) else getattr(block, "tool_use_id", "")
                            result_content = block.get("content", "") if isinstance(block, dict) else getattr(block, "content", "")
                            if isinstance(result_content, list):
                                result_content = "\n".join(
                                    (b.get("text", "") if isinstance(b, dict) else getattr(b, "text", ""))
                                    for b in result_content
                                )
                            section += f"\n### ↩️ Tool Result (id: `{tid}`)" + "\n\n"
                            section += f"```\n{result_content}\n```\n"
                        elif btype == "tool_use":
                            name = block.get("name", "") if isinstance(block, dict) else getattr(block, "name", "")
                            inp = block.get("input", {}) if isinstance(block, dict) else getattr(block, "input", {})
                            section += f"\n### 🛠️ Tool Call: `{name}`" + "\n\n"
                            section += "**Input:**\n```json\n"
                            section += json.dumps(inp, ensure_ascii=False) + "\n```\n"
                        elif btype == "text":
                            text = block.get("text", "") if isinstance(block, dict) else getattr(block, "text", "")
                            if text:
                                section += f"\n### {icon}\n\n"
                                if role == "system":
                                    section += _blockquote(text) + "\n"
                                else:
                                    section += f"{text}\n"
                        else:
                            section += f"\n### {icon}\n\n[block type: {btype}]\n"
                else:
                    # Plain string content
                    section += f"\n### {icon}\n\n"
                    if role == "system":
                        section += _blockquote(raw_content) + "\n"
                    else:
                        section += f"{raw_content}\n"

        # Render tool calls
        if tool_calls:
            for i, tc in enumerate(tool_calls):
                name = tc.get("name", "unknown")
                tc_input = tc.get("input", {})
                tc_output = tc.get("output")
                tc_error = tc.get("error")

                # Tool call header (numbered if multiple)
                if len(tool_calls) > 1:
                    section += f"\n### 🛠️ Tool Call {i + 1}: `{name}`\n"
                else:
                    section += f"\n### 🛠️ Tool Call: `{name}`\n"

                # Input
                section += "\n**Input:**\n"
                section += "```json\n"
                if isinstance(tc_input, dict):
                    section += json.dumps(tc_input, ensure_ascii=False) + "\n"
                else:
                    section += str(tc_input) + "\n"
                section += "```\n"

                # Response or error
                if tc_error:
                    section += f"\n### ❌ Tool Error: `{name}`\n\n"
                    section += f"```\n{tc_error}\n```\n"
                elif tc_output is not None:
                    section += f"\n### ↩️ Tool Response: `{name}`\n\n"
                    section += f"```\n{tc_output}\n```\n"

        # Render response (after tool calls if present)
        if response is not None:
            if tool_calls:
                section += f"\n### 🤖 Assistant (continued)\n\n{response}\n"
            else:
                section += f"\n### 🤖 Assistant\n\n{response}\n"

        self._append(section)

    def close(
        self,
        summary: Optional[str] = None,
        input_tokens: Optional[int] = None,
        output_tokens: Optional[int] = None,
    ) -> dict:
        """Append Session End section to the Markdown file.

        Args:
            summary: Optional session summary.
            input_tokens: Override total input tokens.
            output_tokens: Override total output tokens.

        Returns:
            Dict with session end metadata.
        """
        ended_at = datetime.now(timezone.utc).isoformat()
        in_tok = input_tokens if input_tokens is not None else self._total_input_tokens
        out_tok = output_tokens if output_tokens is not None else self._total_output_tokens

        cost = None
        if self._model:
            cost = estimate_cost(self._model, in_tok, out_tok)
        cost_str = f"${cost:.4f}" if cost is not None else "N/A"

        footer = "\n---\n\n## Session End\n\n"
        footer += "| Field              | Value |\n"
        footer += "|--------------------|-------|\n"
        footer += f"| Ended              | {ended_at} |\n"
        footer += f"| Total Turns        | {self._turn_count} |\n"
        footer += f"| Input Tokens       | {in_tok:,} |\n"
        footer += f"| Output Tokens      | {out_tok:,} |\n"
        footer += f"| Estimated Cost     | {cost_str} |\n"
        if summary:
            footer += f"| Summary            | {summary} |\n"

        self._append(footer)

        return {
            "session_id": self._session_id,
            "ended_at": ended_at,
            "total_turns": self._turn_count,
            "input_tokens": in_tok,
            "output_tokens": out_tok,
            "estimated_cost": cost,
            "summary": summary,
        }

    # ------------------------------------------------------------------
    # OpenAI wrapper
    # ------------------------------------------------------------------
    def wrap_openai(self, client: Any) -> Any:
        """Return a lightweight proxy around an OpenAI client that auto-logs.

        The returned object delegates attribute access to the real client but
        intercepts ``client.chat.completions.create(...)`` to log every call.
        """
        try:
            import openai as _openai  # noqa: F401
        except ImportError:
            raise ImportError(
                "The openai package is required for wrap_openai. "
                "Install it with: pip install openai"
            )

        logger = self

        class _ChatCompletionsProxy:
            def __init__(self, real_completions: Any) -> None:
                self._real = real_completions

            def create(self, **kwargs: Any) -> Any:
                start = time.perf_counter()
                response_obj = None
                try:
                    response_obj = self._real.create(**kwargs)
                except Exception as exc:
                    logger.log_turn(
                        messages=kwargs.get("messages", []),
                        response=str(exc),
                    )
                    raise
                _log_openai_turn(kwargs, response_obj, logger)
                return response_obj

            def __getattr__(self, name: str) -> Any:
                return getattr(self._real, name)

        class _ChatProxy:
            def __init__(self, real_chat: Any) -> None:
                self.completions = _ChatCompletionsProxy(real_chat.completions)

            def __getattr__(self, name: str) -> Any:
                return getattr(self._real, name)

            @property
            def _real(self) -> Any:
                return client.chat

        class _OpenAIProxy:
            def __init__(self) -> None:
                self.chat = _ChatProxy(client.chat)

            def __getattr__(self, name: str) -> Any:
                return getattr(client, name)

        return _OpenAIProxy()

    # ------------------------------------------------------------------
    # Anthropic wrapper
    # ------------------------------------------------------------------
    def wrap_anthropic(self, client: Any) -> Any:
        """Return a lightweight proxy around an Anthropic client that auto-logs.

        Intercepts ``client.messages.create(...)`` to log every call.
        """
        try:
            import anthropic as _anthropic  # noqa: F401
        except ImportError:
            raise ImportError(
                "The anthropic package is required for wrap_anthropic. "
                "Install it with: pip install anthropic"
            )

        logger = self

        class _MessagesProxy:
            def __init__(self, real_messages: Any) -> None:
                self._real = real_messages

            def create(self, **kwargs: Any) -> Any:
                response_obj = None
                try:
                    response_obj = self._real.create(**kwargs)
                except Exception as exc:
                    logger.log_turn(
                        messages=kwargs.get("messages", []),
                        response=str(exc),
                    )
                    raise
                _log_anthropic_turn(kwargs, response_obj, logger)
                return response_obj

            def __getattr__(self, name: str) -> Any:
                return getattr(self._real, name)

        class _AnthropicProxy:
            def __init__(self) -> None:
                self.messages = _MessagesProxy(client.messages)

            def __getattr__(self, name: str) -> Any:
                return getattr(client, name)

        return _AnthropicProxy()


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _blockquote(text: str) -> str:
    """Wrap text in Markdown blockquote."""
    return "\n".join(f"> {line}" for line in text.split("\n"))


def _log_openai_turn(
    kwargs: dict, response: Any, logger: ModelLedger
) -> None:
    """Build and log a turn from an OpenAI response."""
    messages = kwargs.get("messages", [])

    response_text = ""
    tool_calls_list: list[dict] = []
    usage: dict = {}

    if response is not None:
        choice = response.choices[0] if response.choices else None
        if choice and choice.message:
            response_text = choice.message.content or ""
            if choice.message.tool_calls:
                for tc in choice.message.tool_calls:
                    tool_calls_list.append(
                        {"name": tc.function.name, "input": tc.function.arguments}
                    )
        if response.usage:
            usage = {
                "input_tokens": response.usage.prompt_tokens,
                "output_tokens": response.usage.completion_tokens,
            }

    logger.log_turn(
        messages=messages,
        response=response_text,
        tool_calls=tool_calls_list,
        usage=usage,
    )


def _log_anthropic_turn(
    kwargs: dict, response: Any, logger: ModelLedger
) -> None:
    """Build and log a turn from an Anthropic response.

    Captures:
    - system prompt (may be str or list of content blocks)
    - all messages including tool_result blocks from previous turns
    - tool_use blocks from the current response (with empty output placeholder)
    - assistant text response
    - token usage
    """
    messages = list(kwargs.get("messages", []))

    # Prepend system prompt — may be a plain string or a list of blocks
    system = kwargs.get("system")
    if system:
        if isinstance(system, str):
            system_content = system
        elif isinstance(system, list):
            # List of {type: "text", text: "..."} blocks
            system_content = "\n".join(
                (b.get("text", "") if isinstance(b, dict) else getattr(b, "text", ""))
                for b in system
            )
        else:
            system_content = str(system)
        messages = [{"role": "system", "content": system_content}] + messages

    response_text = ""
    tool_calls_list: list[dict] = []
    usage: dict = {}

    if response is not None:
        text_parts = []
        # Build a map of tool_use_id → result from messages (tool_result blocks)
        tool_results: dict[str, str] = {}
        for msg in kwargs.get("messages", []):
            raw = msg.get("content", [])
            if isinstance(raw, list):
                for block in raw:
                    btype = block.get("type") if isinstance(block, dict) else getattr(block, "type", None)
                    if btype == "tool_result":
                        tid = block.get("tool_use_id", "") if isinstance(block, dict) else getattr(block, "tool_use_id", "")
                        rc = block.get("content", "") if isinstance(block, dict) else getattr(block, "content", "")
                        if isinstance(rc, list):
                            rc = "\n".join(
                                (b.get("text", "") if isinstance(b, dict) else getattr(b, "text", ""))
                                for b in rc
                            )
                        tool_results[tid] = rc

        for block in response.content:
            btype = block.type if hasattr(block, "type") else block.get("type")
            if btype == "text":
                text_parts.append(block.text if hasattr(block, "text") else block.get("text", ""))
            elif btype == "tool_use":
                tid = block.id if hasattr(block, "id") else block.get("id", "")
                name = block.name if hasattr(block, "name") else block.get("name", "")
                inp = block.input if hasattr(block, "input") else block.get("input", {})
                entry = {"name": name, "input": inp}
                # Attach result if it arrived in the messages (previous-turn result)
                if tid in tool_results:
                    entry["output"] = tool_results[tid]
                tool_calls_list.append(entry)

        response_text = "\n".join(text_parts)
        if hasattr(response, "usage") and response.usage:
            usage = {
                "input_tokens": response.usage.input_tokens,
                "output_tokens": response.usage.output_tokens,
            }

    logger.log_turn(
        messages=messages,
        response=response_text,
        tool_calls=tool_calls_list,
        usage=usage,
    )
