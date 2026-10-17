#!/usr/bin/env python3
"""READ-ONLY four-stage reconciliation of the CFB manifest-vs-history coverage gap.

Loads FOUR artifacts and walks every expected manifest decision through
  manifest -> raw -> normalized replay -> stored history -> graded results,
charging it to the FIRST failing stage. Identity uses the WAVE-LOCAL key
`app._cfb_wave_team_key` (cff._resolve(normalize_ncaaf_team_name(...))) so a re-run reconciles exactly
as the wave now does. The id-less manifest/history/results are bridged by that key + week; raw games are
indexed in BOTH orientations (home/away) so a road team's decision is never a false "absent from raw".

Reporting separates DISTINCT GAMES (by CFBD id) from TEAM-SIDE DECISIONS (two per game). Exits NONZERO
on: a missing/unreadable input, an ambiguous legacy join, a genuine absent-from-raw, or a team-key
collision. Read-only (one /lines GET + three local reads). Run on prod:
    sudo -u ubuntu bash -lc 'cd /opt/bankrollkings && set -a && . .env && set +a && venv/bin/python diagnose_cfb_line_coverage.py --completed-week 6'
    ... add --collision-audit to run ONLY the collision scan over the raw team universe.
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

import app
import bk_runtime
import cfb_current_form as cff
import fetch_cfbd_game_lines_history as histmod

K = app._cfb_wave_team_key
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


def _collision_audit(raw) -> int:
    names = set()
    for g in raw:
        for side in ("homeTeam", "awayTeam"):
            n = str(g.get(side) or "").strip()
            if n:
                names.add(n)
    coll = app._cfb_wave_key_collisions(names)
    print(f"collision audit: {len(names)} distinct raw CFBD team names -> {len(coll)} collisions")
    for key, merged in sorted(coll.items()):
        print(f"  [COLLISION] key {key!r} merges distinct teams: {merged}")
    if coll:
        print("[EXIT 2] team-key collisions present — the helper would merge distinct teams; FAIL CLOSED.")
        return 2
    print("[EXIT 0] no collisions; every distinct raw team name maps to a unique key.")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--season", type=int, default=2026)
    ap.add_argument("--completed-week", type=int, default=6)
    ap.add_argument("--collision-audit", action="store_true", help="Run only the raw-universe collision scan.")
    args = ap.parse_args()
    from services.env_loader import load_local_env
    load_local_env(BASE_DIR)
    season, cw = args.season, args.completed_week

    raw = _fetch_lines(season)
    if args.collision_audit:
        return _collision_audit(raw)

    print("=" * 74)
    print(f"CFB FOUR-STAGE LINE-COVERAGE RECONCILIATION — season {season}, thru wk {cw}")
    print("=" * 74)

    # 1. runtime manifest + provenance
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

    # 2. fresh raw CFBD /lines (id-bearing), indexed in BOTH orientations
    print(f"raw /lines games       : {len(raw)} (single unpaginated GET)")
    coll_rc = _collision_audit(raw)
    raw_by_canon = defaultdict(list)
    for g in raw:
        rh, ra = K(str(g.get("homeTeam") or "")), K(str(g.get("awayTeam") or ""))
        wk = g.get("week")
        if wk is None:
            continue
        raw_by_canon[(int(wk), rh, ra)].append(g)   # home-side decision
        raw_by_canon[(int(wk), ra, rh)].append(g)   # away-side decision (both orientations)

    # 3. stored history CSV
    if not HIST_CSV.exists():
        print(f"[FATAL] stored history CSV missing: {HIST_CSV}")
        return 2
    try:
        hdf = pd.read_csv(HIST_CSV, low_memory=False)
    except Exception as exc:
        print(f"[FATAL] cannot read history CSV ({type(exc).__name__}: {exc})")
        return 2
    hdf = hdf[pd.to_numeric(hdf.get("Season"), errors="coerce") == season]
    stored_hist = Counter()
    for _, r in hdf.iterrows():
        if pd.isna(pd.to_numeric(r.get("HomeSpread"), errors="coerce")):
            continue
        wk = pd.to_numeric(r.get("Week"), errors="coerce")
        if pd.notna(wk):
            stored_hist[(int(wk), K(str(r.get("Home", ""))), K(str(r.get("Away", ""))))] += 1

    # 4. graded results CSV
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
        wk = pd.to_numeric(r.get("Week"), errors="coerce")
        if pd.notna(wk):
            graded.add((int(wk), K(str(r.get("Team", ""))), K(str(r.get("Opponent", "")))))

    # normalized replay of the history fetcher on the SAME raw payload
    replay = set()
    rep_df = histmod.normalize_payload(raw, season)
    if not rep_df.empty:
        for _, r in rep_df.iterrows():
            if pd.isna(pd.to_numeric(r.get("HomeSpread"), errors="coerce")):
                continue
            wk = pd.to_numeric(r.get("Week"), errors="coerce")
            if pd.notna(wk):
                replay.add((int(wk), K(str(r.get("Home", ""))), K(str(r.get("Away", "")))))

    fbs = {K(t) for t in cff._fbs_teams()}
    if not fbs:
        print("[FATAL] _fbs_teams() empty — cannot classify the FBS-team universe.")
        return 2

    buckets, samples = Counter(), defaultdict(list)
    decisions = ambiguous = absent_raw = 0
    games_seen = set()
    for mg in manifest["games"]:
        wk = mg.get("week")
        if wk is None or int(wk) > cw or not mg.get("completed") or mg.get("spread_now") is None:
            continue
        rh, ra = K(str(mg.get("home") or "")), K(str(mg.get("away") or ""))
        for rteam, ropp in ((rh, ra), (ra, rh)):
            if rteam not in fbs:
                continue
            decisions += 1
            key = (int(wk), rteam, ropp)
            raw_hits = raw_by_canon.get(key, [])
            raw_ids = {g.get("id") for g in raw_hits}
            games_seen.update(raw_ids)
            if key in graded:
                reason = "graded_ok"
            elif len(raw_ids) > 1:
                reason = "ambiguous_legacy_join"
                ambiguous += 1
            elif not raw_hits:
                reason = "absent_from_current_raw"
                absent_raw += 1
            elif key not in replay:
                reason = "dropped_in_normalize"
            elif key not in stored_hist:
                reason = "in_replay_absent_from_stored_history"
            else:
                reason = "in_history_but_ungraded"
            buckets[reason] += 1
            if reason != "graded_ok":
                g0 = raw_hits[0] if raw_hits else {}
                samples[reason].append(
                    f"id={g0.get('id')} wk{wk} {mg.get('home')}/{mg.get('away')} side={rteam} "
                    f"replay={key in replay} stored={stored_hist.get(key, 0)}")

    print(f"stored history rows    : {len(hdf)} ({season})")
    print(f"graded decisions       : {len(rdf)} rows")
    print("-" * 74)
    print(f"expected team-side decisions : {decisions}  across {len(games_seen)} distinct game ids")
    print("RECONCILIATION BY STAGE/REASON (mutually exclusive):")
    for reason, n in buckets.most_common():
        print(f"  {n:4}  {reason}")
        for s in samples.get(reason, [])[:8]:
            print(f"          {s}")
    print("-" * 74)

    # cross-checks (directive point 4)
    wk0 = sum(1 for g in raw if g.get("week") == 0)
    starts = [d for d in (_start_date(g) for g in raw) if d]
    s0 = min(starts) if starts else None
    datewk = sum(1 for g in raw if _start_date(g) and g.get("week") is not None and s0
                 and abs(((_start_date(g) - s0).days // 7 + 1) - int(g.get("week"))) > 1)
    print(f"week-0 games in raw          : {wk0}")
    print(f"date-vs-numbered-week drift  : {datewk}")
    print(f"pagination/truncation        : single unpaginated GET; {len(raw)} games")
    print("-" * 74)

    rc = 0
    if coll_rc:
        print("[EXIT] team-key collisions present (see collision audit above).")
        rc = 2
    if absent_raw:
        print(f"[EXIT] {absent_raw} genuine absent_from_current_raw decision(s) — not a clean reconciliation.")
        rc = max(rc, 1)
    if ambiguous:
        print(f"[EXIT] {ambiguous} ambiguous legacy join(s) — id-less bridge unreliable for those.")
        rc = max(rc, 1)
    if rc == 0:
        print("[EXIT 0] clean: no collisions, no absent-from-raw, no ambiguous joins.")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
