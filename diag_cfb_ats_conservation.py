"""
CFB ATS Audit #3 -- conservation reconciliation (read-only). Partitions EVERY graded (GameID, TeamSide)
decision into exactly ONE disjoint terminal disposition against the runtime manifest, proving

    graded universe = expected_FBS + known_non_FBS + no_line + future_week + not_completed
                      + outside_manifest + unknown_conference        (no overlap, no residual)

and details every row that is NOT one of {expected_FBS, known_non_FBS, no_line} -- i.e. the previously
unexplained remainder. NO CFBD call, NO membership/source change. Fingerprints consumed artifacts.

Operational distinction preserved: board synchronization/completeness is judged here ONLY from the
last-known-good runtime artifacts; a synchronized cached artifact does NOT imply CFBD is reachable (no
provider call is made; CFBD quota state is out of scope).

Run on the box (prod/owner), venv python:
    /opt/bankrollkings/venv/bin/python3 /opt/bankrollkings/diag_cfb_ats_conservation.py
"""
from __future__ import annotations

import hashlib
import json
import os
from collections import Counter

import pandas as pd

import app
import bk_runtime

GRADED = app.DATA_DIR / "tracking" / "NCAAF_GameLineResults.csv"
MANIFEST = bk_runtime.scenario_read_path("cfb_line_moves.json")
SEASON = 2026


def _fp(paths):
    fp = {}
    for p in paths:
        try:
            st = os.stat(p)
            with open(p, "rb") as fh:
                fp[p] = (hashlib.sha256(fh.read()).hexdigest()[:16], st.st_mtime_ns, st.st_size)
        except OSError:
            fp[p] = None
    return fp


def main() -> int:
    print("=" * 96)
    print("CFB ATS AUDIT #3 -- CONSERVATION RECONCILIATION (read-only; no CFBD call)")
    print("=" * 96)
    consumed = [str(GRADED), str(MANIFEST)]
    fp0 = _fp(consumed)

    # authoritative graded decision set (the 1,732) + their per-key detail
    sd = app._cfb_active_cover_streaks(SEASON)
    if sd.get("read_error"):
        print(f"graded read_error={sd['read_error']!r} -> fail closed"); return 2
    graded_keys = sd.get("graded_keys", set())
    print(f"graded decisions (authoritative (GameID,TeamSide) keys): {len(graded_keys)}")

    # re-read the graded CSV to attach per-key detail (week/conf/team/opp/date/line/state)
    df = pd.read_csv(GRADED, low_memory=False)
    df = df[(df["MarketType"].astype(str).str.upper() == "SPREAD")
            & (pd.to_numeric(df["Season"], errors="coerce") == SEASON)
            & (df["OutcomeState"].astype(str).isin(["Hit", "Miss", "Push"]))]
    detail = {}
    for _, r in df.iterrows():
        gid = bk_runtime.cfb_game_id(r.get("GameID"))
        side = str(r.get("TeamSide") or "").strip().upper()
        if gid is None or side not in ("HOME", "AWAY"):
            continue
        key = (gid, side)
        if key in graded_keys and key not in detail:
            detail[key] = {"team": str(r.get("Team", "")).strip(), "opp": str(r.get("Opponent", "")).strip(),
                           "week": r.get("Week"), "date": str(r.get("GameDate", "")).strip(),
                           "line": r.get("Line"), "state": str(r.get("OutcomeState", "")).strip(),
                           "graded_conf": str(r.get("Conf", "")).strip()}

    # runtime manifest -> per (GameID, TeamSide) disposition
    lm = json.load(open(MANIFEST, encoding="utf-8"))
    games = lm.get("games", []) or []
    # completed_week exactly as build_cfb_wave_context derives it
    upcoming = [g for g in games if not g.get("completed") and g.get("spread_now") is not None]
    wave_week = min((g["week"] for g in upcoming), default=None)
    completed_week = (wave_week - 1) if wave_week else None
    print(f"manifest season={lm.get('season')} updated={lm.get('updated')!r} games={len(games)} "
          f"wave_week={wave_week} completed_week={completed_week}")

    man = {}        # (gid, side) -> (disposition, game-conf, game detail)
    man_game = {}
    for g in games:
        gid = bk_runtime.cfb_game_id(g.get("game_id"))
        if gid is None:
            continue
        wk = g.get("week")
        completed = bool(g.get("completed"))
        no_line = g.get("spread_now") is None and g.get("spread_open") is None
        man_game[gid] = g
        for side, conf in (("HOME", g.get("home_conf")), ("AWAY", g.get("away_conf"))):
            if not completed or wk is None:
                disp = "not_completed"
            elif completed_week is not None and wk > completed_week:
                disp = "future_week"
            elif no_line:
                disp = "no_line"
            else:
                cls = app._cfb_conf_class(conf)
                disp = {"FBS": "expected_FBS", "NON_FBS": "known_non_FBS"}.get(cls, "unknown_conference")
            man[(gid, side)] = (disp, conf)

    # classify every graded key into exactly one disposition
    part = Counter()
    remainder = []   # anything not in {expected_FBS, known_non_FBS, no_line}
    for key in graded_keys:
        if key in man:
            disp, conf = man[key]
        else:
            disp, conf = "outside_manifest", None
        part[disp] += 1
        if disp not in ("expected_FBS", "known_non_FBS", "no_line"):
            gid, side = key
            d = detail.get(key, {})
            g = man_game.get(gid, {})
            remainder.append({
                "GameID": gid, "TeamSide": side, "team": d.get("team"), "opp": d.get("opp"),
                "week": d.get("week"), "date": d.get("date"), "line": d.get("line"), "state": d.get("state"),
                "graded_conf": d.get("graded_conf"),
                "manifest_match": gid in man_game,
                "manifest_home_conf": g.get("home_conf"), "manifest_away_conf": g.get("away_conf"),
                "manifest_week": g.get("week"), "manifest_completed": g.get("completed"),
                "reason_code": disp.upper(),
            })

    print("-" * 96)
    print("DISJOINT PARTITION of the graded universe:")
    total = 0
    for disp in ("expected_FBS", "known_non_FBS", "no_line", "future_week", "not_completed",
                 "outside_manifest", "unknown_conference"):
        print(f"  {disp:20} {part.get(disp, 0)}")
        total += part.get(disp, 0)
    print(f"  {'TOTAL':20} {total}   (graded_keys={len(graded_keys)})")
    conserved = (total == len(graded_keys))
    print(f"  conservation (sum == graded, no residual, no overlap): {conserved}")
    # sync-side counters for cross-reference (manifest-derived)
    sync = app._cfb_ats_sync(sd, lm, completed_week, SEASON)
    print(f"  cross-ref (manifest-side): expected_decisions={sync.get('expected_decisions')} "
          f"exclusions={sync.get('exclusions')} missing={sync.get('missing_count')} "
          f"ineligible={sync.get('ineligible')} malformed={sync.get('malformed_rows')} "
          f"conflicts={sync.get('conflicting_duplicates')} collapsed={sync.get('exact_duplicates_collapsed')}")

    print("-" * 96)
    print(f"REMAINDER (graded rows not in expected_FBS / known_non_FBS / no_line): {len(remainder)}")
    for row in remainder:
        print(f"  {row['reason_code']}: GameID={row['GameID']} {row['TeamSide']} "
              f"{row['team']} vs {row['opp']}  wk={row['week']}/{row['date']}  line={row['line']} {row['state']}  "
              f"graded_conf={row['graded_conf']!r}  manifest_match={row['manifest_match']} "
              f"man_wk={row['manifest_week']} man_completed={row['manifest_completed']} "
              f"man_conf=({row['manifest_home_conf']}/{row['manifest_away_conf']})")

    fp1 = _fp(consumed)
    changed = sorted(p for p in consumed if fp0.get(p) != fp1.get(p))
    print("=" * 96)
    print(f"READ-ONLY PROOF: {len(consumed)} artifact(s); {'ALL UNCHANGED' if not changed else 'CHANGED: ' + ', '.join(changed)}")
    if changed:
        return 4
    return 0 if conserved else 3


if __name__ == "__main__":
    raise SystemExit(main())
