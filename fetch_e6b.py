#!/usr/bin/env python3
import json
import os
from datetime import datetime, timezone, timedelta
from urllib.request import urlopen, Request
from urllib.error import URLError, HTTPError

E6B_HEX = {
    "ae0410": "163918",
    "ae0411": "163919",
    "ae0412": "163920",
    "ae0413": "164386",
    "ae0414": "164387",
    "ae0415": "164388",
    "ae0416": "164404",
    "ae0417": "164405",
    "ae0418": "164406",
    "ae0419": "164407",
    "ae041a": "164408",
    "ae041b": "164409",
    "ae041c": "164410",
}

LATEST_OUTPUT_PATH = "data/e6b_latest.json"
HISTORY_OUTPUT_PATH = "data/e6b_history.json"
DATA_URL = "https://opendata.adsb.fi/api/v2/lat/39.5/lon/-98.35/dist/3000"
HISTORY_DAYS = 7


def fetch_json(url: str):
    req = Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 E6B-Tracker/1.0"
        }
    )
    with urlopen(req, timeout=60) as resp:
        return json.loads(resp.read().decode("utf-8"))


def infer_confidence(ac: dict) -> str:
    hex_code = (ac.get("hex") or "").lower()
    callsign = (ac.get("flight") or ac.get("r") or "").strip().upper()

    if hex_code in E6B_HEX:
        return "High"
    if callsign:
        return "Medium"
    return "Low"


def area_label(lat, lon):
    if lat is None or lon is None:
        return "Unknown"
    if 32 <= lat <= 42.5 and -125 <= lon <= -114:
        return "California"
    if 41.5 <= lat <= 46.5 and -125 <= lon <= -116:
        return "Oregon"
    return "Other"


def normalize_aircraft(ac: dict, now_utc: str):
    hex_code = (ac.get("hex") or "").lower()
    if hex_code not in E6B_HEX:
        return None

    lat = ac.get("lat")
    lon = ac.get("lon")
    alt_baro = ac.get("alt_baro")
    gs = ac.get("gs")

    if not isinstance(lat, (int, float)) or not isinstance(lon, (int, float)):
        return None

    return {
        "hex": hex_code.upper(),
        "tail_number": E6B_HEX.get(hex_code, ""),
        "callsign": (ac.get("flight") or ac.get("r") or "").strip(),
        "lat": lat,
        "lon": lon,
        "altitude_ft": alt_baro if isinstance(alt_baro, (int, float)) else None,
        "groundspeed_kt": gs if isinstance(gs, (int, float)) else None,
        "seen_utc": now_utc,
        "confidence": infer_confidence(ac),
        "area": area_label(lat, lon),
        "source": "adsb.fi public API"
    }


def load_existing_history():
    if not os.path.exists(HISTORY_OUTPUT_PATH):
        return {"generated_utc": None, "count": 0, "positions": []}

    try:
        with open(HISTORY_OUTPUT_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {"generated_utc": None, "count": 0, "positions": []}


def trim_history_points(points, cutoff_dt):
    kept = []
    for pt in points:
        seen = pt.get("seen_utc")
        if not seen:
            continue
        try:
            pt_dt = datetime.strptime(seen, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
        except ValueError:
            continue
        if pt_dt >= cutoff_dt:
            kept.append(pt)
    return kept


def update_history(existing_history, latest_positions, now_dt):
    cutoff_dt = now_dt - timedelta(days=HISTORY_DAYS)

    history_map = {}
    for entry in existing_history.get("positions", []):
        hex_code = entry.get("hex")
        if hex_code:
            history_map[hex_code] = entry

    for hex_code, tail in E6B_HEX.items():
        hex_up = hex_code.upper()
        if hex_up not in history_map:
            history_map[hex_up] = {
                "hex": hex_up,
                "tail_number": tail,
                "callsign": "",
                "confidence": "High",
                "source": "adsb.fi public API",
                "history": []
            }

    for position in latest_positions:
        hex_code = position["hex"]
        entry = history_map.get(hex_code, {
            "hex": hex_code,
            "tail_number": position.get("tail_number", ""),
            "callsign": position.get("callsign", ""),
            "confidence": position.get("confidence", "High"),
            "source": position.get("source", "adsb.fi public API"),
            "history": []
        })

        entry["tail_number"] = position.get("tail_number", entry.get("tail_number", ""))
        entry["callsign"] = position.get("callsign", entry.get("callsign", ""))
        entry["confidence"] = position.get("confidence", entry.get("confidence", "High"))
        entry["source"] = position.get("source", entry.get("source", "adsb.fi public API"))

        entry.setdefault("history", []).append({
            "lat": position["lat"],
            "lon": position["lon"],
            "seen_utc": position["seen_utc"],
            "altitude_ft": position.get("altitude_ft"),
            "groundspeed_kt": position.get("groundspeed_kt"),
            "area": position.get("area")
        })

        history_map[hex_code] = entry

    output_positions = []
    for entry in history_map.values():
        entry["history"] = trim_history_points(entry.get("history", []), cutoff_dt)
        if entry["history"]:
            latest_pt = entry["history"][-1]
            entry["lat"] = latest_pt.get("lat")
            entry["lon"] = latest_pt.get("lon")
            entry["seen_utc"] = latest_pt.get("seen_utc")
            entry["altitude_ft"] = latest_pt.get("altitude_ft")
            entry["groundspeed_kt"] = latest_pt.get("groundspeed_kt")
            entry["area"] = latest_pt.get("area")
        output_positions.append(entry)

    return {
        "generated_utc": now_dt.strftime("%Y-%m-%d %H:%M:%S"),
        "count": sum(1 for p in output_positions if p.get("history")),
        "positions": sorted(output_positions, key=lambda x: x.get("hex", ""))
    }


def main():
    os.makedirs("data", exist_ok=True)
    now_dt = datetime.now(timezone.utc)
    now_utc = now_dt.strftime("%Y-%m-%d %H:%M:%S")

    latest_output = {
        "generated_utc": now_utc,
        "count": 0,
        "positions": []
    }

    history_output = load_existing_history()

    try:
        payload = fetch_json(DATA_URL)
        aircraft = payload.get("ac", [])
        positions = []

        for ac in aircraft:
            norm = normalize_aircraft(ac, now_utc)
            if norm:
                positions.append(norm)

        latest_output["positions"] = positions
        latest_output["count"] = len(positions)
        history_output = update_history(history_output, positions, now_dt)

    except (URLError, HTTPError, TimeoutError, json.JSONDecodeError) as exc:
        latest_output["error"] = str(exc)
        history_output["error"] = str(exc)

    with open(LATEST_OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(latest_output, f, indent=2)

    with open(HISTORY_OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(history_output, f, indent=2)


if __name__ == "__main__":
    main()
