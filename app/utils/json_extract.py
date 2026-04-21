"""Pull a JSON object out of messy LLM output.

Local models don't always honor "respond with JSON only" — they'll wrap
their answer in markdown code fences, add a sentence of prose before
the object, or tack on a sign-off at the end. Rather than re-prompting
every time, the ingestion / orchestrator / validator nodes pipe model
output through `parse_json_object`, which tries four strategies in
order:

1. the whole string parses as JSON,
2. there's a ```json ... ``` fenced block,
3. a balanced `{ ... }` object is embedded in the text,
4. a balanced `[ ... ]` array is embedded (last resort).

Returns `None` when nothing parses — callers treat that as "model
didn't give us structured output" and fall back to defaults.
"""

from __future__ import annotations

import json
import re
from typing import Any


# Matches a fenced code block, optionally tagged `json`. `DOTALL` lets
# the body span multiple lines; `IGNORECASE` accepts `JSON` / `Json`.
_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL | re.IGNORECASE)


def parse_json_object(content: Any) -> dict[str, Any] | None:
    """Extract a JSON object (dict) from arbitrary model output, or `None`.

    Arrays and primitives are ignored — callers that need an object
    rely on that. Use `_parse_json_payload` directly for the looser
    "any JSON value" semantics.
    """
    parsed = _parse_json_payload(content)
    return parsed if isinstance(parsed, dict) else None


def _parse_json_payload(content: Any) -> Any | None:
    """Try progressively more forgiving strategies to parse JSON out of `content`.

    Strategy order (cheapest first):
      1. the whole input is already JSON,
      2. JSON is inside a triple-backtick fence,
      3. extract the first balanced `{...}` substring,
      4. extract the first balanced `[...]` substring.
    """
    text = content if isinstance(content, str) else str(content or "")
    text = text.strip()
    if not text:
        return None

    direct = _try_loads(text)
    if direct is not None:
        return direct

    fence_match = _FENCE_RE.search(text)
    if fence_match:
        fenced = fence_match.group(1).strip()
        fenced_parsed = _try_loads(fenced)
        if fenced_parsed is not None:
            return fenced_parsed

    object_slice = _balanced_slice(text, "{", "}")
    if object_slice:
        obj = _try_loads(object_slice)
        if obj is not None:
            return obj

    array_slice = _balanced_slice(text, "[", "]")
    if array_slice:
        arr = _try_loads(array_slice)
        if arr is not None:
            return arr

    return None


def _try_loads(text: str) -> Any | None:
    """`json.loads` that swallows every parse error.

    We purposely ignore the specific error type — this module is only
    about "did the text happen to contain valid JSON?", not about
    reporting why something failed.
    """
    try:
        return json.loads(text)
    except Exception:
        return None


def _balanced_slice(text: str, opener: str, closer: str) -> str:
    """Return the first substring of `text` that is a balanced `opener`…`closer` run.

    Walks character by character, incrementing a depth counter on
    `opener` and decrementing on `closer`, returning the slice once
    depth hits zero. Naive about strings/comments — that's fine for
    JSON-ish text where `{` and `}` don't appear inside values the
    model is emitting.
    """
    start = text.find(opener)
    if start < 0:
        return ""
    depth = 0
    for idx in range(start, len(text)):
        char = text[idx]
        if char == opener:
            depth += 1
        elif char == closer:
            depth -= 1
            if depth == 0:
                return text[start : idx + 1]
    return ""
