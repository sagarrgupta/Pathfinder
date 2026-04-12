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
from pathlib import Path
from typing import Any

from pypdf import PdfReader

from app.adapters.llm.lmstudio import get_vision_llm

log = logging.getLogger("pathfinder.pdf")

_MIN_CHARS_PER_PAGE = 30
_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".heif", ".heic"}
_TEXT_EXTENSIONS = {".txt", ".md", ".markdown", ".csv", ".tsv", ".log", ".text"}
_MIME_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".heif": "image/jpeg",
    ".heic": "image/jpeg",
}

def _page_payload(page: int, text: str, method: str) -> dict[str, Any]:
    return {"page": page, "text": str(text or "").strip(), "method": method}


async def _extract_text_with_vision(
    *,
    image_bytes: bytes,
    mime_type: str,
    prompt: str,
    filename: str,
    context_label: str,
) -> str:
    b64_data = base64.b64encode(image_bytes).decode("utf-8")
    vision_llm = get_vision_llm()
    response = await vision_llm.ainvoke([
        {
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": f"data:{mime_type};base64,{b64_data}"}},
            ],
        }
    ])
    extracted = response.content if isinstance(response.content, str) else str(response.content)
    log.info("Vision model extracted %d chars from %s in %s", len(extracted), context_label, filename)
    return extracted


async def extract_text_from_pdf(file_bytes: bytes, filename: str = "document.pdf") -> list[dict[str, Any]]:
    """Extract text from a PDF using pypdf with vision fallback."""
    try:
        reader = PdfReader(io.BytesIO(file_bytes))
    except Exception as exc:
        log.warning("PDF open failed for %s: %s", filename, exc)
        return []

    pages: list[dict[str, Any]] = []
    for page_num, page in enumerate(reader.pages, start=1):
        try:
            text = (page.extract_text() or "").strip()
        except Exception as exc:
            log.warning("pypdf extraction failed for page %d of %s: %s", page_num, filename, exc)
            text = ""

        if len(text) >= _MIN_CHARS_PER_PAGE:
            pages.append(_page_payload(page_num, text, "pypdf"))
            continue

        log.info("Page %d of %s: low text (%d chars), using vision fallback", page_num, filename, len(text))
        vision_text = await _extract_page_with_vision(file_bytes, page_num, filename)
        if vision_text:
            pages.append(_page_payload(page_num, vision_text, "vision"))
        else:
            method = "pypdf_low_text" if text else "vision_failed"
            pages.append(_page_payload(page_num, text, method))

    log.info("Extracted %d pages from %s", len(pages), filename)
    return pages


async def _extract_page_with_vision(pdf_bytes: bytes, page_number: int, filename: str) -> str:
    """Render one PDF page and run OCR through the vision model."""
    try:
        import fitz  # PyMuPDF
    except ImportError:
        log.warning("PyMuPDF not installed — cannot convert PDF page to image for vision extraction")
        return ""

    doc = None
    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        if page_number > len(doc):
            return ""
        page = doc[page_number - 1]
        pix = page.get_pixmap(dpi=200)
        img_bytes = pix.tobytes("png")
        return await _extract_text_with_vision(
            image_bytes=img_bytes,
            mime_type="image/png",
            prompt=(
                f"Extract ALL text content from this document page image (page {page_number}). "
                "Include all text, numbers, tables, and structured data. "
                "Preserve the original structure as much as possible. "
                "Return ONLY the extracted text, nothing else."
            ),
            filename=filename,
            context_label=f"page {page_number}",
        )
    except Exception as exc:
        log.warning("Vision extraction failed for page %d of %s: %s", page_number, filename, exc)
        return ""
    finally:
        if doc is not None:
            doc.close()


async def extract_text_from_image(file_bytes: bytes, filename: str = "image.png") -> list[dict[str, Any]]:
    """Extract text from an image file using the vision model."""
    ext = Path(filename).suffix.lower()

    try:
        if ext in {".heif", ".heic"}:
            img_bytes, mime_type = _convert_heif_to_jpeg(file_bytes)
        else:
            img_bytes = file_bytes
            mime_type = _MIME_TYPES.get(ext, "image/png")

        extracted = await _extract_text_with_vision(
            image_bytes=img_bytes,
            mime_type=mime_type,
            prompt=(
                "Extract ALL text content from this image. "
                "Include all text, numbers, tables, and structured data you can see. "
                "Preserve the original structure and formatting as much as possible. "
                "If the image contains a document (resume, transcript, etc.), "
                "extract all information from it. "
                "Return ONLY the extracted text, nothing else."
            ),
            filename=filename,
            context_label="image",
        )
        return [_page_payload(1, extracted, "vision")]
    except Exception as exc:
        log.warning("Image extraction failed for %s: %s", filename, exc)
        return [_page_payload(1, "", "vision_failed")]


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
    if img.mode != "RGB":
        img = img.convert("RGB")
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=95)
    return buf.getvalue(), "image/jpeg"


async def extract_text_from_docx(file_bytes: bytes, filename: str = "document.docx") -> list[dict[str, Any]]:
    """Extract text from a DOCX file using python-docx."""
    try:
        from docx import Document

        doc = Document(io.BytesIO(file_bytes))
        paragraphs: list[str] = []

        for para in doc.paragraphs:
            text = para.text.strip()
            if text:
                paragraphs.append(text)

        for table in doc.tables:
            for row in table.rows:
                row_texts = [
                    cell.text.strip()
                    for cell in row.cells
                    if cell.text.strip()
                ]
                if row_texts:
                    paragraphs.append(" | ".join(row_texts))

        full_text = "\n".join(paragraphs)
        log.info("Extracted %d chars from DOCX %s", len(full_text), filename)
        return [_page_payload(1, full_text, "docx")]
    except ImportError:
        log.warning("python-docx not installed — DOCX support unavailable")
        return [_page_payload(1, "", "docx_failed")]
    except Exception as exc:
        log.warning("DOCX extraction failed for %s: %s", filename, exc)
        return [_page_payload(1, "", "docx_failed")]


async def extract_text_from_plaintext(file_bytes: bytes, filename: str = "document.txt") -> list[dict[str, Any]]:
    """Extract text from plain text-like documents."""
    text = ""
    for encoding in ("utf-8", "utf-8-sig", "latin-1"):
        try:
            text = file_bytes.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    text = text.replace("\r\n", "\n").replace("\r", "\n").strip()
    log.info("Extracted %d chars from text file %s", len(text), filename)
    return [_page_payload(1, text, "plaintext")]


def get_file_type(filename: str) -> str:
    """Determine file category from filename extension."""
    ext = Path(filename).suffix.lower()
    if ext == ".pdf":
        return "pdf"
    if ext in _IMAGE_EXTENSIONS:
        return "image"
    if ext == ".docx":
        return "docx"
    if ext in _TEXT_EXTENSIONS:
        return "text"
    return "unknown"
