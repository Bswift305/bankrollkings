"""Portrait library helpers for Franchise Kings.

The library is intentionally name-agnostic: players store only a portrait_id, and
metadata decides which images fit a generated profile.
"""
from __future__ import annotations

import csv
import json
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
ASSETS_DIR = BASE_DIR / "assets"
METADATA_DIR = ASSETS_DIR / "metadata"
PLAYERS_DIR = ASSETS_DIR / "portraits" / "players"
CSV_PATH = METADATA_DIR / "portraits.csv"
JSON_PATH = METADATA_DIR / "portraits.json"

FIELDNAMES = [
    "portrait_id", "file_path", "category", "age_range", "skin_tone",
    "ethnicity_group", "hair_style", "facial_hair", "accessories",
    "expression", "body_type", "position_bias", "used",
]


def age_range_for(age):
    try:
        age = int(age)
    except (TypeError, ValueError):
        return "prime"
    if age <= 25:
        return "young"
    if age <= 31:
        return "prime"
    return "veteran"


def body_type_for(pos):
    if pos in ("OL", "DL"):
        return "large"
    if pos in ("WR", "CB", "RB", "S", "LB"):
        return "athletic"
    if pos in ("QB", "TE"):
        return "balanced"
    return "average"


def portrait_url(portrait_id, records=None):
    if not portrait_id:
        return ""
    for rec in records or load_records():
        if rec.get("portrait_id") == portrait_id:
            path = rec.get("file_path") or ""
            return path if path.startswith("/") else "/" + path.replace("\\", "/")
    return f"/assets/portraits/players/active/{portrait_id}.png"


def load_records():
    if JSON_PATH.exists():
        try:
            data = json.loads(JSON_PATH.read_text(encoding="utf-8"))
            if isinstance(data, list):
                return [_normalize_record(x) for x in data if isinstance(x, dict)]
        except (OSError, json.JSONDecodeError):
            pass
    if not CSV_PATH.exists():
        return []
    with CSV_PATH.open("r", encoding="utf-8", newline="") as f:
        return [_normalize_record(row) for row in csv.DictReader(f)]


def write_records(records):
    METADATA_DIR.mkdir(parents=True, exist_ok=True)
    clean = [_normalize_record(r) for r in records]
    with CSV_PATH.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        writer.writeheader()
        for rec in clean:
            writer.writerow({k: rec.get(k, "") for k in FIELDNAMES})
    JSON_PATH.write_text(json.dumps(clean, indent=2), encoding="utf-8")
    return clean


def append_records(records):
    existing = {r["portrait_id"]: r for r in load_records() if r.get("portrait_id")}
    for rec in records:
        rec = _normalize_record(rec)
        if rec.get("portrait_id"):
            existing[rec["portrait_id"]] = rec
    return write_records(sorted(existing.values(), key=lambda r: r["portrait_id"]))


def select_portrait(player, used_ids=None, records=None):
    records = records if records is not None else load_records()
    if not records:
        return ""
    used_ids = set(used_ids or ())
    pos = player.get("pos") or player.get("position") or ""
    wanted_age = age_range_for(player.get("age"))
    wanted_body = body_type_for(pos)

    def split_bias(rec):
        return [x.strip() for x in str(rec.get("position_bias") or "").split("|") if x.strip()]

    def score(rec):
        if rec.get("category") not in ("", "player"):
            return -100
        s = 0
        if rec.get("portrait_id") in used_ids:
            s -= 80
        if rec.get("age_range") == wanted_age:
            s += 35
        elif rec.get("age_range") in ("", "any"):
            s += 8
        if rec.get("body_type") == wanted_body:
            s += 25
        elif rec.get("body_type") in ("", "any"):
            s += 6
        bias = split_bias(rec)
        if pos and pos in bias:
            s += 30
        elif not bias:
            s += 4
        if str(rec.get("used", "")).lower() == "false":
            s += 2
        return s

    ranked = sorted(records, key=lambda r: (score(r), _stable_tiebreak(player, r)), reverse=True)
    return ranked[0].get("portrait_id", "") if ranked else ""


def assign_player(player, used_ids=None, records=None):
    if player.get("portrait_id"):
        return player["portrait_id"]
    pid = select_portrait(player, used_ids=used_ids, records=records)
    if pid:
        player["portrait_id"] = pid
    return pid


def _stable_tiebreak(player, rec):
    token = f"{player.get('id', '')}:{player.get('name', '')}:{rec.get('portrait_id', '')}"
    return sum((i + 1) * ord(ch) for i, ch in enumerate(token)) % 100000


def _normalize_record(rec):
    out = {k: str(rec.get(k, "") if rec.get(k, "") is not None else "").strip() for k in FIELDNAMES}
    if not out["portrait_id"] and out["file_path"]:
        out["portrait_id"] = Path(out["file_path"]).stem
    if out["file_path"] and not out["file_path"].startswith("/"):
        out["file_path"] = "/" + out["file_path"].replace("\\", "/").lstrip("/")
    if not out["used"]:
        out["used"] = "false"
    return out
