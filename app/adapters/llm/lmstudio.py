"""LM Studio LLM adapter and output quality helpers."""

from __future__ import annotations

import re
import logging
import time
from pathlib import Path
from typing import Any, Optional

from langchain_openai import ChatOpenAI
from langchain_core.messages import BaseMessage

from app.config.settings import settings
log = logging.getLogger("pathfinder.llm")

_text_llms: dict[str, "LoggingChatOpenAI"] = {}
_vision_llm: Optional["LoggingChatOpenAI"] = None
_REASONING_KEYS = ("reasoning_content", "thinking", "reasoning", "refusal")
_DEBUG_LOG_PATH = Path(settings.LLM_DEBUG_LOG_PATH)
_SUPPORTED_REASONING_EFFORTS = {"none", "low", "medium", "high"}
_REASONING_ALIASES = {
    "off": "none",
    "false": "none",
    "on": "medium",
    "true": "medium",
    "1": "medium",
}


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

        if settings.LLM_DEBUG_LOG_ENABLED:
            _log_request(label, input)

        try:
            result = await super().ainvoke(input, config=config, **kwargs)
            if settings.LLM_DEBUG_LOG_ENABLED:
                _log_response(label, result, elapsed=time.time() - start)
            return result

        except Exception as exc:
            if settings.LLM_DEBUG_LOG_ENABLED:
                _log_error(label, exc, elapsed=time.time() - start)
            raise


def _log_request(label: str, input_val: Any) -> None:
    """Write a request trace entry for one LLM call."""
    prompt_summary = _summarize_input(input_val)
    _write_debug(f"[{label.upper()}] ── REQUEST ──\n{prompt_summary}\n")


def _log_response(label: str, result: BaseMessage, *, elapsed: float) -> None:
    """Write a response trace entry including useful metadata."""
    content = result.content if isinstance(result.content, str) else str(result.content)
    extra_str = "\n".join(_response_debug_lines(result))
    _write_debug(
        f"[{label.upper()}] ── RESPONSE ({elapsed:.1f}s, {len(content)} chars) ──\n"
        f"content: {_trunc(content, 2000)}\n"
        f"{extra_str}\n"
        f"{'─' * 60}\n"
    )


def _log_error(label: str, exc: Exception, *, elapsed: float) -> None:
    """Write an error trace entry for one failed LLM call."""
    _write_debug(
        f"[{label.upper()}] ── ERROR ({elapsed:.1f}s) ──\n"
        f"{type(exc).__name__}: {exc}\n"
        f"{'─' * 60}\n"
    )


def _response_debug_lines(result: BaseMessage) -> list[str]:
    """Return compact debug lines describing one model response."""
    lines: list[str] = []
    additional_kwargs = getattr(result, "additional_kwargs", None)
    if additional_kwargs:
        lines.append(f"additional_kwargs keys: {list(additional_kwargs.keys())}")
        for key in _REASONING_KEYS:
            if key in additional_kwargs:
                value = additional_kwargs[key]
                lines.append(f"  {key} ({type(value).__name__}): {_trunc(str(value), 1500)}")
    response_metadata = getattr(result, "response_metadata", None)
    if response_metadata:
        lines.append(f"response_metadata: {_trunc(str(response_metadata), 500)}")
    tool_calls = getattr(result, "tool_calls", None)
    if tool_calls:
        lines.append(f"tool_calls: {tool_calls}")
    lines.append(f"content type: {type(result.content).__name__}")
    if isinstance(result.content, list):
        lines.append(f"content list: {_trunc(str(result.content), 1000)}")
    return lines


def _summarize_input(input_val: Any) -> str:
    """Build a readable summary of the LLM input messages."""
    lines = []
    messages = input_val if isinstance(input_val, (list, tuple)) else [input_val]
    for msg in messages:
        if isinstance(msg, dict):
            role = msg.get("role", "?")
            content = msg.get("content", "")
            if isinstance(content, list):
                content = _summarize_multimodal_content(content)
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


def _summarize_multimodal_content(parts: list[Any]) -> str:
    """Summarize multimodal content for log readability without dumping payloads."""
    text_parts = [
        part.get("text", "")
        for part in parts
        if isinstance(part, dict) and part.get("type") == "text"
    ]
    has_image = any(
        part.get("type") == "image_url"
        for part in parts
        if isinstance(part, dict)
    )
    text_summary = " ".join(text_parts).strip()
    if has_image:
        return f"{text_summary} [+image]".strip()
    return text_summary


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


# ── LLM Singletons ─────────────────────────────────────────────────
def _build_llm(
    *,
    label: str,
    model: str,
    model_kwargs: dict[str, Any] | None = None,
    extra_body: dict[str, Any] | None = None,
) -> LoggingChatOpenAI:
    """Build one LM Studio client with the shared connection settings."""
    kwargs: dict[str, Any] = {
        "llm_label": label,
        "model": model,
        "base_url": settings.LLM_BASE_URL,
        "api_key": settings.LLM_API_KEY,
    }
    if model_kwargs:
        kwargs["model_kwargs"] = model_kwargs
    if extra_body:
        kwargs["extra_body"] = extra_body
    return LoggingChatOpenAI(**kwargs)


def _normalize_reasoning_effort(model: str, reasoning: str | None) -> str:
    """Map app-level reasoning labels to what the configured model accepts."""
    reasoning_key = str(reasoning or "medium").strip().lower() or "medium"

    # Older LM Studio/Gemma flows sometimes used a binary on/off toggle.
    # The current OpenAI-compatible API only accepts the standard effort enum.
    if reasoning_key in _REASONING_ALIASES:
        return _REASONING_ALIASES[reasoning_key]

    if reasoning_key in _SUPPORTED_REASONING_EFFORTS:
        return reasoning_key

    log.warning(
        "Unsupported reasoning value %r for model %r; falling back to 'medium'.",
        reasoning_key,
        model,
    )
    return "medium"


def _is_gemma_4_model(model: str) -> bool:
    """Return True when the configured text model is from the Gemma 4 family."""
    lowered_model = str(model or "").strip().lower()
    return "gemma-4" in lowered_model


def _build_reasoning_config(model: str, reasoning: str | None) -> dict[str, Any]:
    """Build model-specific reasoning settings for the current text model."""
    reasoning_key = _normalize_reasoning_effort(model, reasoning)

    if _is_gemma_4_model(model):
        # Gemma 4 exposes thinking as a boolean prompt-template toggle rather
        # than an OpenAI-style reasoning_effort enum.
        enable_thinking = reasoning_key != "none"
        return {
            "cache_key": f"gemma4:{'thinking' if enable_thinking else 'no-thinking'}",
            "extra_body": {
                "chat_template_kwargs": {"enable_thinking": enable_thinking},
            },
        }

    return {
        "cache_key": reasoning_key,
        "model_kwargs": {"reasoning_effort": reasoning_key},
    }


def get_text_llm(reasoning: str | None = None) -> LoggingChatOpenAI:
    """Return a cached text LLM for the requested reasoning setting."""
    config = _build_reasoning_config(settings.LLM_MODEL, reasoning)
    cache_key = str(config["cache_key"])
    build_kwargs: dict[str, Any] = {}
    if "model_kwargs" in config:
        build_kwargs["model_kwargs"] = config["model_kwargs"]
    if "extra_body" in config:
        build_kwargs["extra_body"] = config["extra_body"]

    if cache_key not in _text_llms:
        _text_llms[cache_key] = _build_llm(
            label=f"text:{cache_key}",
            model=settings.LLM_MODEL,
            **build_kwargs,
        )
    return _text_llms[cache_key]


def get_vision_llm() -> LoggingChatOpenAI:
    """Return the singleton vision LLM."""
    global _vision_llm
    if _vision_llm is None:
        _vision_llm = _build_llm(label="vision", model=settings.VISION_MODEL)
    return _vision_llm


# ── Output Quality Guards ───────────────────────────────────────────
# Control-token patterns that indicate the model hallucinated tool use
# or produced internal formatting instead of a real answer.
_GARBAGE_PATTERNS = (
    "<|",       # Model control tokens (e.g. <|channel|>, <|im_end|>)
    "<|im_",    # Common in Qwen/ChatML models
    "```json",  # Sometimes the model wraps its entire answer in a code block
)

def is_garbage_output(text: str) -> bool:
    """Return True if the LLM output looks like garbage rather than a real answer.

    Detects:
    - Model control tokens (``<|channel|>``, ``<|im_end|>``, etc.)
    - Outputs that are entirely JSON when prose was expected
    """
    if not text or not text.strip():
        return True
    stripped = text.strip()
    for pattern in _GARBAGE_PATTERNS:
        if pattern in stripped:
            log.warning("Garbage pattern %r detected in output: %s", pattern, stripped[:120])
            return True
    if (stripped.startswith("{") and stripped.endswith("}")) or (stripped.startswith("[") and stripped.endswith("]")):
        log.debug("Output appears to be raw structured data, not prose: %s", stripped[:120])
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
