#!/usr/bin/env python3
"""READ-ONLY diagnosis of the CFB manifest-vs-history coverage gap (docs/cfb_runtime_data_corrective.md).

The Active ATS Wave fail-closes on "missing decisions": completed, line-bearing FBS-team games present in
the manifest (fetch_cfb_line_moves.py: CFBD /lines, median spread across books) but absent from the graded
record (build_ncaaf_game_line_backfill.py over NCAAF_GameLines_History.csv, produced by
fetch_cfbd_game_lines_history.py). BOTH feeds call the SAME endpoint:
    GET https://api.collegefootballdata.com/lines?year=<season>&seasonType=regular   (one call, no pagination)
so the RAW universe is identical; any loss is in the history fetcher's NORMALIZATION. This replays that
normalization on the same raw payload, keyed by the stable CFBD game `id`, and buckets every expected but
ungraded game by REASON. It fetches /lines (read) and reads the on-disk history + results CSVs; it writes
nothing and changes no pipeline. Run on prod:
    sudo -u ubuntu bash -lc 'cd /opt/bankrollkings && set -a && . .env && set +a && venv/bin/python diagnose_cfb_line_coverage.py --completed-week 6'
"""
from __future__ import annotations

import argparse
import json
import os
import statistics
import urllib.request
from collections import Counter
from pathlib import Path

import pandas as pd

import cfb_current_form as cff
import fetch_cfbd_game_lines_history as histmod   # reuse the EXACT history normalization helpers

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


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--season", type=int, default=2026)
    ap.add_argument("--completed-week", type=int, default=6, help="Count games with week <= this.")
    args = ap.parse_args()
    from services.env_loader import load_local_env
    load_local_env(BASE_DIR)

    raw = _fetch_lines(args.season)
    print("=" * 66)
    print(f"CFB LINE-COVERAGE RECONCILIATION — season {args.season}, through week {args.completed_week}")
    print("=" * 66)
    print(f"raw /lines games returned      : {len(raw)}   (single call, seasonType=regular)")

    fbs = cff._fbs_teams()
    if not fbs:
        print("WARNING: _fbs_teams() is empty (cfb_2026_results runtime copy missing) — FBS tagging degraded.")

    # Graded decisions actually on disk (what the wave counts): (week, resolve(team), resolve(opp)).
    graded = set()
    try:
        rdf = pd.read_csv(RESULTS_CSV, low_memory=False)
        rdf = rdf[(rdf["MarketType"].astype(str).str.upper() == "SPREAD")
                  & (pd.to_numeric(rdf["Season"], errors="coerce") == args.season)
                  & (rdf["OutcomeState"].astype(str).isin(["Hit", "Miss", "Push"]))
                  & (pd.to_numeric(rdf["Line"], errors="coerce").notna())]
        for _, r in rdf.iterrows():
            graded.add((int(pd.to_numeric(r["Week"], errors="coerce")),
                        cff._resolve(str(r.get("Team", ""))), cff._resolve(str(r.get("Opponent", "")))))
    except Exception as exc:
        print(f"WARNING: could not read results CSV ({type(exc).__name__}: {exc})")

    # History rows (what the grader had to work from), replayed from the SAME raw payload via the exact
    # normalize_payload, keyed by (week, resolve(home), resolve(away)) with a non-null home spread.
    hist_norm = histmod.normalize_payload(raw, args.season)
    hist_keys = set()
    if not hist_norm.empty:
        for _, r in hist_norm.iterrows():
            wk = pd.to_numeric(r.get("Week"), errors="coerce")
            if pd.notna(wk) and pd.notna(pd.to_numeric(r.get("HomeSpread"), errors="coerce")):
                hist_keys.add((int(wk), cff._resolve(str(r.get("Home", ""))), cff._resolve(str(r.get("Away", "")))))

    buckets = Counter()
    samples = {}
    expected = 0
    for g in raw:
        wk = g.get("week")
        if wk is None or int(wk) > args.completed_week:
            continue
        if g.get("homeScore") is None or g.get("awayScore") is None:
            continue                                   # not completed -> not expected
        lines = g.get("lines") or []
        med_spread = _median([l.get("spread") for l in lines])
        if med_spread is None:
            continue                                   # no market line -> legitimately not expected
        home, away = str(g.get("homeTeam") or ""), str(g.get("awayTeam") or "")
        rh, ra = cff._resolve(home), cff._resolve(away)
        first = histmod._first_line(g)
        first_spread = histmod._home_spread(first) if first else None
        from app import normalize_ncaaf_team_name as _nz
        for team, opp, rteam, ropp in ((home, away, rh, ra), (away, home, ra, rh)):
            if fbs and rteam not in fbs:
                continue                               # expected universe = FBS-team sides
            expected += 1
            key = (int(wk), rteam, ropp)
            if key in graded:
                buckets["graded_ok"] += 1
                continue
            # classify the miss by reason
            if key in hist_keys:
                reason = "in_history_not_graded(join/normalize)"
            elif first_spread is None:
                reason = "first_line_null (median has a spread; lines[0] does not)"
            elif _nz(home) == "" or _nz(away) == "":
                reason = "name_blanked_by_normalize"
            else:
                reason = "absent_from_history (normalize dropped a line-bearing game)"
            buckets[reason] += 1
            samples.setdefault(reason, []).append(f"wk{wk} {team} vs {opp} (med {med_spread}, first {first_spread})")

    print(f"expected FBS-team decisions    : {expected}")
    print("-" * 66)
    print("RECONCILIATION BY REASON:")
    for reason, n in buckets.most_common():
        print(f"  {n:4}  {reason}")
        for s in samples.get(reason, [])[:6]:
            print(f"          e.g. {s}")
    print("-" * 66)
    # Targeted test cases from the directive.
    print("TARGETED CHECKS:")
    _probe(raw, args, "FBS-FCS", lambda g: True)   # handled inside _probe via named lists below
    return 0


def _probe(raw, args, label, _):
    """Print raw-feed facts for the named/edge games the directive calls out."""
    named = {
        "washington|washington state", "kansas|missouri", "miami (oh)|pittsburgh",
        "auburn|southern miss", "app state|maine", "kansas|long island university",
    }
    wk0 = [g for g in raw if g.get("week") == 0]
    print(f"  week-0 games in raw feed     : {len(wk0)}"
          + (f"  e.g. {wk0[0].get('awayTeam')} @ {wk0[0].get('homeTeam')}" if wk0 else ""))
    for g in raw:
        h, a = str(g.get("homeTeam") or "").lower(), str(g.get("awayTeam") or "").lower()
        if f"{h}|{a}" in named or f"{a}|{h}" in named:
            lines = g.get("lines") or []
            med = _median([l.get("spread") for l in lines])
            first = histmod._first_line(g)
            fs = histmod._home_spread(first) if first else None
            nh = __import__("app").normalize_ncaaf_team_name(g.get("homeTeam"))
            na = __import__("app").normalize_ncaaf_team_name(g.get("awayTeam"))
            print(f"  {g.get('awayTeam')} @ {g.get('homeTeam')} wk{g.get('week')} "
                  f"completed={g.get('homeScore') is not None} books={len(lines)} "
                  f"median_spread={med} first_line_spread={fs} norm=({na!r},{nh!r}) "
                  f"neutral={g.get('neutralSite')}")


if __name__ == "__main__":
    raise SystemExit(main())
