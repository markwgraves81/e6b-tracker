#!/usr/bin/env python3
import json
import os
from datetime import datetime, timezone
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

OUTPUT_PATH = "data/e6b_latest.json"
DATA_URL = "https://opendata.adsb.fi/api/v2/lat/39.5/lon/-98.35/dist/3000"


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


def normalize_aircraft(ac: dict):
    hex_code = (ac.get("hex") or "").lower()
    if hex_code not in E6B_HEX:
        return None

    lat = ac.get("lat")
    lon = ac.get("lon")
    alt_baro = ac.get("alt_baro")
    gs = ac.get("gs")

    return {
        "hex": hex_code.upper(),
        "tail_number": E6B_HEX.get(hex_code, ""),
        "callsign": (ac.get("flight") or ac.get("r") or "").strip(),
        "lat": lat,
        "lon": lon,
        "altitude_ft": alt_baro if isinstance(alt_baro, (int, float)) else None,
        "groundspeed_kt": gs if isinstance(gs, (int, float)) else None,
        "seen_utc": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
        "confidence": infer_confidence(ac),
        "area": area_label(lat, lon),
        "source": "adsb.fi public API",
        "history": []
    }


def main():
    os.makedirs("data", exist_ok=True)

    output = {
        "generated_utc": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
        "count": 0,
        "positions": []
    }

    try:
        payload = fetch_json(DATA_URL)
        aircraft = payload.get("ac", [])
        positions = []

        for ac in aircraft:
            norm = normalize_aircraft(ac)
            if norm:
                positions.append(norm)

        output["positions"] = positions
        output["count"] = len(positions)

    except (URLError, HTTPError, TimeoutError, json.JSONDecodeError) as exc:
        output["error"] = str(exc)

    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2)


if __name__ == "__main__":
    main()
