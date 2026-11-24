"""Turn uploaded files into plain text the ingestion pipeline can chunk.

The `doc_analyst` node calls `extract_document_text()` for every
attached file. Each supported format has its own path:

- PDF  : try `pypdf` first (fast, text-native); if a page comes back
         nearly empty (likely a scanned page), fall back to rendering
         it as an image and running the vision LLM for OCR.
- DOCX : `python-docx` — paragraphs plus a flattened "cell | cell"
         rendering for any embedded tables.
- Image: go straight to the vision LLM for OCR, converting HEIF/HEIC
         to JPEG first since the vision client doesn't accept them.

Every path returns the same `list[dict]` shape: one dict per logical
"page" with `page`, `text`, and `method` (where the text came from —
useful when debugging low-quality ingests).
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

# A page with fewer than this many characters is treated as likely
# scanned / image-only, so we re-run it through the vision model.
_MIN_CHARS_PER_PAGE = 30

_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".heif", ".heic"}
_MIME_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".heif": "image/jpeg",
    ".heic": "image/jpeg",
}


def _page_payload(page: int, text: str, method: str) -> dict[str, Any]:
    """Shape every extractor returns — the ingestion pipeline assumes this."""
    return {"page": page, "text": str(text or "").strip(), "method": method}


async def _extract_text_with_vision(
    *,
    image_bytes: bytes,
    mime_type: str,
    prompt: str,
    filename: str,
    context_label: str,
) -> str:
    """Send one image to the vision LLM and return the extracted text.

    Shared by the image-upload path and the PDF vision-fallback path so
    the prompt + response handling only lives in one place.
    """
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
    """Extract text from each PDF page, with automatic OCR fallback.

    Tries the fast path (`pypdf.extract_text()`) first. If a page comes
    back too short to be real content, re-renders that single page with
    PyMuPDF at 200 DPI and sends the resulting PNG through the vision
    model. The `method` field in each returned page tells the ingester
    which path won.
    """
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
    """Render one PDF page to an image and OCR it via the vision LLM.

    Returns an empty string if PyMuPDF isn't installed or the page is
    out of range — the caller decides how to record the failure.
    """
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
                f"Extract ALL text from this document page (page {page_number}): "
                "text, numbers, tables, structured data. Preserve original structure. "
                "Return ONLY the extracted text."
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
    """Describe uploaded clothing and extract text. Convert HEIF/HEIC to JPEG.

    Always returns exactly one page so the downstream chunker can treat
    images and single-page PDFs the same way.
    """
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
                "Describe this image for a fashion wardrobe and document knowledge graph. "
                "For clothing or accessories, describe EACH visible item separately with a "
                "local item number, category, color, pattern, and visible design details. "
                "Transcribe readable labels, sizes, brands, measurements with units, and "
                "any other visible text or tables. Preserve document and size-table structure. "
                "Distinguish printed facts from visual observations. Do not guess exact "
                "measurements, size, brand, material, ownership, or occasion from appearance; "
                "mark unclear attributes unknown. If no text is present, still describe "
                "visible garments. Return only the factual description and extracted text."
            ),
            filename=filename,
            context_label="image",
        )
        return [_page_payload(1, extracted, "vision")]
    except Exception as exc:
        log.warning("Image extraction failed for %s: %s", filename, exc)
        return [_page_payload(1, "", "vision_failed")]

def _convert_heif_to_jpeg(file_bytes: bytes) -> tuple[bytes, str]:
    """Re-encode an iPhone-style HEIF/HEIC image as JPEG.

    The vision LLM client only accepts standard formats; HEIF images
    (common on iOS exports) would otherwise be rejected silently.
    """
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
    """Pull paragraph text + a flat rendering of table rows from a `.docx`.

    `python-docx` doesn't have a real page concept, so we return one
    synthetic page with all content joined by newlines — the chunker
    will slice it back up.
    """
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

async def extract_document_text(file_type: str, content: bytes, filename: str) -> list[dict[str, Any]]:
    """Public entry point the ingestion pipeline uses.

    Routes to the right extractor based on `file_type` (produced by
    `get_file_type`) and always returns the same page-list shape.
    """
    if file_type == "pdf":
        return await extract_text_from_pdf(content, filename)
    if file_type == "image":
        return await extract_text_from_image(content, filename)
    if file_type == "docx":
        return await extract_text_from_docx(content, filename)
    raise ValueError(f"Unsupported file type for ingestion: {file_type}")

def get_file_type(filename: str) -> str:
    """Bucket a filename into one of {"pdf", "image", "docx", "unknown"}."""
    ext = Path(filename).suffix.lower()
    if ext == ".pdf":
        return "pdf"
    if ext in _IMAGE_EXTENSIONS:
        return "image"
    if ext == ".docx":
        return "docx"
    return "unknown"
