"""
Offline alert-engine smoke test.
Run only after dependencies have been installed:
    python TEST_ALERTS.py
It does NOT connect to flespi or send Twilio messages unless credentials are configured.
"""
from pathlib import Path
import tempfile
from app.database import Database
from app.alerts import AlertEngine

db = Database(Path(tempfile.gettempdir()) / "possl_alert_test.db")
engine = AlertEngine(db)
engine.save_config({
    "ignition_enabled": True,
    "movement_enabled": True,
    "voltage_enabled": True,
    "voltage_threshold": 12.2,
    "cooldown_seconds": 0,
})

engine.evaluate({"engine.ignition.status": False, "movement.status": False, "external.powersource.voltage": 13.4})
engine.evaluate({"engine.ignition.status": True, "movement.status": False, "external.powersource.voltage": 13.4})
engine.evaluate({"engine.ignition.status": True, "movement.status": True, "external.powersource.voltage": 13.4})
engine.evaluate({"engine.ignition.status": True, "movement.status": True, "external.powersource.voltage": 11.9})

for alert in db.list_alerts():
    print(alert["type"], "-", alert["title"])
