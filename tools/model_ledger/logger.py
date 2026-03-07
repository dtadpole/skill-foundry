"""Core ModelLedger — writes ModelLedgerRecords to JSONL and wraps LLM clients."""

from __future__ import annotations

import os
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from .record import ModelLedgerRecord
from .pricing import estimate_cost

_DEFAULT_DIR = Path.home() / ".skillfoundry" / "audit"


class ModelLedger:
    """Thread-safe logger that appends ModelLedgerRecords to daily JSONL files.

    Args:
        log_dir: Directory for log files. Defaults to ~/.skillfoundry/audit/
        session_id: Optional session identifier attached to every record.
        caller: Optional caller name attached to every record.
    """

    def __init__(
        self,
        log_dir: str | Path | None = None,
        session_id: Optional[str] = None,
        caller: Optional[str] = None,
    ) -> None:
        self.log_dir = Path(log_dir) if log_dir else _DEFAULT_DIR
        self.session_id = session_id
        self.caller = caller
        self._lock = threading.Lock()

    def _log_path(self) -> Path:
        """Return today's log file path."""
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        return self.log_dir / f"llm_{today}.jsonl"

    def log(self, record: ModelLedgerRecord) -> None:
        """Append a single ModelLedgerRecord to today's JSONL log file."""
        path = self._log_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        line = record.to_jsonl() + "\n"
        with self._lock:
            with open(path, "a", encoding="utf-8") as f:
                f.write(line)

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
                error_info: dict = {}
                response_obj = None
                try:
                    response_obj = self._real.create(**kwargs)
                except Exception as exc:
                    elapsed = (time.perf_counter() - start) * 1000
                    error_info = {
                        "status": "error",
                        "error_type": type(exc).__name__,
                        "error_message": str(exc),
                    }
                    record = _build_openai_record(
                        kwargs, None, elapsed, error_info, logger
                    )
                    logger.log(record)
                    raise
                elapsed = (time.perf_counter() - start) * 1000
                record = _build_openai_record(
                    kwargs, response_obj, elapsed, error_info, logger
                )
                logger.log(record)
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
                start = time.perf_counter()
                error_info: dict = {}
                response_obj = None
                try:
                    response_obj = self._real.create(**kwargs)
                except Exception as exc:
                    elapsed = (time.perf_counter() - start) * 1000
                    error_info = {
                        "status": "error",
                        "error_type": type(exc).__name__,
                        "error_message": str(exc),
                    }
                    record = _build_anthropic_record(
                        kwargs, None, elapsed, error_info, logger
                    )
                    logger.log(record)
                    raise
                elapsed = (time.perf_counter() - start) * 1000
                record = _build_anthropic_record(
                    kwargs, response_obj, elapsed, error_info, logger
                )
                logger.log(record)
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
# Helpers to build records from provider-specific shapes
# ------------------------------------------------------------------

def _build_openai_record(
    kwargs: dict,
    response: Any,
    latency_ms: float,
    error_info: dict,
    logger: ModelLedger,
) -> ModelLedgerRecord:
    model = kwargs.get("model", "")
    messages = kwargs.get("messages", [])

    system_prompt = None
    conversation: list[dict] = []
    for msg in messages:
        if msg.get("role") == "system":
            system_prompt = msg.get("content", "")
        else:
            conversation.append({"role": msg.get("role"), "content": msg.get("content")})

    response_text = ""
    tool_calls_list: list[dict] = []
    prompt_tokens = None
    completion_tokens = None
    total_tokens = None

    if response is not None:
        choice = response.choices[0] if response.choices else None
        if choice and choice.message:
            response_text = choice.message.content or ""
            if choice.message.tool_calls:
                for tc in choice.message.tool_calls:
                    tool_calls_list.append(
                        {"name": tc.function.name, "arguments": tc.function.arguments}
                    )
        if response.usage:
            prompt_tokens = response.usage.prompt_tokens
            completion_tokens = response.usage.completion_tokens
            total_tokens = response.usage.total_tokens

    extra = {}
    for k in ("frequency_penalty", "presence_penalty", "seed", "stop", "logprobs"):
        if k in kwargs:
            extra[k] = kwargs[k]

    cost = None
    if prompt_tokens is not None and completion_tokens is not None:
        cost = estimate_cost(model, prompt_tokens, completion_tokens)

    return ModelLedgerRecord(
        request_id=str(uuid.uuid4()),
        session_id=logger.session_id,
        caller=logger.caller,
        timestamp=datetime.now(timezone.utc).isoformat(),
        latency_ms=round(latency_ms, 2),
        provider="openai",
        model=model,
        temperature=kwargs.get("temperature"),
        max_tokens=kwargs.get("max_tokens"),
        top_p=kwargs.get("top_p"),
        extra_params=extra,
        system_prompt=system_prompt,
        messages=conversation,
        response=response_text,
        tool_calls=tool_calls_list,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=total_tokens,
        cost_usd=cost,
        **(error_info if error_info else {"status": "success"}),
    )


def _build_anthropic_record(
    kwargs: dict,
    response: Any,
    latency_ms: float,
    error_info: dict,
    logger: ModelLedger,
) -> ModelLedgerRecord:
    model = kwargs.get("model", "")
    messages = kwargs.get("messages", [])
    system_prompt = kwargs.get("system")

    conversation: list[dict] = []
    for msg in messages:
        conversation.append({"role": msg.get("role"), "content": msg.get("content")})

    response_text = ""
    tool_calls_list: list[dict] = []
    prompt_tokens = None
    completion_tokens = None
    total_tokens = None

    if response is not None:
        text_parts = []
        for block in response.content:
            if block.type == "text":
                text_parts.append(block.text)
            elif block.type == "tool_use":
                tool_calls_list.append(
                    {"name": block.name, "arguments": block.input}
                )
        response_text = "\n".join(text_parts)
        if response.usage:
            prompt_tokens = response.usage.input_tokens
            completion_tokens = response.usage.output_tokens
            total_tokens = (prompt_tokens or 0) + (completion_tokens or 0)

    extra = {}
    for k in ("stop_sequences", "metadata"):
        if k in kwargs:
            extra[k] = kwargs[k]

    cost = None
    if prompt_tokens is not None and completion_tokens is not None:
        cost = estimate_cost(model, prompt_tokens, completion_tokens)

    return ModelLedgerRecord(
        request_id=str(uuid.uuid4()),
        session_id=logger.session_id,
        caller=logger.caller,
        timestamp=datetime.now(timezone.utc).isoformat(),
        latency_ms=round(latency_ms, 2),
        provider="anthropic",
        model=model,
        temperature=kwargs.get("temperature"),
        max_tokens=kwargs.get("max_tokens"),
        top_p=kwargs.get("top_p"),
        extra_params=extra,
        system_prompt=system_prompt,
        messages=conversation,
        response=response_text,
        tool_calls=tool_calls_list,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=total_tokens,
        cost_usd=cost,
        **(error_info if error_info else {"status": "success"}),
    )
