"""Tests for the artifact export builders (app.services.export)."""

from app.services.export import build_cover_letter_docx, build_resume_pdf


def test_cover_letter_docx_is_a_valid_docx():
    data = build_cover_letter_docx(
        "Dear Hiring Manager,\n\nI built FastAPI services.\n\nSincerely,\nA. Candidate",
        job_title="Senior Backend Engineer",
        company="Acme Corp",
    )
    assert isinstance(data, (bytes, bytearray))
    assert bytes(data[:2]) == b"PK"   # .docx is a ZIP archive
    assert len(data) > 200


def test_resume_pdf_is_a_valid_pdf():
    rewrite = {
        "bullets": [
            {
                "section": "Experience",
                "original_bullet": "Built APIs.",
                "rewritten_bullet": "Architected FastAPI services handling 1M requests/day.",
                "rationale": "Quantified impact.",
            }
        ],
        "summary_of_changes": "Tightened bullets.",
    }
    data = build_resume_pdf(rewrite, job_title="Senior Backend Engineer", company="Acme Corp")
    assert isinstance(data, (bytes, bytearray))
    assert bytes(data[:5]) == b"%PDF-"
    assert len(data) > 400


def test_resume_pdf_survives_unicode_without_crashing():
    # Smart punctuation + accents must not crash fpdf2's Latin-1 core fonts.
    rewrite = {
        "bullets": [
            {
                "section": "Exp",
                "original_bullet": "x",
                "rewritten_bullet": "Led — “scaled” the platform • 99.9% uptime",
                "rationale": "r",
            }
        ]
    }
    data = build_resume_pdf(rewrite, job_title="Señor Engineer", company="Acmé")
    assert bytes(data[:5]) == b"%PDF-"
