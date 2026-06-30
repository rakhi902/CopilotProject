"""Tests for the roles + drafts endpoints and the end-to-end generation flow."""

import time


def submit_application(client, headers, pdf_bytes):
    """POST /roles with a PDF + JD and return the raw response."""
    files = {"resume_pdf": ("resume.pdf", pdf_bytes, "application/pdf")}
    data = {
        "job_title": "Senior Backend Engineer",
        "company": "Acme Corp",
        "jd_text": "Seeking a FastAPI engineer with SQL.",
    }
    return client.post("/roles", data=data, files=files, headers=headers)


def poll_until_finished(client, draft_id, headers, attempts=50):
    """Poll a draft until it leaves the in-progress states; return the final JSON."""
    body = {}
    for _ in range(attempts):
        body = client.get("/drafts/%d" % draft_id, headers=headers).json()
        if body["status"] in ("completed", "failed"):
            return body
        time.sleep(0.02)
    return body


def test_create_role_runs_generation_to_completion(client, auth_headers, sample_pdf_bytes, mock_llm):
    response = submit_application(client, auth_headers, sample_pdf_bytes)
    assert response.status_code == 202, response.text

    body = response.json()
    assert body["status"] == "pending"
    assert body["role"]["has_source_resume"] is True

    finished = poll_until_finished(client, body["draft_id"], auth_headers)
    assert finished["status"] == "completed", finished
    assert finished["fit_analysis"]["fit_score"] == 80
    assert finished["resume_rewrite"]["bullets"][0]["rewritten_bullet"].startswith("Architected FastAPI")
    assert finished["cover_letter"].startswith("Dear Hiring Manager")
    assert len(finished["interview_qa"]["questions"]) == 10


def test_list_roles_returns_the_created_role(client, auth_headers, sample_pdf_bytes, mock_llm):
    submit_application(client, auth_headers, sample_pdf_bytes)
    roles = client.get("/roles", headers=auth_headers).json()
    assert len(roles) == 1
    assert roles[0]["company"] == "Acme Corp"


def test_non_pdf_upload_is_rejected(client, auth_headers):
    files = {"resume_pdf": ("resume.txt", b"i am not a pdf", "text/plain")}
    data = {"job_title": "Engineer", "company": "Acme", "jd_text": "A role."}
    response = client.post("/roles", data=data, files=files, headers=auth_headers)
    assert response.status_code == 422


def test_reading_a_draft_requires_authentication(client, auth_headers, sample_pdf_bytes, mock_llm):
    body = submit_application(client, auth_headers, sample_pdf_bytes).json()
    assert client.get("/drafts/%d" % body["draft_id"]).status_code in (401, 403)


def test_one_user_cannot_read_another_users_draft(client, sample_pdf_bytes, mock_llm):
    # First user creates an application.
    client.post("/auth/register", json={"email": "owner@example.com", "password": "supersecret123"})
    owner_token = client.post("/auth/login", json={"email": "owner@example.com", "password": "supersecret123"}).json()["access_token"]
    owner_headers = {"Authorization": "Bearer " + owner_token}
    body = submit_application(client, owner_headers, sample_pdf_bytes).json()

    # A second user must not be able to read it (hidden behind a 404).
    client.post("/auth/register", json={"email": "intruder@example.com", "password": "supersecret123"})
    intruder_token = client.post("/auth/login", json={"email": "intruder@example.com", "password": "supersecret123"}).json()["access_token"]
    intruder_headers = {"Authorization": "Bearer " + intruder_token}
    assert client.get("/drafts/%d" % body["draft_id"], headers=intruder_headers).status_code == 404


# JD URL, application status, delete, regenerate, export
def test_create_via_jd_url_scrapes_the_jd(client, auth_headers, sample_pdf_bytes, mock_llm, monkeypatch):
    import app.api.roles as roles_api

    monkeypatch.setattr(roles_api, "scrape_jd_text", lambda url: "Scraped: FastAPI engineer needed.")
    files = {"resume_pdf": ("resume.pdf", sample_pdf_bytes, "application/pdf")}
    data = {"job_title": "Engineer", "company": "Acme", "jd_url": "https://example.com/job"}  # no jd_text
    response = client.post("/roles", data=data, files=files, headers=auth_headers)
    assert response.status_code == 202, response.text

    role = client.get("/roles/%d" % response.json()["role"]["id"], headers=auth_headers).json()
    assert role["jd_url"] == "https://example.com/job"
    assert role["application_status"] == "Not Applied"


def test_create_requires_jd_text_or_url(client, auth_headers, sample_pdf_bytes):
    files = {"resume_pdf": ("resume.pdf", sample_pdf_bytes, "application/pdf")}
    data = {"job_title": "Engineer", "company": "Acme"}  # neither jd_text nor jd_url
    response = client.post("/roles", data=data, files=files, headers=auth_headers)
    assert response.status_code == 422


def test_update_application_status_persists(client, auth_headers, sample_pdf_bytes, mock_llm):
    role_id = submit_application(client, auth_headers, sample_pdf_bytes).json()["role"]["id"]
    response = client.patch("/roles/%d" % role_id, json={"application_status": "Interviewing"}, headers=auth_headers)
    assert response.status_code == 200, response.text
    assert response.json()["application_status"] == "Interviewing"
    # Persisted across a fresh read.
    assert client.get("/roles/%d" % role_id, headers=auth_headers).json()["application_status"] == "Interviewing"


def test_update_application_status_rejects_invalid_value(client, auth_headers, sample_pdf_bytes, mock_llm):
    role_id = submit_application(client, auth_headers, sample_pdf_bytes).json()["role"]["id"]
    response = client.patch("/roles/%d" % role_id, json={"application_status": "Ghosted"}, headers=auth_headers)
    assert response.status_code == 422


def test_delete_role(client, auth_headers, sample_pdf_bytes, mock_llm):
    role_id = submit_application(client, auth_headers, sample_pdf_bytes).json()["role"]["id"]
    assert client.delete("/roles/%d" % role_id, headers=auth_headers).status_code == 204
    assert client.get("/roles/%d" % role_id, headers=auth_headers).status_code == 404


def test_bulk_delete_only_removes_owned_roles(client, auth_headers, sample_pdf_bytes, mock_llm):
    id1 = submit_application(client, auth_headers, sample_pdf_bytes).json()["role"]["id"]
    id2 = submit_application(client, auth_headers, sample_pdf_bytes).json()["role"]["id"]
    response = client.post("/roles/bulk-delete", json={"ids": [id1, id2, 999999]}, headers=auth_headers)
    assert response.status_code == 200, response.text
    assert set(response.json()["deleted_ids"]) == {id1, id2}  # the bogus id is ignored
    assert client.get("/roles", headers=auth_headers).json() == []


def test_regenerate_single_artifact(client, auth_headers, sample_pdf_bytes, mock_llm):
    body = submit_application(client, auth_headers, sample_pdf_bytes).json()
    role_id, draft_id = body["role"]["id"], body["draft_id"]
    assert poll_until_finished(client, draft_id, auth_headers)["status"] == "completed"

    response = client.post("/roles/%d/regenerate/cover" % role_id, headers=auth_headers)
    assert response.status_code == 202, response.text
    assert response.json()["artifact"] == "cover"

    refreshed = poll_until_finished(client, draft_id, auth_headers)
    assert refreshed["status"] == "completed"
    assert refreshed["cover_letter"].startswith("Dear Hiring Manager")
    # Other artifacts remain intact (only the cover letter was re-run).
    assert refreshed["fit_analysis"]["fit_score"] == 80


def test_regenerate_unknown_artifact_is_rejected(client, auth_headers, sample_pdf_bytes, mock_llm):
    role_id = submit_application(client, auth_headers, sample_pdf_bytes).json()["role"]["id"]
    assert client.post("/roles/%d/regenerate/banana" % role_id, headers=auth_headers).status_code == 422


def test_export_cover_letter_docx(client, auth_headers, sample_pdf_bytes, mock_llm):
    body = submit_application(client, auth_headers, sample_pdf_bytes).json()
    poll_until_finished(client, body["draft_id"], auth_headers)
    response = client.get("/roles/%d/export/cover-letter.docx" % body["role"]["id"], headers=auth_headers)
    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("application/vnd.openxmlformats")
    assert response.content[:2] == b"PK"


def test_export_resume_pdf(client, auth_headers, sample_pdf_bytes, mock_llm):
    body = submit_application(client, auth_headers, sample_pdf_bytes).json()
    poll_until_finished(client, body["draft_id"], auth_headers)
    response = client.get("/roles/%d/export/resume.pdf" % body["role"]["id"], headers=auth_headers)
    assert response.status_code == 200, response.text
    assert response.headers["content-type"] == "application/pdf"
    assert response.content[:5] == b"%PDF-"
