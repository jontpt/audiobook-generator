"""
services/text_extraction.py
Handles extraction of raw text from PDF, DOCX, ePub, and plain-text files.
Returns a list of chapters: [{"title": str, "paragraphs": [str]}]
"""
from __future__ import annotations
import re
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# ── Chapter detection patterns ───────────────────────────────────────────────
CHAPTER_PATTERNS = [
    re.compile(r'^chapter\s+\w+', re.IGNORECASE),
    re.compile(r'^(part|book|volume|act|scene)\s+\w+', re.IGNORECASE),
    re.compile(r'^\d+\.\s+\w+'),          # "1. Title"
    re.compile(r'^[IVXLCDM]+\.\s+\w+'),   # Roman numerals
]

HEADER_FOOTER_PATTERNS = [
    re.compile(r'^\d+$'),                  # Lone page number
    re.compile(r'^page\s+\d+', re.I),
    re.compile(r'^[-–—]{3,}$'),            # Dividers
]


def _is_chapter_heading(line: str) -> bool:
    stripped = line.strip()
    return any(p.match(stripped) for p in CHAPTER_PATTERNS)


def _is_noise(line: str) -> bool:
    stripped = line.strip()
    return any(p.match(stripped) for p in HEADER_FOOTER_PATTERNS)


def _split_into_chapters(raw_text: str) -> list[dict]:
    """
    Split raw text into chapters.
    Each chapter: {"title": str, "paragraphs": [str]}
    """
    lines = raw_text.split('\n')
    chapters: list[dict] = []
    current_title = "Chapter 1"
    current_paras: list[str] = []
    buffer: list[str] = []

    def flush_buffer():
        block = ' '.join(buffer).strip()
        if block:
            current_paras.append(block)
        buffer.clear()

    for line in lines:
        clean = line.strip()
        if not clean or _is_noise(clean):
            flush_buffer()
            continue

        if _is_chapter_heading(clean):
            flush_buffer()
            if current_paras:
                chapters.append({"title": current_title, "paragraphs": current_paras.copy()})
            current_title = clean
            current_paras = []
        else:
            buffer.append(clean)

    flush_buffer()
    if current_paras:
        chapters.append({"title": current_title, "paragraphs": current_paras})

    if not chapters:
        # No chapter markers found — treat whole text as one chapter
        all_paras = [p.strip() for p in raw_text.split('\n\n') if p.strip()]
        chapters = [{"title": "Chapter 1", "paragraphs": all_paras}]

    return chapters


# ── PDF ──────────────────────────────────────────────────────────────────────

def extract_from_pdf(file_path: Path) -> list[dict]:
    try:
        import fitz  # PyMuPDF
        doc = fitz.open(str(file_path))
        pages_text = []
        for page in doc:
            pages_text.append(page.get_text("text"))
        doc.close()
        raw = '\n'.join(pages_text)
        return _split_into_chapters(raw)
    except ImportError:
        logger.warning("PyMuPDF not installed, falling back to basic PDF reading")
        return _fallback_pdf(file_path)
    except Exception as e:
        logger.error(f"PDF extraction error: {e}")
        raise


def _fallback_pdf(file_path: Path) -> list[dict]:
    """Minimal fallback using pdfminer if available."""
    try:
        from pdfminer.high_level import extract_text
        raw = extract_text(str(file_path))
        return _split_into_chapters(raw)
    except Exception as e:
        raise RuntimeError(f"Cannot extract PDF text: {e}")


# ── DOCX ─────────────────────────────────────────────────────────────────────

def extract_from_docx(file_path: Path) -> list[dict]:
    try:
        from docx import Document
        doc = Document(str(file_path))
        chapters: list[dict] = []
        current_title = "Chapter 1"
        current_paras: list[str] = []

        for para in doc.paragraphs:
            text = para.text.strip()
            if not text:
                continue
            # Use heading styles as chapter breaks
            if para.style.name.startswith('Heading 1') or _is_chapter_heading(text):
                if current_paras:
                    chapters.append({"title": current_title, "paragraphs": current_paras.copy()})
                current_title = text
                current_paras = []
            else:
                current_paras.append(text)

        if current_paras:
            chapters.append({"title": current_title, "paragraphs": current_paras})

        return chapters if chapters else _split_into_chapters(
            '\n'.join(p.text for p in Document(str(file_path)).paragraphs))
    except Exception as e:
        logger.error(f"DOCX extraction error: {e}")
        raise


# ── ePub ─────────────────────────────────────────────────────────────────────

def extract_from_epub(file_path: Path) -> list[dict]:
    try:
        import ebooklib
        from ebooklib import epub
        from bs4 import BeautifulSoup

        book = epub.read_epub(str(file_path))
        chapters: list[dict] = []

        for item in book.get_items_of_type(ebooklib.ITEM_DOCUMENT):
            soup = BeautifulSoup(item.get_content(), 'html.parser')
            # Try to get chapter title from h1/h2/h3
            heading = soup.find(['h1', 'h2', 'h3'])
            title = heading.get_text().strip() if heading else f"Chapter {len(chapters)+1}"
            # Extract paragraphs
            paras = [p.get_text().strip() for p in soup.find_all('p') if p.get_text().strip()]
            if paras:
                chapters.append({"title": title, "paragraphs": paras})

        return chapters
    except Exception as e:
        logger.error(f"ePub extraction error: {e}")
        raise


# ── Plain text ────────────────────────────────────────────────────────────────

def extract_from_txt(file_path: Path) -> list[dict]:
    raw = file_path.read_text(encoding='utf-8', errors='replace')
    return _split_into_chapters(raw)


# ── Dispatcher ───────────────────────────────────────────────────────────────

def extract_text(file_path: Path) -> list[dict]:
    """
    Main entry point. Detect file type and extract chapters.
    Returns: list of {"title": str, "paragraphs": [str]}
    """
    ext = file_path.suffix.lower()
    extractors = {
        '.pdf':  extract_from_pdf,
        '.docx': extract_from_docx,
        '.epub': extract_from_epub,
        '.txt':  extract_from_txt,
    }
    extractor = extractors.get(ext)
    if not extractor:
        raise ValueError(f"Unsupported file type: {ext}")

    logger.info(f"Extracting text from {file_path.name} ({ext})")
    chapters = extractor(file_path)
    logger.info(f"Extracted {len(chapters)} chapters")
    return chapters
