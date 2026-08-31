import asyncio
import time
from typing import Any


class TelemetryState:
    def __init__(self):
        self.values: dict[str, Any] = {}
        self.last_message: dict[str, Any] = {}
        self.updated_at: float = 0.0
        self.received_at: float = 0.0
        self.connected: bool = False
        self.message_count: int = 0
        self._listeners: set[asyncio.Queue] = set()
        self.loop: asyncio.AbstractEventLoop | None = None

    def set_loop(self, loop: asyncio.AbstractEventLoop):
        self.loop = loop

    def set_connected(self, value: bool):
        self.connected = value
        self._broadcast_threadsafe({"type": "connection", "connected": value})

    def update_message(self, message: dict, source_timestamp: float | None = None):
        self.last_message = message
        self.values.update(message)
        now = time.time()
        self.received_at = now
        candidates = [message.get("server.timestamp"), source_timestamp, message.get("timestamp")]
        tracker_ts = None
        for candidate in candidates:
            try:
                value = float(candidate)
                if value > 0:
                    tracker_ts = value
                    break
            except Exception:
                pass
        if tracker_ts is None:
            tracker_ts = now
        self.updated_at = max(self.updated_at, tracker_ts)
        self.message_count += 1
        self._broadcast_threadsafe({
            "type": "telemetry",
            "data": message,
            "snapshot": self.snapshot(),
        })

    def snapshot(self) -> dict:
        return {
            "connected": self.connected,
            "updated_at": self.updated_at,
            "received_at": self.received_at,
            "message_count": self.message_count,
            "telemetry": dict(self.values),
        }

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=20)
        self._listeners.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue):
        self._listeners.discard(q)

    async def _broadcast(self, event: dict):
        stale = []
        for q in list(self._listeners):
            try:
                if q.full():
                    q.get_nowait()
                q.put_nowait(event)
            except Exception:
                stale.append(q)
        for q in stale:
            self._listeners.discard(q)

    def _broadcast_threadsafe(self, event: dict):
        if not self.loop:
            return
        try:
            asyncio.run_coroutine_threadsafe(self._broadcast(event), self.loop)
        except Exception:
            pass


telemetry_state = TelemetryState()
