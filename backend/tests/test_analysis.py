"""Tests for the analysis endpoints and the iCalendar builder."""

import app.services.ats as ats_service
import app.services.interview_grading as grading_service
import app.services.salary as salary_service
from app.schemas import ATSScore, InterviewGrade, NegotiationScript, SalaryCoaching
from app.services.calendar_export import build_followup_ics


class _FakeChat:
    """A fake chat model whose structured output returns a fixed result."""

    def __init__(self, result):
        self._result = result

    def with_structured_output(self, schema, **_kwargs):
        result = self._result

        class _Structured:
            def invoke(self, _messages):
                return result

        return _Structured()


# --- ATS score ------------------------------------------------------------
def test_ats_score(client, auth_headers, completed_role, monkeypatch):
    monkeypatch.setattr(
        ats_service, "get_chat_model",
        lambda: _FakeChat(ATSScore(score=82, feedback=["Add Kubernetes.", "Mention SQL joins."])),
    )
    response = client.post("/roles/%d/ats-score" % completed_role["role_id"], headers=auth_headers)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["score"] == 82
    assert 2 <= len(body["feedback"]) <= 3


def test_ats_score_clamps_out_of_range(client, auth_headers, completed_role, monkeypatch):
    monkeypatch.setattr(ats_service, "get_chat_model", lambda: _FakeChat(ATSScore(score=140, feedback=["x"])))
    response = client.post("/roles/%d/ats-score" % completed_role["role_id"], headers=auth_headers)
    assert response.json()["score"] == 100


# --- interview grade ------------------------------------------------------
def test_interview_grade(client, auth_headers, completed_role, monkeypatch):
    monkeypatch.setattr(
        grading_service, "get_chat_model",
        lambda: _FakeChat(InterviewGrade(score=75, assessment="Solid.", strengths=["clear"], improvements=["add metrics"])),
    )
    payload = {"question": "Tell me about a project.", "sample_answer": "I built X.", "user_answer": "Um, I built an API."}
    response = client.post("/roles/%d/interview/grade" % completed_role["role_id"], json=payload, headers=auth_headers)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["score"] == 75
    assert body["improvements"] == ["add metrics"]


def test_interview_grade_requires_user_answer(client, auth_headers, completed_role):
    payload = {"question": "Q?", "sample_answer": "A", "user_answer": ""}  # empty -> 422
    response = client.post("/roles/%d/interview/grade" % completed_role["role_id"], json=payload, headers=auth_headers)
    assert response.status_code == 422


# --- salary coach ---------------------------------------------------------
def test_salary_coach(client, auth_headers, completed_role, monkeypatch):
    coaching = SalaryCoaching(scripts=[
        NegotiationScript(title="Aggressive / Market-Rate", body="Script A."),
        NegotiationScript(title="Value-Based / Equity-Focused", body="Script B."),
    ])
    monkeypatch.setattr(salary_service, "get_chat_model", lambda: _FakeChat(coaching))
    response = client.post(
        "/roles/%d/salary-coach" % completed_role["role_id"], json={"offered_salary": "120000"}, headers=auth_headers
    )
    assert response.status_code == 200, response.text
    scripts = response.json()["scripts"]
    assert len(scripts) == 2
    assert scripts[0]["title"] == "Aggressive / Market-Rate"


def test_salary_coach_requires_offer(client, auth_headers, completed_role):
    response = client.post("/roles/%d/salary-coach" % completed_role["role_id"], json={"offered_salary": ""}, headers=auth_headers)
    assert response.status_code == 422


# --- calendar export ------------------------------------------------------
def test_calendar_ics_endpoint(client, auth_headers, completed_role):
    response = client.get("/roles/%d/export/calendar" % completed_role["role_id"], headers=auth_headers)
    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("text/calendar")
    text = response.content.decode()
    assert text.startswith("BEGIN:VCALENDAR")
    assert "SUMMARY:Follow up with Acme Corp for Senior Backend Engineer" in text
    assert "END:VCALENDAR" in text


def test_ics_builder_one_week_out_and_escaped():
    from datetime import datetime, timedelta, timezone

    ics = build_followup_ics("Acme, Inc.", "Engineer")
    # The comma in the company name must be escaped (RFC 5545).
    assert "SUMMARY:Follow up with Acme\\, Inc. for Engineer" in ics
    expected_date = (datetime.now(timezone.utc) + timedelta(days=7)).strftime("%Y%m%d")
    assert ("DTSTART;VALUE=DATE:" + expected_date) in ics


# --- ownership ------------------------------------------------------------
def test_analysis_endpoints_require_ownership(client, auth_headers, completed_role):
    client.post("/auth/register", json={"email": "intruder@example.com", "password": "supersecret123"})
    token = client.post("/auth/login", json={"email": "intruder@example.com", "password": "supersecret123"}).json()["access_token"]
    intruder = {"Authorization": "Bearer " + token}
    rid = completed_role["role_id"]
    assert client.post("/roles/%d/ats-score" % rid, headers=intruder).status_code == 404
    assert client.get("/roles/%d/export/calendar" % rid, headers=intruder).status_code == 404
