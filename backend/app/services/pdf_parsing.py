"""Resume PDF parsing: turn an uploaded PDF into clean, plain text.

The multi-agent pipeline reasons over plain text, so this service is the bridge
between the raw bytes a user uploads and the text the agents read. It's written as
pure functions over ``bytes``, with no FastAPI imports, so it can be unit-tested
without a web server or a real file on disk.
"""

import io
import re

from pypdf import PdfReader

# The first bytes of every PDF file. Checking this up front lets us fail fast,
# with a friendly message, when someone uploads a file that isn't a PDF.
_PDF_MAGIC_HEADER = b"%PDF-"


class ResumeParsingError(Exception):
    """Raised when an uploaded file can't be read as a text-bearing PDF.

    The API layer catches this and returns a 400/422 with the message, rather than
    leaking a low-level parsing traceback to the client.
    """


def _normalize_whitespace(raw_text: str) -> str:
    """Tidy the ragged whitespace pypdf emits into clean, readable text.

    PDF text extraction often comes out with stray runs of spaces and blank lines.
    We keep paragraph breaks but squeeze everything else, so the eventual LLM
    prompt is clean and token-efficient.
    """
    # Normalize Windows / old-Mac line endings to a single '\n'.
    text = raw_text.replace("\r\n", "\n").replace("\r", "\n")
    # Strip leading/trailing spaces on every line (blank lines become empty).
    text = "\n".join(line.strip() for line in text.split("\n"))
    # Collapse 3+ consecutive newlines down to a single blank line.
    text = re.sub(r"\n{3,}", "\n\n", text)
    # Collapse runs of spaces/tabs into a single space.
    text = re.sub(r"[ \t]{2,}", " ", text)
    return text.strip()


def extract_text_from_pdf_bytes(pdf_bytes: bytes) -> str:
    """Extract and clean the text content of a PDF resume.

    Returns the concatenated, whitespace-normalized text of every page. Raises
    ``ResumeParsingError`` if the bytes are empty, aren't a PDF, the PDF is
    password-protected or corrupt, or no extractable text is found (for example a
    purely scanned / image-only document).
    """
    # Fail fast on obviously-wrong input before handing it to pypdf.
    if not pdf_bytes:
        raise ResumeParsingError("The uploaded file is empty.")
    if not pdf_bytes.startswith(_PDF_MAGIC_HEADER):
        raise ResumeParsingError("The uploaded file does not appear to be a PDF.")

    try:
        reader = PdfReader(io.BytesIO(pdf_bytes))

        # Some resumes are "encrypted" with an empty owner password; try that
        # before giving up, but never prompt for a real one.
        if reader.is_encrypted:
            try:
                reader.decrypt("")
            except Exception as decrypt_error:  # noqa: BLE001 - any failure means unreadable
                raise ResumeParsingError(
                    "The PDF is password-protected and cannot be read."
                ) from decrypt_error

        page_texts = [page.extract_text() or "" for page in reader.pages]
    except ResumeParsingError:
        raise  # already a clean, user-facing error; don't re-wrap it
    except Exception as parsing_error:  # noqa: BLE001 - wrap any low-level pypdf failure
        raise ResumeParsingError(f"Could not read the PDF: {parsing_error}") from parsing_error

    combined_text = _normalize_whitespace("\n".join(page_texts))
    if not combined_text:
        raise ResumeParsingError(
            "No selectable text was found in the PDF. If this is a scanned "
            "document, please upload a text-based PDF instead."
        )
    return combined_text
