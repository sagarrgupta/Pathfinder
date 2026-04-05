"""LM Studio LLM adapter.

Provides singleton ChatOpenAI instances for text and vision models
running on LM Studio's OpenAI-compatible API.

Includes a post-generation repetition guard that detects and truncates
outputs where the model gets stuck in a loop.

Debug logging: every LLM call is written to data/llm_debug.log with
timestamps, prompts (truncated), full responses, and elapsed time.
"""

from __future__ import annotations

import json
import os
import re
import logging
import time
from pathlib import Path
from typing import Any, Optional, Sequence

from langchain_openai import ChatOpenAI
from langchain_core.messages import BaseMessage, AIMessage

from app.config.settings import settings

log = logging.getLogger("pathfinder.llm")

_text_llm: Optional["LoggingChatOpenAI"] = None
_vision_llm: Optional["LoggingChatOpenAI"] = None
_json_llm: Optional["LoggingChatOpenAI"] = None

# Debug log file path
_DEBUG_LOG_PATH = Path("data/llm_debug.log")


# ── Logging wrapper ─────────────────────────────────────────────────


class LoggingChatOpenAI(ChatOpenAI):
    """ChatOpenAI subclass that logs every call to a debug file."""

    _llm_label: str = "text"

    def __init__(self, llm_label: str = "text", **kwargs: Any):
        super().__init__(**kwargs)
        # Store label using object __dict__ to avoid pydantic issues
        object.__setattr__(self, "_llm_label", llm_label)

    async def ainvoke(self, input: Any, config: Any = None, **kwargs: Any) -> BaseMessage:
        """Wrap ainvoke with debug logging."""
        label = object.__getattribute__(self, "_llm_label")
        start = time.time()

        # Extract prompt info for logging
        prompt_summary = _summarize_input(input)

        _write_debug(f"[{label.upper()}] ── REQUEST ──\n{prompt_summary}\n")

        try:
            result = await super().ainvoke(input, config=config, **kwargs)
            elapsed = time.time() - start

            content = result.content if isinstance(result.content, str) else str(result.content)

            # Log full response structure to diagnose empty content
            extra_info = []
            if hasattr(result, "additional_kwargs") and result.additional_kwargs:
                extra_info.append(f"additional_kwargs keys: {list(result.additional_kwargs.keys())}")
                # Check for thinking/reasoning content
                for key in ("reasoning_content", "thinking", "reasoning", "refusal"):
                    if key in result.additional_kwargs:
                        val = result.additional_kwargs[key]
                        extra_info.append(f"  {key} ({type(val).__name__}): {_trunc(str(val), 1500)}")
            if hasattr(result, "response_metadata") and result.response_metadata:
                extra_info.append(f"response_metadata: {_trunc(str(result.response_metadata), 500)}")
            if hasattr(result, "tool_calls") and result.tool_calls:
                extra_info.append(f"tool_calls: {result.tool_calls}")
            extra_info.append(f"content type: {type(result.content).__name__}")
            if isinstance(result.content, list):
                extra_info.append(f"content list: {_trunc(str(result.content), 1000)}")
            extra_str = "\n".join(extra_info)

            _write_debug(
                f"[{label.upper()}] ── RESPONSE ({elapsed:.1f}s, {len(content)} chars) ──\n"
                f"content: {_trunc(content, 2000)}\n"
                f"{extra_str}\n"
                f"{'─' * 60}\n"
            )
            return result

        except Exception as exc:
            message = str(exc)
            if "context length" in message.lower() or "tokens to keep" in message.lower():
                _write_debug(f"[{label.upper()}] context-length error; retrying with trimmed prompt\n")
                trimmed_input = _trim_messages_for_retry(input)
                result = await super().ainvoke(trimmed_input, config=config, **kwargs)
                elapsed = time.time() - start
                content = result.content if isinstance(result.content, str) else str(result.content)
                _write_debug(
                    f"[{label.upper()}] ── RESPONSE AFTER RETRY ({elapsed:.1f}s, {len(content)} chars) ──\n"
                    f"content: {_trunc(content, 2000)}\n"
                    f"{'─' * 60}\n"
                )
                return result
            elapsed = time.time() - start
            _write_debug(
                f"[{label.upper()}] ── ERROR ({elapsed:.1f}s) ──\n"
                f"{type(exc).__name__}: {exc}\n"
                f"{'─' * 60}\n"
            )
            raise


def _summarize_input(input_val: Any) -> str:
    """Build a readable summary of the LLM input messages."""
    lines = []
    messages = input_val if isinstance(input_val, (list, tuple)) else [input_val]
    for msg in messages:
        if isinstance(msg, dict):
            role = msg.get("role", "?")
            content = msg.get("content", "")
            if isinstance(content, list):
                # Multimodal content (vision)
                text_parts = [p.get("text", "") for p in content if isinstance(p, dict) and p.get("type") == "text"]
                content = " ".join(text_parts) + " [+image]" if any(p.get("type") == "image_url" for p in content if isinstance(p, dict)) else " ".join(text_parts)
            lines.append(f"  {role}: {_trunc(str(content), 500)}")
        elif isinstance(msg, BaseMessage):
            role = msg.type
            content = msg.content if isinstance(msg.content, str) else str(msg.content)
            lines.append(f"  {role}: {_trunc(content, 500)}")
        elif isinstance(msg, tuple) and len(msg) == 2:
            lines.append(f"  {msg[0]}: {_trunc(str(msg[1]), 500)}")
        else:
            lines.append(f"  ?: {_trunc(str(msg), 300)}")
    return "\n".join(lines)


def _trunc(text: str, max_len: int) -> str:
    """Truncate text for logging."""
    if len(text) <= max_len:
        return text
    return text[:max_len] + f"... [{len(text)} chars total]"


def _write_debug(text: str) -> None:
    """Append a timestamped entry to the debug log file."""
    try:
        _DEBUG_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        ts = time.strftime("%H:%M:%S")
        with open(_DEBUG_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(f"[{ts}] {text}\n")
    except Exception:
        pass  # Never let debug logging break the app


def _shorten_message_content(content: Any, *, limit: int) -> Any:
    if isinstance(content, str):
        return _trunc(content, limit)
    return content


def _trim_messages_for_retry(input_val: Any) -> Any:
    messages = input_val if isinstance(input_val, list) else [input_val]
    trimmed = []
    for index, msg in enumerate(messages):
        limit = 1200 if index == 0 else 2200
        if isinstance(msg, BaseMessage):
            trimmed.append(msg.__class__(content=_shorten_message_content(msg.content, limit=limit)))
        elif isinstance(msg, dict):
            copied = dict(msg)
            copied["content"] = _shorten_message_content(copied.get("content", ""), limit=limit)
            trimmed.append(copied)
        elif isinstance(msg, tuple) and len(msg) == 2:
            trimmed.append((msg[0], _shorten_message_content(msg[1], limit=limit)))
        else:
            trimmed.append(msg)
    return trimmed if isinstance(input_val, list) else trimmed[0]


# ── LLM Singletons ─────────────────────────────────────────────────


def get_text_llm() -> LoggingChatOpenAI:
    """Return the singleton text LLM (gpt-oss-20b)."""
    global _text_llm
    if _text_llm is None:
        _text_llm = LoggingChatOpenAI(
            llm_label="text",
            model=settings.LLM_MODEL,
            base_url=settings.LLM_BASE_URL,
            api_key=settings.LLM_API_KEY,
            temperature=settings.LLM_TEMPERATURE,
            max_tokens=settings.LLM_MAX_TOKENS,
            request_timeout=settings.LLM_REQUEST_TIMEOUT,
            frequency_penalty=settings.LLM_FREQUENCY_PENALTY,
            presence_penalty=settings.LLM_PRESENCE_PENALTY,
        )
    return _text_llm


def get_vision_llm() -> LoggingChatOpenAI:
    """Return the singleton vision LLM (qwen3-vl-8b)."""
    global _vision_llm
    if _vision_llm is None:
        _vision_llm = LoggingChatOpenAI(
            llm_label="vision",
            model=settings.VISION_MODEL,
            base_url=settings.LLM_BASE_URL,
            api_key=settings.LLM_API_KEY,
            temperature=0.1,
            max_tokens=settings.LLM_MAX_TOKENS,
            request_timeout=settings.LLM_REQUEST_TIMEOUT,
            frequency_penalty=settings.LLM_FREQUENCY_PENALTY,
            presence_penalty=settings.LLM_PRESENCE_PENALTY,
        )
    return _vision_llm


def get_json_llm() -> LoggingChatOpenAI:
    """Return a text LLM configured for strict JSON-object outputs."""
    global _json_llm
    if _json_llm is None:
        _json_llm = LoggingChatOpenAI(
            llm_label="json",
            model=settings.LLM_MODEL,
            base_url=settings.LLM_BASE_URL,
            api_key=settings.LLM_API_KEY,
            temperature=0.0,
            max_tokens=settings.LLM_MAX_TOKENS,
            request_timeout=settings.LLM_REQUEST_TIMEOUT,
            frequency_penalty=settings.LLM_FREQUENCY_PENALTY,
            presence_penalty=settings.LLM_PRESENCE_PENALTY,
        )
    return _json_llm

# ── Output Quality Guards ───────────────────────────────────────────


# Control-token patterns that indicate the model hallucinated tool use
# or produced internal formatting instead of a real answer.
_GARBAGE_PATTERNS = (
    "<|",       # Model control tokens (e.g. <|channel|>, <|im_end|>)
    "<|im_",    # Common in Qwen/ChatML models
    "```json",  # Sometimes the model wraps its entire answer in a code block
)

# Minimum length for a "real" prose answer from an advisory agent
_MIN_ANSWER_LEN = 80


def is_garbage_output(text: str) -> bool:
    """Return True if the LLM output looks like garbage rather than a real answer.

    Detects:
    - Model control tokens (``<|channel|>``, ``<|im_end|>``, etc.)
    - Extremely short outputs (< 80 chars) that are not valid prose
    - Outputs that are entirely JSON when prose was expected
    """
    if not text or not text.strip():
        return True
    stripped = text.strip()
    if len(stripped) < _MIN_ANSWER_LEN:
        # Very short — could still be valid for JSON-only agents, but
        # advisory agents should produce longer answers.
        log.debug("Output too short (%d chars): %s", len(stripped), stripped[:100])
        return True
    for pattern in _GARBAGE_PATTERNS:
        if pattern in stripped:
            log.warning("Garbage pattern %r detected in output: %s", pattern, stripped[:120])
            return True
    return False


# ── Repetition Guard ────────────────────────────────────────────────


def strip_repetition(text: str, min_phrase_len: int = 20, max_repeats: int = 2) -> str:
    """Detect and truncate text where the model fell into a repetition loop.

    Scans for any phrase of at least *min_phrase_len* characters that repeats
    more than *max_repeats* consecutive times.  When found, keeps only the
    first *max_repeats* occurrences and appends a brief note.

    This is a safety net — the frequency/presence penalties should prevent
    most loops, but local models can still occasionally get stuck.
    """
    if len(text) < min_phrase_len * (max_repeats + 1):
        return text

    # Look for a repeated block: capture a chunk and see if it repeats
    # Pattern: (.{20,200}?)\1{2,}  — a phrase repeated 3+ times
    pattern = re.compile(r"(.{" + str(min_phrase_len) + r"," + str(min(200, len(text))) + r"?})\1{" + str(max_repeats) + r",}", re.DOTALL)
    match = pattern.search(text)

    if match:
        # Keep everything up to the start of the first repetition occurrence,
        # plus one clean copy of the repeated phrase
        repeated_phrase = match.group(1)
        cut_point = match.start() + len(repeated_phrase)
        truncated = text[:cut_point].rstrip()
        log.warning(
            "Repetition detected (%d-char phrase repeated). Truncated from %d to %d chars.",
            len(repeated_phrase), len(text), len(truncated),
        )
        return truncated

    return text
