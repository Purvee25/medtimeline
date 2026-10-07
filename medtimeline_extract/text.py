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
# Lab reports are a page or two; anything longer is rejected before parsing or rasterising, which
# bounds the CPU, memory and temp disk a hostile PDF can consume.
MAX_PDF_PAGES = 20
# A4 at OCR_DPI is ~8.7 MP; refuse anything far larger instead of decoding a decompression bomb.
Image.MAX_IMAGE_PIXELS = 40_000_000

# A line is treated as identifying if it carries one of these labels followed by a separator or value.
_IDENTIFIER_LABELS = (
    r"patient|pt\.?|name|uhid|mrn|reg(?:istration)?\.?\s*no|report\s*id|sample\s*id|lab\s*no|\bid"
    r"|phone|mobile|mob\.?|tel\.?|contact|e-?mail|address|addr\.?|aadh?aa?r|abha"
    r"|d\.?\s*o\.?\s*b\.?|date\s*of\s*birth|birth|age|sex|gender|ref(?:erred)?\.?\s*by|consultant|doctor|dr\."
)
_IDENTIFIER_LINE = re.compile(rf"(?<![a-z])(?:{_IDENTIFIER_LABELS})(?![a-z])\s*(?:[:#\-=.]|\s+\S)", re.IGNORECASE)
# Unlabelled identifiers: honorific + name, or a "45Y/M" age-sex token.
_NAME_OR_DEMOGRAPHIC_LINE = re.compile(
    r"\b(?:mr|mrs|ms|miss|master|baby|smt|shri)\.?\s+[a-z]|\b\d{1,3}\s*y(?:rs?|ears?)?\s*/\s*[mf]\b", re.IGNORECASE
)
# Values that identify a person wherever they appear.
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_LONG_NUMBER = re.compile(r"\+?\d[\d\s-]{8,}\d")  # phone numbers, Aadhaar, MRNs; digit count checked below
_MIN_IDENTIFIER_DIGITS = 10
_DATE = re.compile(r"\d{4}-\d{2}-\d{2}|\d{1,2}[/-]\d{1,2}[/-]\d{2,4}")
_COLLECTION_HINT = re.compile(r"collect|sample|drawn", re.IGNORECASE)


def _check_pdf(path: Path) -> None:
    with path.open("rb") as f:
        if f.read(len(PDF_MAGIC)) != PDF_MAGIC:
            raise ValueError(f"{path} is not a PDF (bad magic bytes)")


def _text_layer(path: Path) -> str:
    reader = PdfReader(path)
    if len(reader.pages) > MAX_PDF_PAGES:
        raise ValueError(f"PDF has {len(reader.pages)} pages; at most {MAX_PDF_PAGES} are accepted")
    # Layout mode keeps table rows on one line; the default emits one cell per line.
    return "\n".join(page.extract_text(extraction_mode="layout") or "" for page in reader.pages)


def _ocr(path: Path) -> str:
    with tempfile.TemporaryDirectory() as tmp:
        subprocess.run(
            [
                "pdftoppm",
                "-f",
                "1",
                "-l",
                str(MAX_PDF_PAGES),
                "-r",
                str(OCR_DPI),
                "-gray",
                "-png",
                str(path),
                f"{tmp}/page",
            ],
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
        ValueError: File is not a PDF, or has more than MAX_PDF_PAGES pages.
        subprocess.CalledProcessError: Rasterisation failed.
    """
    _check_pdf(path)
    text = _text_layer(path)
    if len(text.strip()) >= MIN_TEXT_LAYER_CHARS:
        return text, "text_layer"
    logger.info("No usable text layer, running OCR", extra={"file": path.name})
    return _ocr(path), "ocr"


def _scrub_values(line: str) -> str:
    line = _EMAIL.sub("[redacted]", line)
    return _LONG_NUMBER.sub(
        lambda m: "[redacted]" if sum(c.isdigit() for c in m.group(0)) >= _MIN_IDENTIFIER_DIGITS else m.group(0),
        line,
    )


def redact_identifiers(text: str) -> str:
    """Remove patient identifiers before any text leaves the system (e.g. to an LLM).

    Lines carrying an identifying label, an honorific + name, or an age/sex token are dropped
    entirely; the collection date is salvaged from them because the timeline needs it. On every
    kept line, e-mail addresses and long digit runs (phones, Aadhaar, MRNs) are replaced.
    Redaction is a deny-list, so it is defence in depth, not a guarantee: the LLM call is also
    gated on explicit consent.
    """
    kept = []
    for line in text.splitlines():
        if _IDENTIFIER_LINE.search(line) or _NAME_OR_DEMOGRAPHIC_LINE.search(line):
            date = _DATE.search(line)
            if date and _COLLECTION_HINT.search(line):
                kept.append(f"Sample collected: {date.group(0)}")
            continue
        kept.append(_scrub_values(line))
    return "\n".join(kept)
