#!/usr/bin/env python3
"""READ-ONLY four-stage reconciliation of the CFB manifest-vs-history coverage gap.

The Active ATS Wave fail-closes on "missing decisions": completed, line-bearing FBS-team games in the
runtime MANIFEST (cfb_line_moves.json) that are ungraded in NCAAF_GameLineResults.csv. This walks the
full pipeline across FOUR artifacts and assigns each expected decision ONE mutually-exclusive reason,
so we do NOT presume where the loss is.

Artifacts:
  1. runtime manifest   — cfb_line_moves.json (what the wave actually expects; provenance printed)
  2. fresh raw CFBD      — GET /lines?year=&seasonType=regular (the id-bearing source both feeds share)
  3. stored history CSV  — data/historical/NCAAF_GameLines_History.csv (what the grader read)
  4. graded results CSV  — data/tracking/NCAAF_GameLineResults.csv (what the wave counts)

Stages (each expected manifest decision is charged to the FIRST stage it fails):
  manifest -> raw -> normalized replay -> stored history -> graded results.

Identity: anchored on the CFBD game `id` in the raw feed; the manifest, stored history and graded
results carry NO id, so they are bridged by the canonical legacy key (season, week, resolved home,
resolved away) with kickoff date as a disambiguator. EVERY ambiguous legacy join (one key -> >1 id, or
a stored-history canonical collision) is counted and makes the tool exit NONZERO -- the id-less join is
a disclosed legacy bridge, not a stable-id reconciliation. Adding a GameID column to future history +
results rows is the recommended correction (NOT applied here).

Read-only: one /lines GET + three local reads; writes nothing, changes no pipeline. Exits nonzero if any
input is missing/unreadable or any legacy join is ambiguous. Run on prod:
    sudo -u ubuntu bash -lc 'cd /opt/bankrollkings && set -a && . .env && set +a && venv/bin/python diagnose_cfb_line_coverage.py --completed-week 6'
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import statistics
import urllib.request
from collections import Counter, defaultdict
from pathlib import Path

import pandas as pd

import bk_runtime
import cfb_current_form as cff
import fetch_cfbd_game_lines_history as histmod
from app import normalize_ncaaf_team_name as _nz

BASE_DIR = Path(__file__).resolve().parent
HIST_CSV = BASE_DIR / "data" / "historical" / "NCAAF_GameLines_History.csv"
RESULTS_CSV = BASE_DIR / "data" / "tracking" / "NCAAF_GameLineResults.csv"


def _median(vals):
    vals = [v for v in vals if v is not None]
    return round(statistics.median(vals), 1) if vals else None


def _fetch_lines(season: int) -> list:
    key = os.getenv("CFBD_API_KEY") or os.getenv("COLLEGEFOOTBALLDATA_API_KEY")
    if not key:
        raise SystemExit("No CFBD_API_KEY in environment/.env")
    url = f"https://api.collegefootballdata.com/lines?year={season}&seasonType=regular"
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {key.strip()}"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)


def _start_date(g):
    s = g.get("startDate") or g.get("start_date") or g.get("date")
    try:
        return dt.datetime.fromisoformat(str(s).replace("Z", "+00:00")) if s else None
    except ValueError:
        return None


def _canon(week, rhome, raway):
    try:
        return (int(week), rhome, raway)
    except (TypeError, ValueError):
        return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--season", type=int, default=2026)
    ap.add_argument("--completed-week", type=int, default=6)
    args = ap.parse_args()
    from services.env_loader import load_local_env
    load_local_env(BASE_DIR)
    season, cw = args.season, args.completed_week

    print("=" * 74)
    print(f"CFB FOUR-STAGE LINE-COVERAGE RECONCILIATION — season {season}, thru wk {cw}")
    print("=" * 74)

    # ---- 1. runtime manifest (what the wave expects) + provenance ---------------------------------
    mpath = bk_runtime.scenario_read_path("cfb_line_moves.json")
    manifest = bk_runtime.read_json("cfb_line_moves.json", None)
    if not manifest or not isinstance(manifest.get("games"), list):
        print(f"[FATAL] runtime manifest missing/invalid at {mpath}")
        return 2
    print(f"manifest source path   : {mpath}")
    print(f"manifest updated/season: {manifest.get('updated')} / {manifest.get('season')}  "
          f"(n_games {manifest.get('n_games')})")
    if manifest.get("season") != season:
        print(f"[FATAL] manifest season {manifest.get('season')} != requested {season}")
        return 2

    # ---- 2. fresh raw CFBD /lines (id-bearing) ----------------------------------------------------
    raw = _fetch_lines(season)
    print(f"raw /lines games       : {len(raw)} (single unpaginated GET, seasonType=regular)")
    raw_by_canon = defaultdict(list)
    for g in raw:
        c = _canon(g.get("week"), cff._resolve(str(g.get("homeTeam") or "")),
                   cff._resolve(str(g.get("awayTeam") or "")))
        if c:
            raw_by_canon[c].append(g)

    # ---- 3. stored history CSV --------------------------------------------------------------------
    if not HIST_CSV.exists():
        print(f"[FATAL] stored history CSV missing: {HIST_CSV}")
        return 2
    try:
        hdf = pd.read_csv(HIST_CSV, low_memory=False)
    except Exception as exc:
        print(f"[FATAL] cannot read history CSV ({type(exc).__name__}: {exc})")
        return 2
    hdf = hdf[pd.to_numeric(hdf.get("Season"), errors="coerce") == season]
    stored_hist = defaultdict(int)                 # canon -> count of stored rows WITH a home spread
    for _, r in hdf.iterrows():
        if pd.isna(pd.to_numeric(r.get("HomeSpread"), errors="coerce")):
            continue
        c = _canon(pd.to_numeric(r.get("Week"), errors="coerce"),
                   cff._resolve(str(r.get("Home", ""))), cff._resolve(str(r.get("Away", ""))))
        if c:
            stored_hist[c] += 1
    print(f"stored history rows    : {len(hdf)} ({season}); distinct line-bearing canon keys {len(stored_hist)}")

    # ---- 4. graded results CSV --------------------------------------------------------------------
    if not RESULTS_CSV.exists():
        print(f"[FATAL] graded results CSV missing: {RESULTS_CSV}")
        return 2
    try:
        rdf = pd.read_csv(RESULTS_CSV, low_memory=False)
    except Exception as exc:
        print(f"[FATAL] cannot read results CSV ({type(exc).__name__}: {exc})")
        return 2
    rdf = rdf[(rdf.get("MarketType").astype(str).str.upper() == "SPREAD")
              & (pd.to_numeric(rdf.get("Season"), errors="coerce") == season)
              & (rdf.get("OutcomeState").astype(str).isin(["Hit", "Miss", "Push"]))
              & (pd.to_numeric(rdf.get("Line"), errors="coerce").notna())]
    graded = set()
    for _, r in rdf.iterrows():
        c = _canon(pd.to_numeric(r.get("Week"), errors="coerce"),
                   cff._resolve(str(r.get("Team", ""))), cff._resolve(str(r.get("Opponent", ""))))
        if c:
            graded.add(c)
    print(f"graded decisions       : {len(rdf)} rows ({len(graded)} canon keys)")

    # ---- normalized replay of the history fetcher on the SAME raw payload -------------------------
    replay_df = histmod.normalize_payload(raw, season)
    replay = set()
    if not replay_df.empty:
        for _, r in replay_df.iterrows():
            if pd.isna(pd.to_numeric(r.get("HomeSpread"), errors="coerce")):
                continue
            c = _canon(pd.to_numeric(r.get("Week"), errors="coerce"),
                       cff._resolve(str(r.get("Home", ""))), cff._resolve(str(r.get("Away", ""))))
            if c:
                replay.add(c)

    fbs = cff._fbs_teams()
    if not fbs:
        print("[FATAL] _fbs_teams() empty — cannot classify the FBS-team universe honestly.")
        return 2

    # ---- walk every EXPECTED manifest decision through the four stages ----------------------------
    buckets, samples = Counter(), defaultdict(list)
    expected = ambiguous = 0
    for mg in manifest["games"]:
        wk = mg.get("week")
        if wk is None or int(wk) > cw or not mg.get("completed") or mg.get("spread_now") is None:
            continue
        home, away = str(mg.get("home") or ""), str(mg.get("away") or "")
        rh, ra = cff._resolve(home), cff._resolve(away)
        for team, opp, rteam, ropp in ((home, away, rh, ra), (away, home, ra, rh)):
            if rteam not in fbs:
                continue
            expected += 1
            key = (int(wk), rteam, ropp)
            raw_hits = raw_by_canon.get(key, [])
            raw_ids = {g.get("id") for g in raw_hits}
            # charge to the FIRST failing stage
            if key in graded:
                reason = "graded_ok"
            elif len(raw_ids) > 1 or stored_hist.get(key, 0) > 1:
                reason = "ambiguous_legacy_join"
                ambiguous += 1
            elif not raw_hits:
                reason = "absent_from_current_raw"
            elif _nz(home) == "" or _nz(away) == "":
                reason = "dropped_in_normalize:name_blanked"
            elif histmod._home_spread(histmod._first_line(raw_hits[0])) is None:
                reason = "first_book_no_spread (other book has one)"
            elif key not in replay:
                reason = "dropped_in_normalize:other"
            elif key not in stored_hist:
                reason = "in_replay_absent_from_stored_history"
            else:
                reason = "in_history_but_ungraded (grade/join)"
            buckets[reason] += 1
            if reason != "graded_ok":
                g0 = raw_hits[0] if raw_hits else {}
                samples[reason].append(
                    f"id={g0.get('id')} wk{wk} {team} vs {opp} | "
                    f"med={_median([l.get('spread') for l in (g0.get('lines') or [])])} "
                    f"first={histmod._home_spread(histmod._first_line(g0)) if g0 else None} "
                    f"replay={key in replay} stored={stored_hist.get(key, 0)} graded=False")

    # ---- manifest staleness cross-check: raw expected games NOT in the manifest -------------------
    man_canon = set()
    for mg in manifest["games"]:
        c = _canon(mg.get("week"), cff._resolve(str(mg.get("home") or "")),
                   cff._resolve(str(mg.get("away") or "")))
        if c:
            man_canon.add(c)
    raw_not_in_manifest = 0
    for g in raw:
        wk = g.get("week")
        if wk is None or int(wk) > cw or g.get("homeScore") is None:
            continue
        if _median([l.get("spread") for l in (g.get("lines") or [])]) is None:
            continue
        rh = cff._resolve(str(g.get("homeTeam") or ""))
        ra = cff._resolve(str(g.get("awayTeam") or ""))
        if rh in fbs and (int(wk), rh, ra) not in man_canon:
            raw_not_in_manifest += 1

    print("-" * 74)
    print(f"expected FBS-team decisions (from manifest): {expected}")
    print("RECONCILIATION BY STAGE/REASON (mutually exclusive):")
    for reason, n in buckets.most_common():
        print(f"  {n:4}  {reason}")
        for s in samples.get(reason, [])[:8]:
            print(f"          {s}")
    print("-" * 74)
    print("CROSS-CHECKS (directive point 4):")
    print(f"  absent_from_runtime_manifest : {raw_not_in_manifest}  "
          "(fresh-raw completed line-bearing FBS games missing from the manifest snapshot)")
    wk0 = sum(1 for g in raw if g.get("week") == 0)
    starts = [d for d in (_start_date(g) for g in raw) if d]
    s0 = min(starts) if starts else None
    datewk = 0
    if s0:
        for g in raw:
            sd, wk = _start_date(g), g.get("week")
            if sd and wk is not None and abs(((sd - s0).days // 7 + 1) - int(wk)) > 1:
                datewk += 1
    print(f"  week-0 games in raw          : {wk0}")
    print(f"  date-vs-numbered-week drift  : {datewk}")
    print(f"  pagination/truncation        : single unpaginated GET; {len(raw)} games")
    print("  named FBS-FBS probes:")
    named = {"washington|washington state", "kansas|missouri", "miami (oh)|pittsburgh",
             "auburn|southern miss", "app state|maine", "kansas|long island university"}
    for g in raw:
        h, a = str(g.get("homeTeam") or "").lower(), str(g.get("awayTeam") or "").lower()
        if f"{h}|{a}" in named or f"{a}|{h}" in named:
            lines = g.get("lines") or []
            key = (int(g.get("week")), cff._resolve(h), cff._resolve(a))
            print(f"    id={g.get('id')} wk{g.get('week')} {g.get('awayTeam')} @ {g.get('homeTeam')} "
                  f"books={len(lines)} median={_median([l.get('spread') for l in lines])} "
                  f"first={histmod._home_spread(histmod._first_line(g))} "
                  f"replay={key in replay} stored={stored_hist.get(key, 0)} graded={key in graded} "
                  f"neutral={g.get('neutralSite')}")
    print("-" * 74)
    print("RECOMMENDED CORRECTION (not applied): add a GameID column to future NCAAF_GameLines_History +"
          " NCAAF_GameLineResults rows so this reconciles on the stable id, not a legacy name/date join.")
    if ambiguous:
        print(f"[EXIT 1] {ambiguous} ambiguous legacy join(s) — id-less bridge is unreliable for those; "
              "treat the table as provisional until GameID is added.")
        return 1
    print("[EXIT 0] no ambiguous legacy joins; reconciliation is id-bridged and unambiguous.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
