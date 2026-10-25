#!/usr/bin/env python3
"""Append a daily snapshot of NFL player-prop lines to a persistent archive, so we build
a real 2026 line history (open -> close) to grade "tickets we could have hit" against over
time. The Odds API only serves CURRENT lines, so if we don't capture them daily they're
gone. Idempotent: one row per (SnapshotDate, Player, Stat) -- re-running the same day
updates that day's snapshot rather than duplicating it.

data/tracking/ is gitignored, so PROD accumulates its own running record (like the game
line-open ledger). Wire into run_daily.py so it runs every day in season.
"""
from __future__ import annotations

import hashlib
import os
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from app import load_nfl_schedule

BASE_DIR = Path(__file__).resolve().parent
PROPS_PATH = BASE_DIR / "data" / "props" / "NFL_Props.csv"
OUT_PATH = BASE_DIR / "data" / "tracking" / "NFL_PropLines_Archive.csv"

# Only the stats we actually model / grade (skip Anytime TD, tackles-for-props we don't line-grade)
KEEP_STATS = {"Pass Yds", "Pass Completions", "Pass TDs", "Rush Yds", "Rush Att",
              "Rec Yds", "Receptions", "Solo Tackles", "Tackles + Assists", "Sacks"}

# Precision-capture schema (2026-10-24). v1 = the legacy date-only rows (no clocks / no observation id);
# they remain UNCHANGED and are classified TEMPORAL_PRECISION_INSUFFICIENT. v2 rows carry the three clocks
# + provider identity so a downstream board can PROVE pregame ordering.
SCHEMA_V1 = "nfl_proplines_v1"
SCHEMA_V2 = "nfl_proplines_v2"
# backward-compatible columns the grader (grade_nfl_prop_lines) already reads, kept first + unchanged
_V1_COLS = ["SnapshotDate", "Season", "Player", "Team", "Stat", "Line", "OverOdds",
            "UnderOdds", "BookCount", "Game", "GameDate"]
_V2_COLS = ["EventId", "EventCommenceAtUTC", "SourceUpdatedEarliestUTC", "SourceUpdatedLatestUTC",
            "QuoteScope", "BKCapturedAtUTC", "TemporalEligibility", "SchemaVersion", "ObservationId"]
ALL_COLS = _V1_COLS + _V2_COLS


def _nonempty(series) -> list[str]:
    # dtype-robust: never .map(str.strip) (unbound method crashes on a float/NA under Arrow-backed string
    # columns in the prod pandas). Skip NA FIRST via pd.isna -- a pyarrow NA stringifies to '<NA>', so
    # stringifying before the NA check would leak garbage. Then drop blanks and nan/none/null sentinels.
    out = []
    for v in series.tolist():
        try:
            if v is None or pd.isna(v):
                continue
        except (TypeError, ValueError):
            pass
        s = str(v).strip()
        if s and s.lower() not in ("nan", "none", "null", "<na>"):
            out.append(s)
    return out


def _observation_id(parts: list) -> str:
    """Deterministic id from IMMUTABLE quote facts only -- never BKCapturedAtUTC (which changes every run
    and would make an identical rerun look new). Identical source observation -> identical id -> idempotent.
    A rescheduled kickoff is included in the basis, so it yields a DISTINCT observation (correction history
    preserved) rather than silently overwriting the prior kickoff."""
    basis = "|".join("" if p is None else str(p) for p in parts)
    return hashlib.sha256(basis.encode("utf-8")).hexdigest()[:24]


_UTC_Z = __import__("re").compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")


def _valid_utc(s: str) -> bool:
    """A provable UTC instant must be canonical 'YYYY-MM-DDTHH:MM:SSZ'. Anything else is NOT trusted for
    temporal ordering (fail closed to unknown) -- never assume a bare/odd string is UTC."""
    return bool(_UTC_Z.match(str(s or "")))


def _eastern_today() -> str:
    try:
        from services.timeutils import to_eastern_date_str  # noqa
        return to_eastern_date_str(datetime.utcnow().isoformat() + "Z")
    except Exception:
        return datetime.now().strftime("%Y-%m-%d")


def _game_dates() -> dict:
    """Map 'AwayFull@HomeFull' -> game Date from the schedule, so each captured line
    carries the game date (for grading and open->close week bucketing)."""
    out = {}
    try:
        sch = load_nfl_schedule()
        for _, r in sch.iterrows():
            a = str(r.get("AwayFull") or r.get("Away") or "").strip()
            h = str(r.get("HomeFull") or r.get("Home") or "").strip()
            if a and h:
                out[f"{a}@{h}"] = str(r.get("Date") or "")
    except Exception:
        pass
    return out


def main() -> int:
    if not PROPS_PATH.exists():
        print("[capture_nfl_prop_lines] no props feed; nothing to capture")
        return 0
    try:
        df = pd.read_csv(PROPS_PATH)
    except Exception as exc:
        print(f"[capture_nfl_prop_lines] could not read props: {exc}")
        return 1
    if df.empty or not {"Player", "Stat", "Line"}.issubset(df.columns):
        print("[capture_nfl_prop_lines] props feed empty / missing columns")
        return 0
    df = df[df["Stat"].isin(KEEP_STATS)].copy()
    df["Line"] = pd.to_numeric(df["Line"], errors="coerce")
    for c in ("OverOdds", "UnderOdds"):
        df[c] = pd.to_numeric(df.get(c), errors="coerce")
    df = df.dropna(subset=["Line"])
    if df.empty:
        print("[capture_nfl_prop_lines] no gradeable prop rows")
        return 0

    snap = _eastern_today()
    gdates = _game_dates()
    captured_utc = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    have_clocks = {"EventId", "EventCommenceAtUTC", "SourceUpdatedAtUTC"}.issubset(df.columns)
    rows = []
    skipped_no_identity = 0
    for (player, stat), g in df.groupby(["Player", "Stat"]):
        # the MAIN line = most common across books; consensus odds AT that line
        main_line = g["Line"].mode()
        main_line = float(main_line.iloc[0]) if len(main_line) else float(g["Line"].median())
        at = g[g["Line"] == main_line]
        over = at["OverOdds"][at["OverOdds"].abs() >= 100]
        under = at["UnderOdds"][at["UnderOdds"].abs() >= 100]
        _game_raw = g["Game"].iloc[0] if "Game" in g.columns else ""
        game = "" if pd.isna(_game_raw) else str(_game_raw).strip()
        if game.lower() in ("nan", "none", "null"):
            game = ""
        over_val = int(round(over.median())) if len(over) else ""
        under_val = int(round(under.median())) if len(under) else ""

        # provider identity + the three clocks (additive; empty when the feed predates Commit 1)
        eid = (_nonempty(g["EventId"])[0] if have_clocks and len(_nonempty(g["EventId"])) else "")
        commence = (_nonempty(g["EventCommenceAtUTC"])[0] if have_clocks and len(_nonempty(g["EventCommenceAtUTC"])) else "")
        src = _nonempty(g["SourceUpdatedAtUTC"]) if have_clocks else []
        src_earliest, src_latest = (min(src), max(src)) if src else ("", "")
        # temporal eligibility from precise UTC clocks (string compare of canonical 'Z' ISO is valid).
        # A malformed/odd kickoff is NOT trusted -> UNKNOWN (fail closed), never assumed pregame.
        if not _valid_utc(commence):
            temporal = "UNKNOWN_NO_KICKOFF"
        elif captured_utc < commence:
            temporal = "PROVABLY_PREGAME"
        else:
            temporal = "POST_START"
        # deterministic observation identity from immutable quote facts (NOT the capture clock); a changed
        # kickoff -> distinct observation. Fail closed if there is not even a game/event to anchor identity.
        if not (eid or game):
            skipped_no_identity += 1
            continue
        obs_id = _observation_id(["oddsapi", eid, game, str(player), str(stat),
                                  main_line, over_val, under_val, "CONSENSUS", src_latest, commence])
        rows.append({
            "SnapshotDate": snap,
            "Season": 2026,
            "Player": str(player),
            "Team": str(g["Team"].iloc[0]) if "Team" in g.columns and pd.notna(g["Team"].iloc[0]) else "",
            "Stat": str(stat),
            "Line": main_line,
            "OverOdds": over_val,
            "UnderOdds": under_val,
            "BookCount": int(g["Book"].nunique()) if "Book" in g.columns else int(len(g)),
            "Game": game,
            "GameDate": gdates.get(game, ""),
            "EventId": eid,
            "EventCommenceAtUTC": commence,
            "SourceUpdatedEarliestUTC": src_earliest,
            "SourceUpdatedLatestUTC": src_latest,
            "QuoteScope": "CONSENSUS",
            "BKCapturedAtUTC": captured_utc,
            "TemporalEligibility": temporal,
            "SchemaVersion": SCHEMA_V2,
            "ObservationId": obs_id,
        })
    fresh = pd.DataFrame(rows, columns=ALL_COLS)

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    if OUT_PATH.exists():
        try:
            prior = pd.read_csv(OUT_PATH, low_memory=False)
        except Exception:
            prior = pd.DataFrame(columns=ALL_COLS)
        # Legacy (date-only) rows remain UNCHANGED; just classify them. Never rewrite their data or infer
        # timestamps for them.
        if "SchemaVersion" not in prior.columns:
            prior["SchemaVersion"] = SCHEMA_V1
        else:
            prior["SchemaVersion"] = prior["SchemaVersion"].fillna("").replace("", SCHEMA_V1)
        if "TemporalEligibility" not in prior.columns:
            prior["TemporalEligibility"] = "TEMPORAL_PRECISION_INSUFFICIENT"
        else:
            prior["TemporalEligibility"] = prior["TemporalEligibility"].fillna("").replace("", "TEMPORAL_PRECISION_INSUFFICIENT")
        if "ObservationId" not in prior.columns:
            prior["ObservationId"] = ""
        for c in ALL_COLS:
            if c not in prior.columns:
                prior[c] = ""
        combined = pd.concat([prior[ALL_COLS], fresh], ignore_index=True)
        # Idempotent upsert: among rows that HAVE an observation id (v2), keep the latest per id; legacy
        # rows (empty id) are preserved verbatim and never deduped against v2.
        oid = combined["ObservationId"].astype(str).str.strip()
        ided = combined[oid != ""].drop_duplicates(subset="ObservationId", keep="last")
        legacy = combined[oid == ""]
        combined = pd.concat([legacy, ided], ignore_index=True)
    else:
        combined = fresh

    # Atomic publication: a crash mid-write can never corrupt the running archive.
    tmp = OUT_PATH.with_name(OUT_PATH.name + ".tmp")
    combined[ALL_COLS].to_csv(tmp, index=False)
    os.replace(tmp, OUT_PATH)
    pregame = int((fresh["TemporalEligibility"] == "PROVABLY_PREGAME").sum()) if not fresh.empty else 0
    print(f"[capture_nfl_prop_lines] snapshot {snap} @ {captured_utc}: {len(fresh)} v2 lines "
          f"({pregame} provably-pregame; skipped {skipped_no_identity} with no identity) -> "
          f"{OUT_PATH.name} ({len(combined)} total rows)")
    if not have_clocks:
        print("[capture_nfl_prop_lines] NOTE: props feed lacks EventId/commence/source clocks "
              "(fetcher Commit 1 not yet applied to this feed); v2 rows recorded with UNKNOWN_NO_KICKOFF.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
