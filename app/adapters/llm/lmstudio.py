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

import httpx
from langchain_openai import ChatOpenAI
from langchain_core.messages import BaseMessage, AIMessage

from app.config.settings import settings

log = logging.getLogger("pathfinder.llm")

_text_llm: Optional["LoggingChatOpenAI"] = None
_vision_llm: Optional["LoggingChatOpenAI"] = None
_text_model_name: Optional[str] = None
_vision_model_name: Optional[str] = None
_model_cache: dict[str, Any] = {"ts": 0.0, "models": []}
_manual_text_model: Optional[str] = None
_available_model_cache: dict[str, Any] = {"ts": 0.0, "models": []}

_MODEL_ALIASES: dict[str, list[str]] = {
    "openai/gpt-oss-20b": [
        "openai/gpt-oss-20b",
        "gpt-oss-20b",
    ],
    "Qwen3-14B-MLX-8bit": [
        "Qwen3-14B-MLX-8bit",
        "qwen/qwen3-14b",
        "qwen3-14b",
        "lmstudio-community/Qwen3-14B-MLX-8bit",
        "lmstudio-community/qwen3-14b-mlx-8bit",
    ],
}

# Debug log file path
_DEBUG_LOG_PATH = Path("data/llm_debug.log")
_MODEL_CACHE_TTL_SECONDS = 5.0


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


# ── LLM Singletons ─────────────────────────────────────────────────


def get_text_llm() -> LoggingChatOpenAI:
    """Return the singleton text LLM using the currently loaded LM Studio model if available."""
    global _text_llm, _text_model_name
    requested_model = _resolve_requested_text_model()
    model_name = _ensure_lmstudio_model_loaded(requested_model)
    if _text_llm is None or _text_model_name != model_name:
        _text_llm = LoggingChatOpenAI(
            llm_label="text",
            model=model_name,
            base_url=settings.LLM_BASE_URL,
            api_key=settings.LLM_API_KEY,
            temperature=settings.LLM_TEMPERATURE,
            max_tokens=settings.LLM_MAX_TOKENS,
            request_timeout=settings.LLM_REQUEST_TIMEOUT,
            model_kwargs={
                "frequency_penalty": settings.LLM_FREQUENCY_PENALTY,
                "presence_penalty": settings.LLM_PRESENCE_PENALTY,
            },
        )
        _text_model_name = model_name
    return _text_llm


def get_vision_llm() -> LoggingChatOpenAI:
    """Return the singleton vision LLM, preferring a loaded multimodal model when available."""
    global _vision_llm, _vision_model_name
    requested_model = _resolve_lmstudio_model(kind="vision")
    model_name = _ensure_lmstudio_model_loaded(requested_model)
    if _vision_llm is None or _vision_model_name != model_name:
        _vision_llm = LoggingChatOpenAI(
            llm_label="vision",
            model=model_name,
            base_url=settings.LLM_BASE_URL,
            api_key=settings.LLM_API_KEY,
            temperature=0.1,
            max_tokens=settings.LLM_MAX_TOKENS,
            request_timeout=settings.LLM_REQUEST_TIMEOUT,
            model_kwargs={
                "frequency_penalty": settings.LLM_FREQUENCY_PENALTY,
                "presence_penalty": settings.LLM_PRESENCE_PENALTY,
            },
        )
        _vision_model_name = model_name
    return _vision_llm


def _resolve_lmstudio_model(kind: str = "text") -> str:
    """Pick a loaded LM Studio model when available, else fall back to configured defaults."""
    models = _get_loaded_lmstudio_models()
    if not models:
        fallback = settings.VISION_MODEL if kind == "vision" else (_manual_text_model or settings.LLM_MODEL)
        log.info("LM Studio returned no loaded models; falling back to configured %s model %s", kind, fallback)
        return fallback

    if kind == "vision":
        for model_id in models:
            lowered = model_id.lower()
            if any(token in lowered for token in ("vision", "vl", "llava", "minicpm-v", "qwen2.5-vl", "qwen3-vl")):
                return model_id
        fallback = settings.VISION_MODEL
        if fallback in models:
            return fallback
        return models[0]

    preferred = _manual_text_model or settings.LLM_MODEL
    if preferred in models:
        return preferred
    return models[0]


def _resolve_requested_text_model() -> str:
    """Resolve the preferred text model to an LM Studio model key."""
    requested = _manual_text_model or settings.LLM_MODEL
    for candidate in _candidate_model_keys(requested):
        resolved = _resolve_model_key(candidate)
        if resolved:
            return resolved
    return requested


def _get_loaded_lmstudio_models() -> list[str]:
    """Fetch currently loaded LM Studio model ids with a short cache."""
    now = time.time()
    if now - _model_cache["ts"] < _MODEL_CACHE_TTL_SECONDS:
        return list(_model_cache["models"])

    base = settings.LLM_BASE_URL.rstrip("/")
    models_url = f"{base[:-3] if base.endswith('/v1') else base}/v1/models"

    try:
        with httpx.Client(timeout=2.5) as client:
            response = client.get(models_url)
            response.raise_for_status()
        payload = response.json()
        models = [
            item.get("id", "")
            for item in payload.get("data", [])
            if isinstance(item, dict) and item.get("id")
        ]
        _model_cache["ts"] = now
        _model_cache["models"] = models
        return list(models)
    except Exception as exc:
        log.debug("Could not fetch LM Studio loaded models: %s", exc)
        _model_cache["ts"] = now
        _model_cache["models"] = []
        return []


def _get_available_lmstudio_models() -> list[dict[str, Any]]:
    """Fetch available LM Studio models from the native REST API."""
    now = time.time()
    if now - _available_model_cache["ts"] < _MODEL_CACHE_TTL_SECONDS:
        return list(_available_model_cache["models"])

    base = settings.LLM_BASE_URL.rstrip("/")
    models_url = f"{base[:-3] if base.endswith('/v1') else base}/api/v1/models"

    try:
        with httpx.Client(timeout=2.5) as client:
            response = client.get(models_url)
            response.raise_for_status()
        payload = response.json()
        models = payload.get("models", [])
        if not isinstance(models, list):
            models = []
        _available_model_cache["ts"] = now
        _available_model_cache["models"] = models
        return list(models)
    except Exception as exc:
        log.debug("Could not fetch LM Studio available models: %s", exc)
        _available_model_cache["ts"] = now
        _available_model_cache["models"] = []
        return []


def _resolve_model_key(requested: str | None) -> str | None:
    """Resolve a requested display name or key to LM Studio's model key."""
    if not requested:
        return None

    available = _get_available_lmstudio_models()
    if not available:
        return requested

    requested_lower = requested.strip().lower()

    for item in available:
        key = str(item.get("key", "")).strip()
        display_name = str(item.get("display_name", "")).strip()
        if requested == key or requested == display_name:
            return key or requested
        if requested_lower == key.lower() or requested_lower == display_name.lower():
            return key or requested

    normalized_requested = requested_lower.replace("-", "").replace("_", "").replace(" ", "")
    for item in available:
        key = str(item.get("key", "")).strip()
        display_name = str(item.get("display_name", "")).strip()
        normalized_key = key.lower().replace("-", "").replace("_", "").replace(" ", "")
        normalized_display = display_name.lower().replace("-", "").replace("_", "").replace(" ", "")
        if normalized_requested in normalized_key or normalized_requested in normalized_display:
            return key or requested

    return requested


def _candidate_model_keys(requested: str | None) -> list[str]:
    """Return candidate model identifiers to try for a selected option."""
    if not requested:
        return []
    candidates = [requested]
    for candidate in _MODEL_ALIASES.get(requested, []):
        if candidate not in candidates:
            candidates.append(candidate)
    return candidates


def _ensure_lmstudio_model_loaded(model_name: str) -> str:
    """Load the requested LM Studio model into memory if needed and return the actual model id."""
    loaded_models = _get_loaded_lmstudio_models()
    resolved_candidates = []
    for candidate in _candidate_model_keys(model_name):
        resolved = _resolve_model_key(candidate) or candidate
        if resolved not in resolved_candidates:
            resolved_candidates.append(resolved)
    for candidate in resolved_candidates:
        if candidate in loaded_models:
            return candidate

    base = settings.LLM_BASE_URL.rstrip("/")
    load_url = f"{base[:-3] if base.endswith('/v1') else base}/api/v1/models/load"
    headers = {"Content-Type": "application/json"}
    api_key = settings.LLM_API_KEY.strip()
    if api_key and api_key != "sk-no-key":
        headers["Authorization"] = f"Bearer {api_key}"

    last_error: Exception | None = None
    for resolved_model in resolved_candidates:
        payload = {
            "model": resolved_model,
            "context_length": settings.LLM_MAX_TOKENS,
        }
        try:
            with httpx.Client(timeout=settings.LLM_REQUEST_TIMEOUT) as client:
                response = client.post(load_url, headers=headers, json=payload)
                response.raise_for_status()
            log.info("Requested LM Studio to load model: %s", resolved_model)
            _model_cache["ts"] = 0.0
            _model_cache["models"] = []
            _available_model_cache["ts"] = 0.0
            _available_model_cache["models"] = []
            # Give LM Studio a brief moment to surface the loaded model id.
            deadline = time.time() + 8.0
            while time.time() < deadline:
                time.sleep(0.25)
                loaded_models = _get_loaded_lmstudio_models()
                for candidate in resolved_candidates:
                    if candidate in loaded_models:
                        return candidate
                if resolved_model in loaded_models:
                    return resolved_model
            # If the loaded-models endpoint is slow to update, continue with the
            # key that LM Studio accepted for loading.
            return resolved_model
        except Exception as exc:
            last_error = exc
            log.warning("Failed to load LM Studio model candidate %s: %s", resolved_model, exc)

    if last_error:
        raise RuntimeError(f"Could not load LM Studio model '{model_name}'") from last_error
    return model_name


def set_text_model(model_name: str | None) -> None:
    """Set the preferred text model for chat generation."""
    global _text_llm, _text_model_name, _manual_text_model
    _manual_text_model = model_name or None
    _text_llm = None
    _text_model_name = None


def get_text_model() -> str:
    """Return the currently selected text model preference."""
    return _manual_text_model or settings.LLM_MODEL


def get_text_model_options() -> list[str]:
    """Return user-selectable text model options."""
    options = []
    for model in settings.LLM_AVAILABLE_MODELS:
        if model and model not in options:
            options.append(model)
    return options


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
