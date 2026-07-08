"""Ingest the ChubbSafes intro PDF into a raw reference text file.

The deck's Chinese text is CID-encoded; ``pdftotext -enc UTF-8`` (poppler) extracts it
cleanly. We try, in order: pdftotext CLI, PyMuPDF (fitz), pypdf.

The raw text is written to a *separate* ``*_pdf_raw.txt`` file — NOT the curated
``chubbsafes_context.md`` — because the curated context is injected into every extraction
prompt, and dumping the whole deck there would inflate tokens/cost. Curate manually from
the raw file when the deck changes.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from loguru import logger


def _via_pdftotext(pdf: Path) -> str | None:
    exe = shutil.which("pdftotext")
    if not exe:
        return None
    try:
        out = subprocess.run(
            [exe, "-enc", "UTF-8", "-layout", str(pdf), "-"],
            capture_output=True, text=True, encoding="utf-8", timeout=120,
        )
        return out.stdout or None
    except Exception as exc:  # noqa: BLE001
        logger.debug("pdftotext failed: {}", exc)
        return None


def _via_pymupdf(pdf: Path) -> str | None:
    try:
        import fitz  # PyMuPDF
    except ImportError:
        return None
    try:
        doc = fitz.open(str(pdf))
        return "\n".join(page.get_text() for page in doc)
    except Exception as exc:  # noqa: BLE001
        logger.debug("PyMuPDF failed: {}", exc)
        return None


def _via_pypdf(pdf: Path) -> str | None:
    try:
        from pypdf import PdfReader
    except ImportError:
        return None
    try:
        reader = PdfReader(str(pdf))
        return "\n".join(page.extract_text() or "" for page in reader.pages)
    except Exception as exc:  # noqa: BLE001
        logger.debug("pypdf failed: {}", exc)
        return None


def extract_pdf_text(pdf: Path) -> str:
    """Extract text from ``pdf`` using the first backend that works."""
    for backend in (_via_pdftotext, _via_pymupdf, _via_pypdf):
        text = backend(pdf)
        if text and text.strip():
            logger.info("PDF extracted via {}", backend.__name__)
            return text.strip()
    raise RuntimeError(
        "no PDF backend succeeded. Install poppler (pdftotext) or `pip install pymupdf`."
    )


def ingest_pdf(pdf: str | Path, context_file: str | Path) -> Path:
    """Extract the PDF to a raw reference file beside the curated context.

    Returns the path of the written ``*_pdf_raw.txt`` file. The curated
    ``chubbsafes_context.md`` (the prompt anchor) is intentionally left untouched.
    """
    pdf = Path(pdf)
    context_file = Path(context_file)
    if not pdf.exists():
        raise FileNotFoundError(pdf)

    raw = extract_pdf_text(pdf)
    raw_file = context_file.with_name("chubbsafes_pdf_raw.txt")
    raw_file.parent.mkdir(parents=True, exist_ok=True)
    header = (
        f"# 原始 PDF 抽取（{pdf.name}）\n"
        f"# 自动生成，供人工整理/核对；不会注入到提示词。\n"
        f"# 精炼后的领域背景请维护 {context_file.name}\n\n"
    )
    raw_file.write_text(header + raw, encoding="utf-8")
    logger.info("raw PDF text written to {}", raw_file)
    return raw_file
