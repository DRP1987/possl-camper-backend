import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any


class Database:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = str(path)
        self.lock = threading.RLock()
        self._init()

    def _conn(self):
        conn = sqlite3.connect(self.path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    def _init(self):
        with self.lock, self._conn() as conn:
            conn.executescript("""
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS alerts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at REAL NOT NULL,
                type TEXT NOT NULL,
                title TEXT NOT NULL,
                message TEXT NOT NULL,
                telemetry_json TEXT,
                sms_status TEXT,
                whatsapp_status TEXT
            );

            CREATE TABLE IF NOT EXISTS push_tokens (
                token TEXT PRIMARY KEY,
                created_at REAL NOT NULL
            );
            """)

    def get_setting(self, key: str, default: Any = None):
        with self.lock, self._conn() as conn:
            row = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
            if not row:
                return default
            try:
                return json.loads(row["value"])
            except Exception:
                return row["value"]

    def set_setting(self, key: str, value: Any):
        with self.lock, self._conn() as conn:
            conn.execute(
                "INSERT INTO settings(key,value) VALUES(?,?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, json.dumps(value)),
            )

    def add_alert(self, alert_type: str, title: str, message: str, telemetry: dict,
                  sms_status: str = "", whatsapp_status: str = "") -> int:
        with self.lock, self._conn() as conn:
            cur = conn.execute(
                """INSERT INTO alerts(created_at,type,title,message,telemetry_json,sms_status,whatsapp_status)
                   VALUES(?,?,?,?,?,?,?)""",
                (time.time(), alert_type, title, message, json.dumps(telemetry), sms_status, whatsapp_status),
            )
            return int(cur.lastrowid)

    def update_delivery(self, alert_id: int, sms_status: str | None = None, whatsapp_status: str | None = None):
        with self.lock, self._conn() as conn:
            if sms_status is not None:
                conn.execute("UPDATE alerts SET sms_status=? WHERE id=?", (sms_status, alert_id))
            if whatsapp_status is not None:
                conn.execute("UPDATE alerts SET whatsapp_status=? WHERE id=?", (whatsapp_status, alert_id))

    def list_alerts(self, limit: int = 100) -> list[dict]:
        with self.lock, self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM alerts ORDER BY id DESC LIMIT ?", (min(max(limit, 1), 500),)
            ).fetchall()
        result = []
        for r in rows:
            item = dict(r)
            try:
                item["telemetry"] = json.loads(item.pop("telemetry_json") or "{}")
            except Exception:
                item["telemetry"] = {}
                item.pop("telemetry_json", None)
            result.append(item)
        return result

    def add_push_token(self, token: str):
        with self.lock, self._conn() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO push_tokens(token,created_at) VALUES(?,?)",
                (token, time.time()),
            )

    def remove_push_token(self, token: str):
        with self.lock, self._conn() as conn:
            conn.execute("DELETE FROM push_tokens WHERE token=?", (token,))

    def push_tokens(self) -> list[str]:
        with self.lock, self._conn() as conn:
            rows = conn.execute("SELECT token FROM push_tokens").fetchall()
        return [r["token"] for r in rows]
