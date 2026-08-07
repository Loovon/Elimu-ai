"""
elimu_ai/email_alerts.py

Email alert system — sends structured alerts when critical failures occur.

Triggers:
  - Gemini unavailable
  - Database disconnected
  - Scheduler crashed
  - Tool timeout
  - Hallucination detected
  - Repeated failures (>3 in 1 hour)

Uses SendGrid if SENDGRID_API_KEY is set, otherwise logs only.
Never crashes — all failures are caught and logged.
"""

from __future__ import annotations

import logging
import os
import traceback
from datetime import datetime, timezone
from typing import List, Optional

logger = logging.getLogger(__name__)

_ALERT_FROM    = os.getenv("ALERT_FROM_EMAIL", "alerts@elimuai.com")
_ALERT_TO      = os.getenv("ALERT_TO_EMAIL", "admin@elimutalks.com")
_SENDGRID_KEY  = os.getenv("SENDGRID_API_KEY", "")

# In-memory rate limit: don't send >1 alert per type per 10 minutes
_last_sent: dict = {}
_COOLDOWN_SECONDS = 600


def _can_send(alert_type: str) -> bool:
    """Rate-limit: return True if we haven't sent this alert type recently."""
    import time
    last = _last_sent.get(alert_type, 0)
    if time.monotonic() - last > _COOLDOWN_SECONDS:
        _last_sent[alert_type] = time.monotonic()
        return True
    return False


def send_alert(
    subject: str,
    body: str,
    alert_type: str = "general",
    exc: Optional[Exception] = None,
    suggested_fix: str = "",
) -> None:
    """
    Send an email alert. Rate-limited per alert_type.
    Falls back to logging if SendGrid is not configured.
    """
    if not _can_send(alert_type):
        logger.debug("email_alerts: rate-limited alert_type=%r", alert_type)
        return

    timestamp = datetime.now(tz=timezone.utc).isoformat()
    tb_text = traceback.format_exc() if exc else ""

    full_body = f"""\
Elimu AI Alert
==============
Type:      {alert_type}
Time:      {timestamp}
Subject:   {subject}

Details:
{body}

{"Traceback:" if tb_text else ""}
{tb_text}

Suggested Fix:
{suggested_fix or "Review logs and restart affected service if needed."}

---
This is an automated alert from Elimu AI v{_get_version()}.
"""

    if _SENDGRID_KEY:
        _send_via_sendgrid(subject=f"[ElimuAI Alert] {subject}", body=full_body)
    else:
        logger.warning(
            "EMAIL ALERT [%s]: %s\n%s",
            alert_type, subject, body[:200],
        )

    # Always persist to DB
    _persist_alert(alert_type, subject, body, tb_text, suggested_fix)


def _send_via_sendgrid(subject: str, body: str) -> None:
    try:
        from sendgrid import SendGridAPIClient
        from sendgrid.helpers.mail import Mail
        msg = Mail(
            from_email=_ALERT_FROM,
            to_emails=_ALERT_TO,
            subject=subject,
            plain_text_content=body,
        )
        sg = SendGridAPIClient(_SENDGRID_KEY)
        response = sg.send(msg)
        logger.info("email_alerts: sent via SendGrid (status=%d)", response.status_code)
    except Exception as exc:
        logger.error("email_alerts: SendGrid send failed: %s", exc)


def _persist_alert(
    alert_type: str,
    subject: str,
    body: str,
    traceback_text: str,
    suggested_fix: str,
) -> None:
    try:
        from elimu_ai.db.repositories import AgentLogRepository
        AgentLogRepository().log_alert(
            alert_type=alert_type,
            subject=subject,
            body=body[:1000],
            traceback_text=traceback_text[:2000],
            suggested_fix=suggested_fix,
        )
    except Exception as exc:
        logger.debug("email_alerts: DB persist failed: %s", exc)


def _get_version() -> str:
    try:
        from elimu_ai.config import SYSTEM_VERSION
        return SYSTEM_VERSION
    except Exception:
        return "unknown"


# ── Convenience helpers ───────────────────────────────────────────────────────

def alert_gemini_unavailable(exc: Optional[Exception] = None) -> None:
    send_alert(
        subject="Gemini API unavailable",
        body="The Gemini API client failed to initialise or all retries were exhausted.",
        alert_type="gemini_down",
        exc=exc,
        suggested_fix="Check GEMINI_API_KEY and Google API quota. Restart the service after fixing.",
    )


def alert_db_disconnected(exc: Optional[Exception] = None) -> None:
    send_alert(
        subject="PostgreSQL connection lost",
        body="The database connection pool failed. Analytics and memory writes are queued.",
        alert_type="db_down",
        exc=exc,
        suggested_fix="Check DATABASE_URL and PostgreSQL server status.",
    )


def alert_scheduler_crashed(exc: Optional[Exception] = None) -> None:
    send_alert(
        subject="Background scheduler crashed",
        body="The APScheduler instance stopped unexpectedly.",
        alert_type="scheduler_crash",
        exc=exc,
        suggested_fix="Scheduler will auto-restart on next health check cycle.",
    )


def alert_tool_timeout(tool_name: str, timeout_seconds: int) -> None:
    send_alert(
        subject=f"Tool timeout: {tool_name}",
        body=f"Tool '{tool_name}' exceeded {timeout_seconds}s timeout.",
        alert_type=f"tool_timeout_{tool_name}",
        suggested_fix=f"Check if {tool_name} dependencies are available.",
    )


def alert_hallucination_detected(question: str, issues: List[str]) -> None:
    send_alert(
        subject="Hallucination detected in AI response",
        body=f"Question: {question[:200]}\nIssues: {'; '.join(issues)}",
        alert_type="hallucination",
        suggested_fix="Review verifier thresholds and tool outputs.",
    )


def alert_repeated_failures(tool: str, count: int, window_hours: int = 1) -> None:
    send_alert(
        subject=f"Repeated failures: {tool} ({count} in {window_hours}h)",
        body=f"Tool '{tool}' has failed {count} times in the last {window_hours} hour(s).",
        alert_type=f"repeated_failures_{tool}",
        suggested_fix=f"Check {tool} dependencies and error logs.",
    )
