"""LM Studio LLM adapter.

Provides singleton ChatOpenAI instances for text and vision models
running on LM Studio's OpenAI-compatible API.
"""

from __future__ import annotations

from typing import Optional

from langchain_openai import ChatOpenAI

from app.config.settings import settings

_text_llm: Optional[ChatOpenAI] = None
_vision_llm: Optional[ChatOpenAI] = None


def get_text_llm() -> ChatOpenAI:
    """Return the singleton text LLM (gpt-oss-20b)."""
    global _text_llm
    if _text_llm is None:
        _text_llm = ChatOpenAI(
            model=settings.LLM_MODEL,
            base_url=settings.LLM_BASE_URL,
            api_key=settings.LLM_API_KEY,
            temperature=settings.LLM_TEMPERATURE,
        )
    return _text_llm


def get_vision_llm() -> ChatOpenAI:
    """Return the singleton vision LLM (qwen3-vl-8b)."""
    global _vision_llm
    if _vision_llm is None:
        _vision_llm = ChatOpenAI(
            model=settings.VISION_MODEL,
            base_url=settings.LLM_BASE_URL,
            api_key=settings.LLM_API_KEY,
            temperature=0.1,
        )
    return _vision_llm