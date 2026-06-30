"""Tests for the resume PDF parsing service (app.services.pdf_parsing)."""

import pytest

from app.services.pdf_parsing import ResumeParsingError, extract_text_from_pdf_bytes


def test_extracts_text_from_a_valid_pdf(sample_pdf_bytes):
    text = extract_text_from_pdf_bytes(sample_pdf_bytes)
    assert "Built" in text
    assert "APIs" in text


def test_rejects_empty_input():
    with pytest.raises(ResumeParsingError):
        extract_text_from_pdf_bytes(b"")


def test_rejects_non_pdf_bytes():
    with pytest.raises(ResumeParsingError):
        extract_text_from_pdf_bytes(b"this is plainly not a pdf file")
