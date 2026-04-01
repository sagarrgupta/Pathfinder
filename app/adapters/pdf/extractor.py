"""Document text extraction adapter.

Supports multiple file types with an adaptive pipeline:
  - PDF: pypdf text extraction -> vision fallback (for scanned docs)
  - Images (PNG, JPEG, HEIF/HEIC): vision model OCR
  - DOCX: python-docx text extraction
  - Plain text / markdown / csv: direct UTF-8 style decoding
"""

from __future__ import annotations

import base64
import io
import logging
import os
from typing import Any

from pypdf import PdfReader

from app.adapters.llm.lmstudio import get_vision_llm

log = logging.getLogger("pathfinder.pdf")

# Minimum characters per page to consider extraction successful
_MIN_CHARS_PER_PAGE = 30

# Supported image extensions
_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".heif", ".heic"}
_TEXT_EXTENSIONS = {".txt", ".md", ".markdown", ".csv", ".tsv", ".log", ".text"}

# MIME type mapping for images
_MIME_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".heif": "image/jpeg",  # converted to JPEG before sending
    ".heic": "image/jpeg",  # converted to JPEG before sending
}


# ── PDF Extraction ──────────────────────────────────────────────────


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
    """Use the vision model to extract text from a PDF page.

    Converts the page to a PNG image first, then sends to the vision model.
    """
    try:
        # Convert the specific page to a PNG image using PyMuPDF
        import fitz  # PyMuPDF

        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        if page_number > len(doc):
            doc.close()
            return ""

        page = doc[page_number - 1]
        # Render page at 200 DPI for good OCR quality
        pix = page.get_pixmap(dpi=200)
        img_bytes = pix.tobytes("png")
        doc.close()

        b64_data = base64.b64encode(img_bytes).decode("utf-8")

        vision_llm = get_vision_llm()
        response = await vision_llm.ainvoke([
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": (
                            f"Extract ALL text content from this document page image (page {page_number}). "
                            "Include all text, numbers, tables, and structured data. "
                            "Preserve the original structure as much as possible. "
                            "Return ONLY the extracted text, nothing else."
                        ),
                    },
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/png;base64,{b64_data}"},
                    },
                ],
            }
        ])
        extracted = response.content if isinstance(response.content, str) else str(response.content)
        log.info("Vision model extracted %d chars from page %d of %s", len(extracted), page_number, filename)
        return extracted

    except ImportError:
        log.warning("PyMuPDF not installed — cannot convert PDF page to image for vision extraction")
        return ""
    except Exception as exc:
        log.warning("Vision extraction failed for page %d of %s: %s", page_number, filename, exc)
        return ""


# ── Image Extraction ────────────────────────────────────────────────


async def extract_text_from_image(file_bytes: bytes, filename: str = "image.png") -> list[dict[str, Any]]:
    """Extract text from an image file using the vision model.

    Supports PNG, JPEG, HEIF/HEIC formats.
    Returns a list of dicts: ``[{page: 1, text: str, method: 'vision'}]``.
    """
    ext = os.path.splitext(filename)[1].lower()

    try:
        # Convert HEIF/HEIC to JPEG for vision model compatibility
        if ext in (".heif", ".heic"):
            img_bytes, mime_type = _convert_heif_to_jpeg(file_bytes)
        else:
            img_bytes = file_bytes
            mime_type = _MIME_TYPES.get(ext, "image/png")

        b64_data = base64.b64encode(img_bytes).decode("utf-8")

        vision_llm = get_vision_llm()
        response = await vision_llm.ainvoke([
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": (
                            "Extract ALL text content from this image. "
                            "Include all text, numbers, tables, and structured data you can see. "
                            "Preserve the original structure and formatting as much as possible. "
                            "If the image contains a document (resume, transcript, etc.), "
                            "extract all information from it. "
                            "Return ONLY the extracted text, nothing else."
                        ),
                    },
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:{mime_type};base64,{b64_data}"},
                    },
                ],
            }
        ])

        extracted = response.content if isinstance(response.content, str) else str(response.content)
        log.info("Vision model extracted %d chars from image %s", len(extracted), filename)
        return [{"page": 1, "text": extracted, "method": "vision"}]

    except Exception as exc:
        log.warning("Image extraction failed for %s: %s", filename, exc)
        return [{"page": 1, "text": "", "method": "vision_failed"}]


def _convert_heif_to_jpeg(file_bytes: bytes) -> tuple[bytes, str]:
    """Convert HEIF/HEIC image bytes to JPEG bytes."""
    try:
        from pillow_heif import register_heif_opener
        register_heif_opener()
    except ImportError:
        log.warning("pillow-heif not installed — HEIF/HEIC support unavailable")
        raise

    from PIL import Image

    img = Image.open(io.BytesIO(file_bytes))
    # Convert to RGB if necessary (HEIF can have alpha channels)
    if img.mode != "RGB":
        img = img.convert("RGB")
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=95)
    return buf.getvalue(), "image/jpeg"


# ── DOCX Extraction ─────────────────────────────────────────────────


async def extract_text_from_docx(file_bytes: bytes, filename: str = "document.docx") -> list[dict[str, Any]]:
    """Extract text from a DOCX file using python-docx.

    Returns a list of dicts: ``[{page: 1, text: str, method: 'docx'}]``.
    """
    try:
        from docx import Document

        doc = Document(io.BytesIO(file_bytes))

        paragraphs = []
        for para in doc.paragraphs:
            text = para.text.strip()
            if text:
                paragraphs.append(text)

        # Also extract text from tables
        for table in doc.tables:
            for row in table.rows:
                row_texts = [cell.text.strip() for cell in row.cells if cell.text.strip()]
                if row_texts:
                    paragraphs.append(" | ".join(row_texts))

        full_text = "\n".join(paragraphs)
        log.info("Extracted %d chars from DOCX %s", len(full_text), filename)
        return [{"page": 1, "text": full_text, "method": "docx"}]

    except ImportError:
        log.warning("python-docx not installed — DOCX support unavailable")
        return [{"page": 1, "text": "", "method": "docx_failed"}]
    except Exception as exc:
        log.warning("DOCX extraction failed for %s: %s", filename, exc)
        return [{"page": 1, "text": "", "method": "docx_failed"}]


async def extract_text_from_plaintext(file_bytes: bytes, filename: str = "document.txt") -> list[dict[str, Any]]:
    """Extract text from plain text-like documents.

    Attempts UTF-8 first, then falls back to a more permissive decode so
    lightweight resumes, transcripts, exported notes, and CSV-style text can
    be used directly in the product.
    """
    for encoding in ("utf-8", "utf-8-sig", "latin-1"):
        try:
            text = file_bytes.decode(encoding)
            break
        except UnicodeDecodeError:
            text = ""
    text = text.replace("\r\n", "\n").replace("\r", "\n").strip()
    log.info("Extracted %d chars from text file %s", len(text), filename)
    return [{"page": 1, "text": text, "method": "plaintext"}]


# ── Helpers ──────────────────────────────────────────────────────────


def get_file_type(filename: str) -> str:
    """Determine file category from filename extension.

    Returns one of: 'pdf', 'image', 'docx', 'text', 'unknown'.
    """
    ext = os.path.splitext(filename)[1].lower()
    if ext == ".pdf":
        return "pdf"
    if ext in _IMAGE_EXTENSIONS:
        return "image"
    if ext == ".docx":
        return "docx"
    if ext in _TEXT_EXTENSIONS:
        return "text"
    return "unknown"
