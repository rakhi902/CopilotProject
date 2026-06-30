"""Generate a follow-up calendar event as an iCalendar (.ics) file.

No third-party dependency needed: a follow-up reminder is a tiny, well-specified
document, so we build a spec-compliant VCALENDAR by hand (RFC 5545, CRLF line
endings). The event is an all-day reminder a week out; all-day sidesteps timezone
ambiguity across Google Calendar, Outlook, and Apple Calendar.
"""

from datetime import datetime, timedelta, timezone
from uuid import uuid4


def _escape(text: str) -> str:
    """Escape text for an iCalendar property value (RFC 5545 section 3.3.11)."""
    return (
        (text or "")
        .replace("\\", "\\\\")
        .replace(";", "\\;")
        .replace(",", "\\,")
        .replace("\n", "\\n")
    )


def build_followup_ics(company: str, job_title: str, days_ahead: int = 7) -> str:
    """Build the .ics text for a "follow up" all-day event ``days_ahead`` out.

    Returns the full iCalendar document as a string with CRLF line endings.
    """
    now = datetime.now(timezone.utc)
    start_date = (now + timedelta(days=days_ahead)).date()
    end_date = start_date + timedelta(days=1)  # DTEND is exclusive for all-day events

    summary = _escape(f"Follow up with {company} for {job_title}")
    description = _escape(
        f"Send a follow-up note to {company} about your {job_title} application."
    )

    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Job Application Co-Pilot//EN",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        "BEGIN:VEVENT",
        f"UID:{uuid4()}@jobcopilot",
        f"DTSTAMP:{now.strftime('%Y%m%dT%H%M%SZ')}",
        f"DTSTART;VALUE=DATE:{start_date.strftime('%Y%m%d')}",
        f"DTEND;VALUE=DATE:{end_date.strftime('%Y%m%d')}",
        f"SUMMARY:{summary}",
        f"DESCRIPTION:{description}",
        "BEGIN:VALARM",
        "TRIGGER:PT0S",
        "ACTION:DISPLAY",
        f"DESCRIPTION:{summary}",
        "END:VALARM",
        "END:VEVENT",
        "END:VCALENDAR",
    ]
    return "\r\n".join(lines) + "\r\n"
