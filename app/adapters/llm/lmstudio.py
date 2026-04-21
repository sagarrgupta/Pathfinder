"""LM Studio chat-model adapter.

LM Studio hosts a local model behind an OpenAI-compatible API, so we can
reuse `langchain-openai`'s `ChatOpenAI` client and just point it at LM
Studio's URL. Every node that calls an LLM (orchestrator, specialist,
ingester, doc analyst) pulls its client from here.

Two extras live on top of plain `ChatOpenAI`:

1. `LoggingChatOpenAI` — a thin subclass that writes every request /
   response / error to `settings.LLM_DEBUG_LOG_PATH` when debug logging
   is on. This is invaluable when something looks off about an answer;
   the raw LLM trace is sitting right next to the replay artifact.

2. Reasoning effort handling — different model families expose
   "thinking" differently. The OpenAI-style API wants a
   `reasoning_effort` enum, while Gemma 4 wants a boolean template
   toggle. `_build_reasoning_config` hides that split so the rest of
   the app just passes a label like "low" / "medium" / "high".

Clients are cached per reasoning label so we don't rebuild them on
every node invocation.
"""

from __future__ import annotations

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
    """`ChatOpenAI` with an extra debug-log side effect.

    Every `ainvoke` writes a request/response pair to the debug log
    file so we can reconstruct exactly what the LLM saw and said on any
    given turn. Logging is gated by `settings.LLM_DEBUG_LOG_ENABLED` so
    it can be switched off for production.
    """

    _llm_label: str = "text"

    def __init__(self, llm_label: str = "text", **kwargs: Any):
        super().__init__(**kwargs)
        # Pydantic models forbid free attribute assignment, so stash the
        # label directly on the instance dict instead.
        object.__setattr__(self, "_llm_label", llm_label)

    async def ainvoke(self, input: Any, config: Any = None, **kwargs: Any) -> BaseMessage:
        """LangChain's async entry point — we wrap it to emit debug trace."""
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
    """Dump the outgoing prompt (truncated per message) to the debug log."""
    prompt_summary = _summarize_input(input_val)
    _write_debug(f"[{label.upper()}] ── REQUEST ──\n{prompt_summary}\n")


def _log_response(label: str, result: BaseMessage, *, elapsed: float) -> None:
    """Dump the model's reply plus handy metadata (tool calls, reasoning)."""
    content = result.content if isinstance(result.content, str) else str(result.content)
    extra_str = "\n".join(_response_debug_lines(result))
    _write_debug(
        f"[{label.upper()}] ── RESPONSE ({elapsed:.1f}s, {len(content)} chars) ──\n"
        f"content: {_trunc(content, 2000)}\n"
        f"{extra_str}\n"
        f"{'─' * 60}\n"
    )


def _log_error(label: str, exc: Exception, *, elapsed: float) -> None:
    """Record a failed call — type, message, and how long we waited before it blew up."""
    _write_debug(
        f"[{label.upper()}] ── ERROR ({elapsed:.1f}s) ──\n"
        f"{type(exc).__name__}: {exc}\n"
        f"{'─' * 60}\n"
    )


def _response_debug_lines(result: BaseMessage) -> list[str]:
    """Pull tool calls, reasoning fields, and content type into debug-log lines."""
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
    """Turn a heterogeneous list of messages into readable debug lines.

    Accepts dicts, LangChain `BaseMessage`, and plain `(role, content)`
    tuples — whichever shape the caller happened to build.
    """
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
    """Collapse vision messages to "<text> [+image]" instead of base64 blobs.

    Image payloads are huge and useless in logs, so we just note that
    one was attached.
    """
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
    """Clip long strings for the log with a "[N chars total]" suffix."""
    if len(text) <= max_len:
        return text
    return text[:max_len] + f"... [{len(text)} chars total]"


def _write_debug(text: str) -> None:
    """Append one timestamped block to the debug log file.

    Swallows all I/O errors: debug logging is strictly best-effort and
    must never take down a real request.
    """
    try:
        _DEBUG_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        ts = time.strftime("%H:%M:%S")
        with open(_DEBUG_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(f"[{ts}] {text}\n")
    except Exception:
        pass


def _build_llm(
    *,
    label: str,
    model: str,
    model_kwargs: dict[str, Any] | None = None,
    extra_body: dict[str, Any] | None = None,
) -> LoggingChatOpenAI:
    """Construct one LM Studio client with the shared URL + API key.

    When `LLM_REQUIRE_EXACT_MODEL` is off we send the magic value
    `local-model` so LM Studio routes the call to whichever model is
    currently loaded, regardless of what `settings.LLM_MODEL` says.
    """
    api_model = model if settings.LLM_REQUIRE_EXACT_MODEL else "local-model"

    kwargs: dict[str, Any] = {
        "llm_label": label,
        "model": api_model,
        "base_url": settings.LLM_BASE_URL,
        "api_key": settings.LLM_API_KEY,
    }
    if model_kwargs:
        kwargs["model_kwargs"] = model_kwargs
    if extra_body:
        kwargs["extra_body"] = extra_body
    return LoggingChatOpenAI(**kwargs)


def _normalize_reasoning_effort(model: str, reasoning: str | None) -> str:
    """Translate a user-facing reasoning label to a provider-accepted one.

    The UI exposes simple words (on/off/low/medium/high). The provider
    expects one of {none, low, medium, high}. We map aliases and fall
    back to "medium" with a warning if the value is unknown.
    """
    reasoning_key = str(reasoning or "medium").strip().lower() or "medium"

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
    """Detect Gemma 4 by name — it needs the template-toggle path, not the enum."""
    lowered_model = str(model or "").strip().lower()
    return "gemma-4" in lowered_model


def _build_reasoning_config(model: str, reasoning: str | None) -> dict[str, Any]:
    """Return the right per-model knobs for the requested reasoning level.

    For OpenAI-style models: set `reasoning_effort` in `model_kwargs`.
    For Gemma 4: flip an `enable_thinking` boolean on the chat template.
    The returned `cache_key` is what we key the client cache on so each
    distinct reasoning config gets its own reusable client.
    """
    reasoning_key = _normalize_reasoning_effort(model, reasoning)

    if _is_gemma_4_model(model):
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
    """Main entry point — hand back a chat client tuned for this reasoning level.

    Clients are cached per reasoning config so repeated calls at the
    same level reuse the same HTTP session. This is what every LangGraph
    node ends up calling when it needs an LLM.
    """
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
    """Return the shared vision-capable model client.

    Used by `doc_analyst` when an uploaded file contains images that
    need OCR / captioning. Singleton because we only ever need one.
    """
    global _vision_llm
    if _vision_llm is None:
        _vision_llm = _build_llm(label="vision", model=settings.VISION_MODEL)
    return _vision_llm
