import asyncio
import time
from contextlib import asynccontextmanager
from datetime import datetime, timedelta

from fastapi import FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from .alerts import AlertEngine
from .config import settings
from .database import Database
from .flespi import FlespiClient, get_history
from .state import telemetry_state
from .trips import create_trips


db = Database(settings.db_path)
alerts = AlertEngine(db)
flespi = FlespiClient(alerts.evaluate)


class AlertConfigModel(BaseModel):
    ignition_enabled: bool = True
    movement_enabled: bool = True
    voltage_enabled: bool = True
    voltage_threshold: float = Field(default=12.0, ge=0, le=30)
    voltage_hysteresis: float = Field(default=0.2, ge=0, le=5)
    cooldown_seconds: int = Field(default=120, ge=0, le=86400)
    sms_enabled: bool = False
    whatsapp_enabled: bool = False
    push_enabled: bool = True


class PushTokenModel(BaseModel):
    token: str


class PushTokenDeleteModel(BaseModel):
    token: str


class TestNotificationModel(BaseModel):
    sms: bool = False
    whatsapp: bool = False
    push: bool = False
    title: str = "PÖSSL Test Alert"
    message: str = "Test notification from the PÖSSL telematics backend."


@asynccontextmanager
async def lifespan(app: FastAPI):
    telemetry_state.set_loop(asyncio.get_running_loop())
    flespi.start()
    yield
    flespi.stop()


app = FastAPI(title="Pössl Telematics Backend", version="2.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_list,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
def root():
    return {
        "name": "Pössl Telematics Backend",
        "version": "2.1.0",
        "device_id": settings.flespi_device_id,
        "docs": "/docs",
    }


@app.get("/health")
def health():
    return {
        "ok": True,
        "mqtt_connected": telemetry_state.connected,
        "device_id": settings.flespi_device_id,
        "message_count": telemetry_state.message_count,
        "updated_at": telemetry_state.updated_at,
        "mqtt_host": settings.flespi_mqtt_host,
        "mqtt_port": settings.flespi_mqtt_port,
        "mqtt_tls": settings.flespi_mqtt_tls,
        "twilio_sms_configured": bool(
            settings.twilio_account_sid
            and settings.twilio_auth_token
            and settings.twilio_sms_from
            and settings.alert_sms_to
        ),
        "twilio_whatsapp_configured": bool(
            settings.twilio_account_sid
            and settings.twilio_auth_token
            and settings.twilio_whatsapp_from
            and settings.alert_whatsapp_to
        ),
        "push_registered_devices": len(db.push_tokens()),
        "twilio_trial_mode": settings.twilio_trial_mode,
        "twilio_sms_trial_template": settings.twilio_sms_trial_template if settings.twilio_trial_mode else None,
        "twilio_whatsapp_content_sid_configured": bool(settings.twilio_whatsapp_content_sid),
    }


@app.get("/api/status")
def status():
    return telemetry_state.snapshot()


@app.get("/api/alerts/config")
def get_alert_config():
    return alerts.config().__dict__


@app.put("/api/alerts/config")
def put_alert_config(config: AlertConfigModel):
    return alerts.save_config(config.model_dump()).__dict__


@app.get("/api/alerts")
def list_alerts(limit: int = Query(100, ge=1, le=500)):
    return db.list_alerts(limit)


@app.get("/api/notifications/status")
def notification_status():
    push_tokens = db.push_tokens()
    return {
        "sms": {
            "configured": bool(
                settings.twilio_account_sid
                and settings.twilio_auth_token
                and settings.twilio_sms_from
                and settings.alert_sms_to
            ),
            "from": settings.twilio_sms_from or None,
            "to": settings.alert_sms_to or None,
        },
        "whatsapp": {
            "configured": bool(
                settings.twilio_account_sid
                and settings.twilio_auth_token
                and settings.twilio_whatsapp_from
                and settings.alert_whatsapp_to
            ),
            "from": settings.twilio_whatsapp_from or None,
            "to": settings.alert_whatsapp_to or None,
        },
        "push": {
            "configured": bool(push_tokens),
            "registered_devices": len(push_tokens),
        },
        "twilio_trial_mode": settings.twilio_trial_mode,
        "sms_trial_template": settings.twilio_sms_trial_template if settings.twilio_trial_mode else None,
        "whatsapp_content_sid_configured": bool(settings.twilio_whatsapp_content_sid),
        "whatsapp_content_variables_configured": bool(settings.twilio_whatsapp_content_variables),
    }


@app.post("/api/notifications/test")
async def test_notification(data: TestNotificationModel):
    if not (data.sms or data.whatsapp or data.push):
        raise HTTPException(
            status_code=400,
            detail="Select at least one channel: sms, whatsapp, or push",
        )
    return await alerts.notifications.test_channels(
        data.title,
        data.message,
        sms=data.sms,
        whatsapp=data.whatsapp,
        push=data.push,
    )


@app.get("/api/push/status")
def push_status():
    tokens = db.push_tokens()
    return {
        "registered_devices": len(tokens),
        "configured": bool(tokens),
    }


@app.post("/api/push/register")
def register_push_token(data: PushTokenModel):
    db.add_push_token(data.token)
    return {
        "ok": True,
        "registered_devices": len(db.push_tokens()),
    }


@app.delete("/api/push/register")
def unregister_push_token(data: PushTokenDeleteModel):
    db.remove_push_token(data.token)
    return {
        "ok": True,
        "registered_devices": len(db.push_tokens()),
    }


@app.get("/api/trips")
async def trips(
    from_ts: int | None = None,
    to_ts: int | None = None,
    hours: int = Query(24, ge=1, le=24*31),
    include_messages: bool = False,
):
    now = int(time.time())
    to_ts = to_ts or now
    from_ts = from_ts or (to_ts - hours * 3600)
    try:
        messages = await get_history(from_ts, to_ts)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"flespi history request failed: {exc}")

    result = create_trips(messages)
    if not include_messages:
        for trip in result:
            trip.pop("messages", None)
    return {"from_ts": from_ts, "to_ts": to_ts, "trips": result}


@app.get("/api/trips/{trip_id}")
async def trip_detail(
    trip_id: int,
    from_ts: int | None = None,
    to_ts: int | None = None,
    hours: int = Query(24, ge=1, le=24*31),
):
    now = int(time.time())
    to_ts = to_ts or now
    from_ts = from_ts or (to_ts - hours * 3600)
    messages = await get_history(from_ts, to_ts)
    trips = create_trips(messages)
    for trip in trips:
        if trip["id"] == trip_id:
            return trip
    raise HTTPException(status_code=404, detail="Trip not found in selected range")


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    q = telemetry_state.subscribe()
    try:
        await websocket.send_json({"type": "snapshot", "data": telemetry_state.snapshot()})
        while True:
            event = await q.get()
            await websocket.send_json(event)
    except WebSocketDisconnect:
        pass
    finally:
        telemetry_state.unsubscribe(q)
