"""Test script — create a mock anomaly, generate alert via Claude, send email."""

import os
import sys
from datetime import datetime, timezone

from dotenv import load_dotenv

load_dotenv()

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from src.agents.alert_agent import AlertAgent, send_email  # noqa: E402
from src.schemas.anomaly import AnomalyEvent, DetectionMethod, Pollutant, Severity  # noqa: E402

mock_event = AnomalyEvent(
    event_id="test-001",
    station_id="IL-001",
    station_name="תל אביב — רחוב ארלוזורוב",
    timestamp=datetime.now(timezone.utc),
    pollutant=Pollutant.NO2,
    value=85.3,
    baseline_value=32.0,
    anomaly_score=0.92,
    severity=Severity.HIGH,
    detection_method=DetectionMethod.ENSEMBLE,
    latitude=32.0853,
    longitude=34.7818,
)

print("1. Creating AlertAgent...")
agent = AlertAgent()

print("2. Generating alert via Claude Haiku...")
alert = agent.generate_alert(mock_event)
print(f"   Title: {alert.title}")
print(f"   Body: {alert.body}")
print(f"   Action: {alert.recommended_action}")

smtp_user = os.environ.get("SMTP_USER", "")
if not smtp_user:
    print("\n3. SMTP_USER not set in .env — skipping email send.")
    print("   Add SMTP_USER and SMTP_PASSWORD to .env to test email delivery.")
else:
    print(f"\n3. Sending email to {smtp_user}...")
    ok = send_email(alert, to_addresses=[smtp_user])
    if ok:
        print("   Email sent! Check your inbox.")
    else:
        print("   Email failed. Check the logs above.")
