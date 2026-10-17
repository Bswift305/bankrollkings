#!/usr/bin/env python3
"""READ-ONLY diagnosis of the CFB manifest-vs-history coverage gap (docs/cfb_runtime_data_corrective.md).

The Active ATS Wave fail-closes on "missing decisions": completed, line-bearing FBS-team games present in
the manifest (fetch_cfb_line_moves.py: CFBD /lines, MEDIAN spread across books) but absent from the graded
record (build_ncaaf_game_line_backfill.py over NCAAF_GameLines_History.csv from fetch_cfbd_game_lines_history.py,
which keeps lines[0] only). BOTH feeds call the SAME endpoint:
    GET https://api.collegefootballdata.com/lines?year=<season>&seasonType=regular   (one call, no pagination)
so the RAW universe is identical; any loss is in the history fetcher's NORMALIZATION.

This is ANCHORED ON THE STABLE CFBD GAME `id` (directive point 1). It fetches /lines once (read), replays
the history keep/drop logic per game id, and joins the on-disk graded results (which lack ids -> matched by
resolved team/opp, with ambiguity flagged). It writes nothing and changes no pipeline. Run on prod:
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

import cfb_current_form as cff
import fetch_cfbd_game_lines_history as histmod   # reuse the EXACT history normalization helpers
from app import normalize_ncaaf_team_name as _nz

BASE_DIR = Path(__file__).resolve().parent
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
    if not s:
        return None
    try:
        return dt.datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except ValueError:
        return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--season", type=int, default=2026)
    ap.add_argument("--completed-week", type=int, default=6)
    args = ap.parse_args()
    from services.env_loader import load_local_env
    load_local_env(BASE_DIR)

    raw = _fetch_lines(args.season)
    print("=" * 72)
    print(f"CFB LINE-COVERAGE RECONCILIATION (by CFBD game id) — season {args.season}, thru wk {args.completed_week}")
    print("=" * 72)
    print(f"raw /lines games returned        : {len(raw)}   (single GET, seasonType=regular, no pagination)")
    ids = [g.get("id") for g in raw]
    print(f"distinct game ids / null ids     : {len(set(i for i in ids if i is not None))} / {sum(1 for i in ids if i is None)}")

    fbs = cff._fbs_teams()
    if not fbs:
        print("WARNING: _fbs_teams() empty (cfb_2026_results runtime copy missing) — FBS tagging degraded.")

    # Graded decisions actually on disk: (week, resolve(team), resolve(opp)); results carry no game id.
    graded = set()
    name_collisions = Counter()
    try:
        rdf = pd.read_csv(RESULTS_CSV, low_memory=False)
        rdf = rdf[(rdf["MarketType"].astype(str).str.upper() == "SPREAD")
                  & (pd.to_numeric(rdf["Season"], errors="coerce") == args.season)
                  & (rdf["OutcomeState"].astype(str).isin(["Hit", "Miss", "Push"]))
                  & (pd.to_numeric(rdf["Line"], errors="coerce").notna())]
        for _, r in rdf.iterrows():
            wk = pd.to_numeric(r["Week"], errors="coerce")
            if pd.notna(wk):
                graded.add((int(wk), cff._resolve(str(r.get("Team", ""))), cff._resolve(str(r.get("Opponent", "")))))
    except Exception as exc:
        print(f"WARNING: could not read results CSV ({type(exc).__name__}: {exc})")

    # Season start (earliest kickoff) for the calendar-date vs numbered-week drift check.
    starts = [d for d in (_start_date(g) for g in raw) if d]
    season_start = min(starts) if starts else None

    buckets = Counter()
    samples = defaultdict(list)
    expected_ids = []
    key_to_ids = defaultdict(list)        # (week, rh, ra) -> [game ids]  (name-join ambiguity detector)
    wk0 = neutral_expected = neutral_missing = datewk_mismatch = 0
    fcs_expected = fcs_missing = 0

    for g in raw:
        gid, wk = g.get("id"), g.get("week")
        if wk == 0:
            wk0 += 1
        if wk is None or int(wk) > args.completed_week:
            continue
        if g.get("homeScore") is None or g.get("awayScore") is None:
            continue                                   # not completed -> not in the expected universe
        lines = g.get("lines") or []
        med = _median([l.get("spread") for l in lines])
        if med is None:
            continue                                   # no market line -> legitimately not expected
        home, away = str(g.get("homeTeam") or ""), str(g.get("awayTeam") or "")
        rh, ra = cff._resolve(home), cff._resolve(away)
        first = histmod._first_line(g)
        first_spread = histmod._home_spread(first) if first else None
        nh, na = _nz(home), _nz(away)
        sd = _start_date(g)
        if season_start and sd:
            delta_wk = (sd - season_start).days // 7 + 1
            if abs(delta_wk - int(wk)) > 1:
                datewk_mismatch += 1

        for team, opp, rteam, ropp in ((home, away, rh, ra), (away, home, ra, rh)):
            if fbs and rteam not in fbs:
                continue                               # expected universe = FBS-team sides only
            expected_ids.append(gid)
            key = (int(wk), rteam, ropp)
            key_to_ids[key].append(gid)
            is_fcs = bool(fbs) and (ropp not in fbs)
            if is_fcs:
                fcs_expected += 1
            if g.get("neutralSite"):
                neutral_expected += 1
            if key in graded:
                buckets["graded_ok"] += 1
                continue
            # ---- classify the miss by reason (directive point 3) ----
            if _nz(home) == "" or _nz(away) == "":
                reason = "lost_in_normalize:name_blanked"
            elif first_spread is None:
                reason = "lost_in_normalize:first_line_null (median has a spread; lines[0] does not)"
            else:
                reason = "in_history_not_graded (grading/join/name-resolution)"
            buckets[reason] += 1
            if is_fcs:
                fcs_missing += 1
            if g.get("neutralSite"):
                neutral_missing += 1
            samples[reason].append(f"id={gid} wk{wk} {team} vs {opp} | med={med} first={first_spread} norm=({na!r},{nh!r})")

    print(f"expected FBS-team decisions      : {len(expected_ids)} across {len(set(expected_ids))} games")
    ambiguous = {k: v for k, v in key_to_ids.items() if len(set(v)) > 1}
    print(f"name-join ambiguous keys         : {len(ambiguous)}   (same (week,team,opp) -> >1 game id)")
    print("-" * 72)
    print("RECONCILIATION BY REASON (directive point 3):")
    for reason, n in buckets.most_common():
        print(f"  {n:4}  {reason}")
        for s in samples.get(reason, [])[:8]:
            print(f"          {s}")
    print("-" * 72)
    print("TARGETED CHECKS (directive point 4):")
    print(f"  FBS-vs-FCS expected / missing  : {fcs_expected} / {fcs_missing}")
    print(f"  neutral-site expected / missing: {neutral_expected} / {neutral_missing}")
    print(f"  week-0 games in raw feed       : {wk0}")
    print(f"  date-vs-numbered-week drift    : {datewk_mismatch} games (|calendar wk - labeled wk| > 1)")
    print(f"  pagination / truncation        : single unpaginated GET; {len(raw)} games returned")
    print("  named FBS-FBS probes:")
    named = {"washington|washington state", "kansas|missouri", "miami (oh)|pittsburgh",
             "auburn|southern miss", "app state|maine", "kansas|long island university"}
    for g in raw:
        h, a = str(g.get("homeTeam") or "").lower(), str(g.get("awayTeam") or "").lower()
        if f"{h}|{a}" in named or f"{a}|{h}" in named:
            lines = g.get("lines") or []
            first = histmod._first_line(g)
            fs = histmod._home_spread(first) if first else None
            print(f"    id={g.get('id')} wk{g.get('week')} {g.get('awayTeam')} @ {g.get('homeTeam')} "
                  f"completed={g.get('homeScore') is not None} books={len(lines)} "
                  f"median={_median([l.get('spread') for l in lines])} first_line={fs} "
                  f"providers={[l.get('provider') for l in lines]} neutral={g.get('neutralSite')}")
    print("-" * 72)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
