"""PDF text and vision extraction adapter.

Implements the adaptive pipeline:
  1. Try pypdf text extraction.
  2. If text is empty / low-quality → fall back to the vision model.
"""

from __future__ import annotations

import base64
import io
import logging
from typing import Any

from pypdf import PdfReader

from app.adapters.llm.lmstudio import get_vision_llm

log = logging.getLogger("pathfinder.pdf")

# Minimum characters per page to consider extraction successful
_MIN_CHARS_PER_PAGE = 30


async def extract_text_from_pdf(file_bytes: bytes, filename: str = "document.pdf") -> list[dict[str, Any]]:
    """Extract text from a PDF using the adaptive pipeline.

    Returns a list of dicts: ``[{page: int, text: str, method: str}]``.
    """
    reader = PdfReader(io.BytesIO(file_bytes))
    pages: list[dict[str, Any]] = []

    for page_num, page in enumerate(reader.pages, start=1):
        text = (page.extract_text() or "").strip()

        if len(text) >= _MIN_CHARS_PER_PAGE:
            pages.append({"page": page_num, "text": text, "method": "pypdf"})
        else:
            # Fall back to vision model
            log.info("Page %d of %s: low text (%d chars), using vision model", page_num, filename, len(text))
            vision_text = await _extract_page_with_vision(file_bytes, page_num, filename)
            pages.append({"page": page_num, "text": vision_text or text, "method": "vision"})

    log.info("Extracted %d pages from %s", len(pages), filename)
    return pages


async def _extract_page_with_vision(pdf_bytes: bytes, page_number: int, filename: str) -> str:
    """Use the vision model to extract text from a PDF page."""
    try:
        # Convert the specific page to an image-like representation
        # For vision models, we send the raw PDF page as base64
        reader = PdfReader(io.BytesIO(pdf_bytes))
        if page_number > len(reader.pages):
            return ""

        # Get page text (even if poor) as context
        page = reader.pages[page_number - 1]
        raw_text = (page.extract_text() or "").strip()

        # Encode PDF bytes for vision model
        b64_data = base64.b64encode(pdf_bytes).decode("utf-8")

        vision_llm = get_vision_llm()
        response = await vision_llm.ainvoke([
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": (
                            f"Extract ALL text content from page {page_number} of this document. "
                            "Include all text, numbers, tables, and structured data. "
                            "Preserve the original structure as much as possible. "
                            "Return ONLY the extracted text, nothing else."
                        ),
                    },
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:application/pdf;base64,{b64_data}"},
                    },
                ],
            }
        ])
        extracted = response.content if isinstance(response.content, str) else str(response.content)
        log.info("Vision model extracted %d chars from page %d of %s", len(extracted), page_number, filename)
        return extracted

    except Exception as exc:
        log.warning("Vision extraction failed for page %d of %s: %s", page_number, filename, exc)
        return ""
