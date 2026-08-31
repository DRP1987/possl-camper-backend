import json
import ssl
import threading
import time
from typing import Callable

import httpx
import paho.mqtt.client as mqtt

from .config import settings
from .state import telemetry_state


class FlespiClient:
    def __init__(self, on_message: Callable[[dict], None]):
        self.on_message_callback = on_message
        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=f"possl-backend-{int(time.time())}")
        self.client.username_pw_set(settings.flespi_token, "")

        if settings.flespi_mqtt_tls:
            self.client.tls_set(cert_reqs=ssl.CERT_REQUIRED)

        self.client.reconnect_delay_set(min_delay=2, max_delay=30)
        self.thread: threading.Thread | None = None

        self.client.on_connect = self._on_connect
        self.client.on_disconnect = self._on_disconnect
        self.client.on_message = self._on_message

    def start(self):
        print("")
        print("flespi MQTT configuration")
        print(f"Host: {settings.flespi_mqtt_host}")
        print(f"Port: {settings.flespi_mqtt_port}")
        print(f"TLS: {'ON' if settings.flespi_mqtt_tls else 'OFF'}")
        print(f"Device ID: {settings.flespi_device_id}")
        print("")

        if not settings.flespi_token:
            print("FLESPI_TOKEN is empty. MQTT will not start.")
            return

        self.client.connect_async(
            settings.flespi_mqtt_host,
            settings.flespi_mqtt_port,
            keepalive=45,
        )
        self.client.loop_start()

    def stop(self):
        try:
            self.client.loop_stop()
            self.client.disconnect()
        except Exception:
            pass

    def _on_connect(self, client, userdata, flags, reason_code, properties):
        # paho-mqtt 2.x passes a ReasonCode object here, not a plain int.
        # Use its public success/failure API instead of int(reason_code).
        try:
            is_failure = bool(reason_code.is_failure)
        except Exception:
            try:
                is_failure = int(getattr(reason_code, "value", reason_code)) != 0
            except Exception:
                is_failure = str(reason_code).lower() not in {"success", "0"}

        ok = not is_failure
        telemetry_state.set_connected(ok)

        if ok:
            device_id = settings.flespi_device_id

            rc1, mid1 = client.subscribe(
                f"flespi/message/gw/devices/{device_id}",
                qos=1,
            )
            rc2, mid2 = client.subscribe(
                f"flespi/state/gw/devices/{device_id}/telemetry/+",
                qos=1,
            )

            print(f"Connected to flespi MQTT for device {device_id}")
            print(
                "Subscribed to device messages and telemetry "
                f"(message rc={rc1}, telemetry rc={rc2})"
            )
        else:
            print(
                "flespi MQTT connection rejected: "
                f"{getattr(reason_code, 'getName', lambda: str(reason_code))()}"
            )

    def _on_disconnect(self, client, userdata, disconnect_flags, reason_code, properties):
        telemetry_state.set_connected(False)
        try:
            reason_text = reason_code.getName()
        except Exception:
            reason_text = str(reason_code)
        print(f"Disconnected from flespi MQTT: {reason_text}")

    def _on_message(self, client, userdata, message):
        payload = message.payload.decode("utf-8", errors="replace")
        topic = message.topic
        data = {}

        source_ts = None
        if "/telemetry/" in topic:
            name = topic.split("/telemetry/", 1)[1]
            try:
                parsed = json.loads(payload)
                if isinstance(parsed, dict):
                    value = parsed.get("value") if "value" in parsed else parsed
                    source_ts = parsed.get("ts")
                else:
                    value = parsed
            except Exception:
                value = payload
            data[name] = value

            if name == "position" and isinstance(value, dict):
                mapping = {
                    "latitude": "position.latitude",
                    "longitude": "position.longitude",
                    "speed": "position.speed",
                    "altitude": "position.altitude",
                    "direction": "position.direction",
                    "satellites": "position.satellites",
                }
                for src, dst in mapping.items():
                    if src in value:
                        data[dst] = value[src]
        else:
            try:
                parsed = json.loads(payload)
                if isinstance(parsed, dict):
                    data = parsed
            except Exception:
                return

        if data:
            telemetry_state.update_message(data, source_timestamp=source_ts)
            self.on_message_callback(data)


async def get_latest_telemetry() -> tuple[dict, float]:
    url = f"https://flespi.io/gw/devices/{settings.flespi_device_id}/telemetry/all"
    headers = {"Authorization": f"FlespiToken {settings.flespi_token}", "Accept": "application/json"}
    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.get(url, headers=headers)
        response.raise_for_status()
        payload = response.json()
    result = payload.get("result", payload) if isinstance(payload, dict) else payload
    if isinstance(result, list):
        result = result[0] if result else {}
    telemetry_obj = result.get("telemetry", result) if isinstance(result, dict) else {}
    flat = {}
    newest_ts = 0.0
    if isinstance(telemetry_obj, dict):
        for name, item in telemetry_obj.items():
            if isinstance(item, dict) and "value" in item:
                flat[name] = item.get("value")
                try:
                    newest_ts = max(newest_ts, float(item.get("ts") or 0))
                except Exception:
                    pass
            else:
                flat[name] = item
    return flat, newest_ts


async def get_history(from_ts: int, to_ts: int, count: int = 20000) -> list[dict]:
    url = f"https://flespi.io/gw/devices/{settings.flespi_device_id}/messages"
    params = {"data": json.dumps({"from": from_ts, "to": to_ts, "count": min(count, 20000)})}
    headers = {"Authorization": f"FlespiToken {settings.flespi_token}", "Accept": "application/json"}
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.get(url, params=params, headers=headers)
        response.raise_for_status()
        payload = response.json()
    result = payload if isinstance(payload, list) else payload.get("result", [])
    return [x for x in result if isinstance(x, dict)]
