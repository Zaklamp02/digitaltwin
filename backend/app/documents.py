"""Text extraction for uploaded documents (PDF, DOCX, TXT/MD).

Used by the admin upload endpoint to populate the body of a knowledge node
so the content is automatically RAG-indexed.
"""

from __future__ import annotations

import logging
from pathlib import Path

log = logging.getLogger("ask-my-agent.documents")

SUPPORTED_SUFFIXES = {".pdf", ".docx", ".doc", ".txt", ".md"}


def extract_text(path: Path, mime_type: str = "") -> str:
    """Return plain text extracted from *path*.

    Falls back to an empty string if extraction fails or the format is not
    supported — callers should treat that as a non-fatal condition.
    """
    suffix = path.suffix.lower()
    try:
        if suffix == ".pdf" or "pdf" in mime_type:
            return _extract_pdf(path)
        if suffix in (".docx", ".doc") or "wordprocessingml" in mime_type:
            return _extract_docx(path)
        if suffix in (".txt", ".md") or mime_type.startswith("text/"):
            return path.read_text(encoding="utf-8", errors="replace")
    except Exception as exc:  # noqa: BLE001
        log.warning("text extraction failed for %s: %s", path.name, exc)
    return ""


def _extract_pdf(path: Path) -> str:
    import pypdf  # type: ignore[import-untyped]

    reader = pypdf.PdfReader(str(path))
    parts: list[str] = []
    for page in reader.pages:
        text = page.extract_text() or ""
        if text.strip():
            parts.append(text.strip())
    return "\n\n".join(parts)


def _extract_docx(path: Path) -> str:
    import docx  # type: ignore[import-untyped]

    doc = docx.Document(str(path))
    return "\n".join(p.text for p in doc.paragraphs if p.text.strip())
