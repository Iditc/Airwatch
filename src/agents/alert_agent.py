"""Alert Agent — generates human-readable alerts from anomaly events using Claude."""

import os
import smtplib
from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import anthropic
import structlog

from src.schemas.agent_io import AlertPayload
from src.schemas.anomaly import AnomalyEvent

logger = structlog.get_logger(__name__)

SEVERITY_EMOJI = {
    "critical": "🔴",
    "high": "🟠",
    "medium": "🟡",
    "low": "🟢",
}

POLLUTANT_NAMES = {
    "no2": "NO₂ (חנקן דו-חמצני)",
    "o3": "O₃ (אוזון)",
    "pm25": "PM2.5 (חלקיקים עדינים)",
    "pm10": "PM10 (חלקיקים)",
    "so2": "SO₂ (גופרית דו-חמצנית)",
    "co": "CO (פחמן חד-חמצני)",
}

SYSTEM_PROMPT = """\
You are AirWatch Alert Agent — an air quality alerting system for Israel.
You receive anomaly events from ML models and generate clear, actionable alerts in Hebrew.

Guidelines:
- Write in Hebrew, concise and clear
- Include: what pollutant, where, how severe, when it's expected
- Add a recommended action for the public (e.g., avoid outdoor exercise)
- Keep the title under 60 characters
- Keep the body under 200 words
- Use the severity to calibrate urgency

Respond in JSON with these fields:
- title: short alert title in Hebrew
- body: explanation in Hebrew
- recommended_action: what people should do, in Hebrew
"""


class AlertAgent:
    """Generates alerts from AnomalyEvents using Claude."""

    def __init__(self, api_key: str | None = None) -> None:
        self.client = anthropic.Anthropic(
            api_key=api_key or os.environ.get("ANTHROPIC_API_KEY", ""),
        )

    def generate_alert(self, event: AnomalyEvent) -> AlertPayload:
        pollutant_name = POLLUTANT_NAMES.get(event.pollutant.value, event.pollutant.value)
        severity = event.severity.value

        user_message = (
            f"Anomaly detected:\n"
            f"- Station: {event.station_name}\n"
            f"- Pollutant: {pollutant_name}\n"
            f"- Current value: {event.value:.1f}\n"
            f"- Baseline (normal): {event.baseline_value:.1f}\n"
            f"- Anomaly score: {event.anomaly_score:.2f}\n"
            f"- Severity: {severity}\n"
            f"- Time: {event.timestamp.isoformat()}\n\n"
            f"Generate an alert for the public."
        )

        response = self.client.messages.create(
            model="claude-haiku-5-5",
            max_tokens=1024,
            output_config={"effort": "low"},
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_message}],
        )

        import json

        text = next((block.text for block in response.content if block.type == "text"), "{}")
        text = text.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1] if "\n" in text else text[3:]
            text = text.rsplit("```", 1)[0]
            text = text.strip()

        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            data = {
                "title": f"התראת זיהום אוויר — {event.station_name}",
                "body": text,
                "recommended_action": None,
            }

        logger.info(
            "alert_generated",
            event_id=event.event_id,
            station=event.station_name,
            severity=severity,
        )

        return AlertPayload(
            event_id=event.event_id,
            station_name=event.station_name,
            severity=severity,
            title=data.get("title", f"התראת זיהום — {event.station_name}"),
            body=data.get("body", ""),
            recommended_action=data.get("recommended_action"),
            timestamp=datetime.now(timezone.utc),
        )

    def generate_alerts(self, events: list[AnomalyEvent]) -> list[AlertPayload]:
        alerts: list[AlertPayload] = []
        for event in events:
            try:
                alert = self.generate_alert(event)
                alerts.append(alert)
            except Exception:
                logger.exception("alert_generation_failed", event_id=event.event_id)
        return alerts


def send_email(
    alert: AlertPayload,
    to_addresses: list[str],
    smtp_host: str = "",
    smtp_port: int = 587,
    smtp_user: str = "",
    smtp_password: str = "",
) -> bool:
    """Send an alert as an HTML email via SMTP."""
    smtp_host = smtp_host or os.environ.get("SMTP_HOST", "smtp.gmail.com")
    smtp_user = smtp_user or os.environ.get("SMTP_USER", "")
    smtp_password = smtp_password or os.environ.get("SMTP_PASSWORD", "")

    emoji = SEVERITY_EMOJI.get(alert.severity, "⚪")

    html_body = f"""\
<div dir="rtl" style="font-family: Arial, sans-serif; max-width: 600px;">
  <h2>{emoji} {alert.title}</h2>
  <p>{alert.body}</p>
  {
        "<p><strong>המלצה:</strong> " + alert.recommended_action + "</p>"
        if alert.recommended_action
        else ""
    }
  <hr>
  <p style="color: #888; font-size: 12px;">
    AirWatch | {alert.station_name} | {alert.severity} | {alert.timestamp:%Y-%m-%d %H:%M}
  </p>
</div>"""

    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"{emoji} {alert.title}"
    msg["From"] = smtp_user
    msg["To"] = ", ".join(to_addresses)
    msg.attach(MIMEText(f"{alert.title}\n\n{alert.body}", "plain", "utf-8"))
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    try:
        with smtplib.SMTP(smtp_host, smtp_port) as server:
            server.starttls()
            server.login(smtp_user, smtp_password)
            server.sendmail(smtp_user, to_addresses, msg.as_string())
        logger.info("email_sent", event_id=alert.event_id, recipients=len(to_addresses))
        return True
    except Exception:
        logger.exception("email_failed", event_id=alert.event_id)
        return False
