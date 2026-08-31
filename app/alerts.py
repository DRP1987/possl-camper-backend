import asyncio
import time
from dataclasses import dataclass
from typing import Any
from .database import Database
from .notifications import NotificationService
from .state import telemetry_state


@dataclass
class AlertConfig:
    ignition_enabled: bool = True
    movement_enabled: bool = True
    voltage_enabled: bool = True
    voltage_threshold: float = 12.0
    voltage_hysteresis: float = 0.2
    cooldown_seconds: int = 120
    sms_enabled: bool = False
    whatsapp_enabled: bool = False
    push_enabled: bool = True


class AlertEngine:
    def __init__(self, db: Database):
        self.db = db
        self.notifications = NotificationService(db)
        self.last_ignition: bool | None = None
        self.last_movement: bool | None = None
        self.last_voltage: float | None = None
        self.voltage_alarm_active = False
        self.last_fired: dict[str, float] = {}

    def config(self) -> AlertConfig:
        raw = self.db.get_setting("alert_config", {}) or {}
        defaults = AlertConfig()
        return AlertConfig(**{
            k: raw.get(k, getattr(defaults, k))
            for k in AlertConfig.__dataclass_fields__.keys()
        })

    def save_config(self, data: dict) -> AlertConfig:
        cfg = self.config()
        for k in AlertConfig.__dataclass_fields__:
            if k in data:
                setattr(cfg, k, data[k])
        cfg.voltage_threshold = float(cfg.voltage_threshold)
        cfg.voltage_hysteresis = max(0.0, float(cfg.voltage_hysteresis))
        cfg.cooldown_seconds = max(0, int(cfg.cooldown_seconds))
        self.db.set_setting("alert_config", cfg.__dict__)
        return cfg

    @staticmethod
    def first(message: dict, keys: list[str]):
        for k in keys:
            if k in message and message[k] is not None:
                return message[k]
        return None

    def evaluate(self, message: dict):
        cfg = self.config()
        ignition = self.first(message, ["engine.ignition.status", "ignition.status"])
        movement = self.first(message, ["movement.status"])
        speed = self.first(message, ["position.speed", "vehicle.speed", "can.vehicle.speed"])
        voltage = self.first(message, [
            "external.powersource.voltage",
            "vehicle.battery.voltage",
            "battery.voltage",
        ])

        if movement is None and speed is not None:
            try:
                movement = float(speed) > 2
            except Exception:
                pass

        if ignition is not None:
            current = bool(ignition)
            if self.last_ignition is not None and cfg.ignition_enabled and not self.last_ignition and current:
                self._fire("ignition", "PÖSSL: Ignition ON", self._message("Ignition switched ON", message), message)
            self.last_ignition = current

        if movement is not None:
            current = bool(movement)
            if self.last_movement is not None and cfg.movement_enabled and not self.last_movement and current:
                self._fire("movement", "PÖSSL: Movement detected", self._message("Vehicle started moving", message), message)
            self.last_movement = current

        if voltage is not None:
            try:
                v = float(voltage)
                if cfg.voltage_enabled:
                    if not self.voltage_alarm_active and v < cfg.voltage_threshold:
                        self.voltage_alarm_active = True
                        self._fire(
                            "voltage",
                            "PÖSSL: Low vehicle voltage",
                            self._message(
                                f"Voltage {v:.2f} V is below the configured {cfg.voltage_threshold:.2f} V threshold",
                                message,
                            ),
                            message,
                        )
                    elif self.voltage_alarm_active and v >= cfg.voltage_threshold + cfg.voltage_hysteresis:
                        self.voltage_alarm_active = False
                self.last_voltage = v
            except Exception:
                pass

    def _message(self, text: str, msg: dict) -> str:
        lat = msg.get("position.latitude")
        lon = msg.get("position.longitude")
        speed = self.first(msg, ["position.speed", "vehicle.speed", "can.vehicle.speed"])
        parts = [text]
        if speed is not None:
            parts.append(f"Speed: {speed} km/h")
        if lat is not None and lon is not None:
            parts.append(f"Location: {lat}, {lon}")
            parts.append(f"Map: https://maps.google.com/?q={lat},{lon}")
        return "\n".join(parts)

    def _fire(self, alert_type: str, title: str, message: str, telemetry: dict):
        cfg = self.config()
        now = time.time()
        if now - self.last_fired.get(alert_type, 0) < cfg.cooldown_seconds:
            return
        self.last_fired[alert_type] = now

        alert_id = self.db.add_alert(alert_type, title, message, telemetry)
        coro = self.notifications.send(
            alert_id,
            title,
            message,
            sms_enabled=cfg.sms_enabled,
            whatsapp_enabled=cfg.whatsapp_enabled,
            push_enabled=cfg.push_enabled,
        )

        # Alert evaluation runs in paho-mqtt's network thread. Schedule
        # notification delivery on FastAPI's asyncio loop instead of trying
        # to create an event loop in the MQTT thread.
        if telemetry_state.loop:
            try:
                asyncio.run_coroutine_threadsafe(coro, telemetry_state.loop)
                return
            except Exception:
                pass

        # If the service is being tested outside FastAPI, close the coroutine
        # rather than leaking an un-awaited coroutine.
        try:
            coro.close()
        except Exception:
            pass
