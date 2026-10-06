"""PDF → text, with OCR fallback for scanned reports, and identifier redaction."""

import logging
import re
import subprocess
import tempfile
from pathlib import Path

import pytesseract
from PIL import Image
from pypdf import PdfReader

logger = logging.getLogger(__name__)

MIN_TEXT_LAYER_CHARS = 40
OCR_DPI = 300
OCR_TIMEOUT_S = 120
PDF_MAGIC = b"%PDF-"

_IDENTIFIER_LINE = re.compile(r"(patient|name|report\s*id|uhid|mrn|phone|mobile|address)\s*[:#]", re.IGNORECASE)
_AGE_SEX = re.compile(r"age\s*/\s*sex\s*:\s*\S+", re.IGNORECASE)


def _check_pdf(path: Path) -> None:
    with path.open("rb") as f:
        if f.read(len(PDF_MAGIC)) != PDF_MAGIC:
            raise ValueError(f"{path} is not a PDF (bad magic bytes)")


def _text_layer(path: Path) -> str:
    # Layout mode keeps table rows on one line; the default emits one cell per line.
    return "\n".join(page.extract_text(extraction_mode="layout") or "" for page in PdfReader(path).pages)


def _ocr(path: Path) -> str:
    with tempfile.TemporaryDirectory() as tmp:
        subprocess.run(
            ["pdftoppm", "-r", str(OCR_DPI), "-gray", "-png", str(path), f"{tmp}/page"],
            check=True,
            capture_output=True,
            timeout=OCR_TIMEOUT_S,
        )
        pages = sorted(Path(tmp).glob("page*.png"))
        # psm 6: assume a uniform block of text — keeps table rows on one line.
        return "\n".join(pytesseract.image_to_string(Image.open(p), config="--psm 6") for p in pages)


def extract_text(path: Path) -> tuple[str, str]:
    """Return (text, method) for a PDF, using OCR when the text layer is empty.

    Raises:
        ValueError: File is not a PDF.
        subprocess.CalledProcessError: Rasterisation failed.
    """
    _check_pdf(path)
    text = _text_layer(path)
    if len(text.strip()) >= MIN_TEXT_LAYER_CHARS:
        return text, "text_layer"
    logger.info("No usable text layer, running OCR", extra={"file": path.name})
    return _ocr(path), "ocr"


def redact_identifiers(text: str) -> str:
    """Drop lines carrying patient identifiers so they never reach the LLM.

    Collection date is kept (needed for the timeline); demographics are removed.
    """
    kept = []
    for line in text.splitlines():
        if _IDENTIFIER_LINE.search(line):
            date = re.search(r"\d{4}-\d{2}-\d{2}|\d{1,2}[/-]\d{1,2}[/-]\d{2,4}", line)
            if date and re.search(r"collect|sample|date", line, re.IGNORECASE):
                kept.append(f"Sample collected: {date.group(0)}")
            continue
        kept.append(_AGE_SEX.sub("", line))
    return "\n".join(kept)
