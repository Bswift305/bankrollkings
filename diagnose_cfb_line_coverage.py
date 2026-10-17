#!/usr/bin/env python3
"""READ-ONLY CFB ATS wave reconciliation on the authoritative (GameID, TeamSide) identity.

Runs the REAL wave path -- app._cfb_active_cover_streaks (graded NCAAF_GameLineResults.csv) +
app._cfb_ats_sync against the runtime manifest (cfb_line_moves.json) -- so it reports exactly what the
board sees. Each missing decision is the stable (GameID, TeamSide); it is detailed from the fresh CFBD
/lines response (week, teams, conferences, scores) to show WHY it is ungraded. Also runs the
non-authoritative name-overlay collision audit (the overlay must never change membership). Writes
nothing, changes no pipeline. Exits nonzero on missing/conflicts/ineligible/collisions or missing inputs.

    sudo -u ubuntu bash -lc 'cd /opt/bankrollkings && set -a && . .env && set +a && venv/bin/python diagnose_cfb_line_coverage.py --completed-week 6'
    ... --collision-audit runs ONLY the overlay collision scan over the raw team universe.
"""
from __future__ import annotations

import argparse
import json
import os
import urllib.request
from pathlib import Path

import app
import bk_runtime

BASE_DIR = Path(__file__).resolve().parent


def _fetch_lines(season: int) -> list:
    key = os.getenv("CFBD_API_KEY") or os.getenv("COLLEGEFOOTBALLDATA_API_KEY")
    if not key:
        raise SystemExit("No CFBD_API_KEY in environment/.env")
    url = f"https://api.collegefootballdata.com/lines?year={season}&seasonType=regular"
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {key.strip()}"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)


def _collision_audit(raw) -> int:
    names = {str(g.get(s) or "").strip() for g in raw for s in ("homeTeam", "awayTeam") if g.get(s)}
    coll = app._cfb_wave_key_collisions(names)
    print(f"overlay collision audit: {len(names)} distinct raw names -> {len(coll)} collisions "
          "(non-authoritative; must not change membership)")
    for key, merged in sorted(coll.items()):
        print(f"  [COLLISION] overlay key {key!r} merges: {merged}")
    return 2 if coll else 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--season", type=int, default=2026)
    ap.add_argument("--completed-week", type=int, default=6)
    ap.add_argument("--collision-audit", action="store_true")
    args = ap.parse_args()
    from services.env_loader import load_local_env
    load_local_env(BASE_DIR)
    season = args.season

    raw = _fetch_lines(season)
    if args.collision_audit:
        rc = _collision_audit(raw)
        print("[EXIT %d]" % rc)
        return rc
    by_id = {str(g.get("id")): g for g in raw}

    print("=" * 74)
    print(f"CFB ATS WAVE RECONCILIATION (GameID, TeamSide) — season {season}")
    print("=" * 74)
    mpath = bk_runtime.scenario_read_path("cfb_line_moves.json")
    manifest = bk_runtime.read_json("cfb_line_moves.json", None)
    if not manifest or not isinstance(manifest.get("games"), list):
        print(f"[FATAL] runtime manifest missing/invalid at {mpath}")
        return 2
    print(f"manifest source/updated : {mpath}")
    print(f"manifest updated/season : {manifest.get('updated')} / {manifest.get('season')} "
          f"(n_games {manifest.get('n_games')})")
    moves = [g for g in manifest["games"] if not g.get("completed") and g.get("spread_now") is not None]
    wk = min((g["week"] for g in moves), default=None)
    completed_week = (wk - 1) if wk else args.completed_week

    streak_data = app._cfb_active_cover_streaks(season)
    sync = app._cfb_ats_sync(streak_data, manifest, completed_week, season)

    print(f"raw /lines games        : {len(raw)}")
    for k in ("completed_week", "expected_decisions", "graded_decisions", "exclusions",
              "duplicates_collapsed", "conflicts", "ineligible", "manifest_missing_gameid",
              "missing_count", "synchronized", "reason"):
        if k in sync:
            print(f"  {k:24}: {sync[k]}")

    miss = sync.get("missing") or []
    if miss:
        print("-" * 74)
        print("MISSING (GameID, TeamSide) — detailed from raw /lines:")
        for gid, side in miss[:30]:
            g = by_id.get(str(gid))
            if g:
                print(f"  id={gid} {side:4} wk{g.get('week')} {g.get('awayTeam')} @ {g.get('homeTeam')} "
                      f"conf=({g.get('homeConference')}/{g.get('awayConference')}) "
                      f"score=({g.get('homeScore')}-{g.get('awayScore')})")
            else:
                print(f"  id={gid} {side:4} — not in fresh raw /lines")
    print("-" * 74)
    overlay_rc = _collision_audit(raw)

    rc = 0
    if not sync.get("synchronized"):
        rc = 1
    if overlay_rc:
        print("NOTE: overlay collisions are non-authoritative (presentation only); they do not gate sync.")
    print(f"[EXIT {rc}] " + ("clean: synchronized, zero missing/conflicts/ineligible."
                             if rc == 0 else "not synchronized — board stays fail-closed."))
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
