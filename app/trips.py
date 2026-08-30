from datetime import datetime
from math import radians, sin, cos, asin, sqrt
from typing import Any


def first(msg: dict, keys: list[str]):
    for k in keys:
        if k in msg and msg[k] is not None:
            return msg[k]
    return None


def ts(msg: dict) -> float:
    return float(msg.get("timestamp") or msg.get("server.timestamp") or 0)


def ignition(msg: dict):
    return first(msg, ["engine.ignition.status", "ignition.status"])


def position(msg: dict):
    try:
        lat = float(msg["position.latitude"])
        lon = float(msg["position.longitude"])
        if lat == 0 and lon == 0:
            return None
        return {"lat": lat, "lon": lon}
    except Exception:
        return None


def speed(msg: dict) -> float:
    try:
        return float(first(msg, ["position.speed", "vehicle.speed", "can.vehicle.speed"]) or 0)
    except Exception:
        return 0.0


def haversine(a: dict, b: dict) -> float:
    r = 6371.0
    lat1, lon1, lat2, lon2 = map(radians, [a["lat"], a["lon"], b["lat"], b["lon"]])
    dlat, dlon = lat2-lat1, lon2-lon1
    h = sin(dlat/2)**2 + cos(lat1)*cos(lat2)*sin(dlon/2)**2
    return 2*r*asin(sqrt(h))


def distance_km(messages: list[dict]) -> float:
    total = 0.0
    prev = None
    for msg in messages:
        p = position(msg)
        if not p:
            continue
        if prev:
            d = haversine(prev, p)
            if d < 20:
                total += d
        prev = p
    return total


def create_trips(messages: list[dict], off_gap_seconds: int = 600) -> list[dict]:
    """Create ignition-based trips matching the web dashboard logic.

    Ignition OFF > 10 minutes ends the trip at the first OFF message.
    The parked waiting period is excluded from duration and route.
    """
    messages = sorted([m for m in messages if ts(m) > 0], key=ts)
    raw_trips = []
    current = []
    off_start = None
    started = False

    def finish():
        nonlocal current, off_start
        if not current:
            off_start = None
            return
        trimmed = list(current)
        if off_start is not None:
            idx = next((j for j, msg in enumerate(trimmed) if ts(msg) >= off_start), None)
            if idx is not None:
                trimmed = trimmed[:idx + 1]
        if len(trimmed) >= 2:
            raw_trips.append(trimmed)
        current = []
        off_start = None

    for msg in messages:
        ign = ignition(msg); now = ts(msg)
        if not started:
            if ign is True:
                started = True; current = [msg]
            continue
        if ign is False:
            if off_start is None: off_start = now
            current.append(msg); continue
        if ign is True:
            if off_start is not None and now - off_start > off_gap_seconds:
                finish(); current = [msg]
            else:
                current.append(msg)
            off_start = None; continue
        if current: current.append(msg)

    finish()
    trips = []
    for k, records in enumerate(raw_trips, 1):
        speeds=[speed(x) for x in records]; moving=[v for v in speeds if v>2]
        st,et=ts(records[0]),ts(records[-1])
        trips.append({
            "id":k,"start_ts":st,"end_ts":et,
            "start_iso":datetime.fromtimestamp(st).isoformat(),
            "end_iso":datetime.fromtimestamp(et).isoformat(),
            "duration_seconds":max(0,et-st),
            "distance_km":round(distance_km(records),2),
            "max_speed":round(max(speeds) if speeds else 0,1),
            "avg_moving_speed":round(sum(moving)/len(moving) if moving else 0,1),
            "start_position":position(records[0]),"end_position":position(records[-1]),
            "points":len(records),"messages":records})
    return trips

