"""
QC for the slate-aware validator (incident 2026-10-24, authorized current-slate contract + the three
precision refinements: independent coverage denominator, strong receipt binding, structural checks in
both modes).

Proves:
 1. fresh COMPARABLE prior + truncated candidate -> REJECT (COMPARABLE_BASELINE_COLLAPSE)
 2. stale larger prior + complete smaller slate -> PUBLISH (CURRENT_SLATE_COMPLETE)
 3. INDEPENDENT denominator: a manifest event entirely ABSENT from the response still counts against
    coverage (covered 7 of eligible 8) -> REJECT (CURRENT_SLATE_INCOMPLETE)
 4. missing / incomplete receipt -> REJECT (RESPONSE_RECEIPT_MISSING)
 5. market present but zero rows on an event (covered < eligible) -> REJECT
 6. empty candidate -> REJECT (structural)
 7. schema / non-finite / wrong-sport / timestamp-regression -> REJECT in either mode
 8. receipt bound to ANOTHER candidate (wrong candidate_sha256) -> REJECT (RESPONSE_RECEIPT_MISSING)
 9. atomic failure preserves the previous artifact byte-for-byte
10. game-line + other props feeds do NOT inherit slate mode
11. the eligible-event denominator is read from an INDEPENDENT manifest file, not the props response

Offline: synthetic frames + a temp prior file whose mtime sets the prior age.
"""
from __future__ import annotations

import os
import tempfile
import time
from pathlib import Path

import pandas as pd

from services.feed_validation import (
    GAME_LINES_SPEC, NBA_PLAYER_PROPS_SLATE_SPEC, PLAYER_PROPS_SPEC, FUTURES_SPEC,
    candidate_sha256, validate_feed_slate,
)
from services.atomic_csv import atomic_write_csv, CsvValidationError

BOOKS = ["DraftKings", "FanDuel", "BetMGM"]
MARKETS = ["player_points", "player_rebounds", "player_assists", "player_threes", "player_steals", "player_blocks"]


def _df(n_events, rows_per_event, bad_line=False, ts="2026-10-24 13:00:00"):
    rows = []
    for e in range(n_events):
        game = f"team{2*e}@team{2*e+1}"
        for r in range(rows_per_event):
            rows.append({"Player": f"P{e}_{r}", "Stat": "Points", "MarketKey": MARKETS[r % len(MARKETS)],
                         "Line": ("nan" if bad_line else 20.5), "OverOdds": -110, "UnderOdds": -110,
                         "Game": game, "Book": BOOKS[r % len(BOOKS)], "LastUpdated": ts})
    return pd.DataFrame(rows)


def _facts(df, eligible_ids, covered_ids, errors=0, sha=None, run_id="run1", sport="basketball_nba"):
    return {"run_id": run_id, "sport": sport,
            "candidate_sha256": candidate_sha256(df) if sha is None else sha,
            "provider_errors": errors, "candidate_rows": len(df),
            "requested_markets": MARKETS, "markets_present": MARKETS, "bookmakers": BOOKS,
            "fetch_start": "s", "fetch_end": "e",
            "eligible_event_ids": list(eligible_ids), "response_event_ids": list(covered_ids),
            "covered_event_ids": list(covered_ids)}


def _write_prior(base: Path, df: pd.DataFrame, age_hours: float) -> Path:
    p = base / "NBA_Props.csv"
    df.to_csv(p, index=False)
    _age(p, age_hours)
    return p


def _age(p: Path, age_hours: float) -> None:
    ts = time.time() - age_hours * 3600
    os.utime(p, (ts, ts))


def main() -> int:
    f = []
    SP = NBA_PLAYER_PROPS_SLATE_SPEC
    E8 = [f"g{i}" for i in range(8)]
    with tempfile.TemporaryDirectory() as td:
        base = Path(td)
        prior_big = _df(8, 206)                       # 1648 rows, 8 events
        p = _write_prior(base, prior_big, age_hours=72)   # ONE prior file; re-aged per case below

        # 1. fresh comparable prior + truncated candidate -> collapse reject
        _age(p, 1)
        trunc = _df(8, 44)                            # 352 < 50% of 1648
        ok, _, rc = validate_feed_slate(trunc, SP, prior_df=prior_big, path=p, sport_tokens=("NBA",),
                                        slate_facts=_facts(trunc, E8, E8))
        if ok or rc["reason_code"] != "COMPARABLE_BASELINE_COLLAPSE":
            f.append(f"1 comparable truncation should collapse-reject; {ok} {rc['reason_code']}")

        # 2. stale prior + complete slate -> publish
        _age(p, 72)
        p_stale = p
        cand = _df(8, 94)                             # 752 rows, all 8 eligible covered
        ok, _, rc = validate_feed_slate(cand, SP, prior_df=prior_big, path=p_stale, sport_tokens=("NBA",),
                                        slate_facts=_facts(cand, E8, E8))
        if not ok or rc["baseline_mode"] != "CURRENT_SLATE" or rc["reason_code"] != "CURRENT_SLATE_COMPLETE":
            f.append(f"2 stale complete slate should publish; {ok} {rc}")
        if rc["event_coverage"] != 1.0:
            f.append(f"2 coverage should be 1.0; got {rc['event_coverage']}")

        # 3/5. independent denominator: manifest has 8, candidate covers only 7 -> reject
        ok, _, rc = validate_feed_slate(cand, SP, prior_df=prior_big, path=p_stale, sport_tokens=("NBA",),
                                        slate_facts=_facts(cand, E8, E8[:7]))
        if ok or rc["reason_code"] != "CURRENT_SLATE_INCOMPLETE" or rc["event_coverage"] >= 1.0:
            f.append(f"3/5 missing manifest event must drop coverage + reject; {ok} {rc['reason_code']} cov={rc['event_coverage']}")

        # 4. missing receipt
        ok, _, rc = validate_feed_slate(cand, SP, prior_df=prior_big, path=p_stale, sport_tokens=("NBA",),
                                        slate_facts=None)
        if ok or rc["reason_code"] != "RESPONSE_RECEIPT_MISSING":
            f.append(f"4 missing receipt reject; {ok} {rc['reason_code']}")
        # 4b. incomplete receipt (no run_id)
        bad = _facts(cand, E8, E8); bad.pop("run_id")
        ok, _, rc = validate_feed_slate(cand, SP, prior_df=prior_big, path=p_stale, sport_tokens=("NBA",),
                                        slate_facts=bad)
        if ok or rc["reason_code"] != "RESPONSE_RECEIPT_MISSING":
            f.append(f"4b incomplete receipt (no run_id) reject; {ok} {rc['reason_code']}")

        # 6. empty candidate
        empty = _df(0, 0)
        ok, _, rc = validate_feed_slate(empty, SP, prior_df=prior_big, path=p_stale, sport_tokens=("NBA",),
                                        slate_facts=_facts(empty, E8, []))
        if ok:
            f.append("6 empty candidate should reject")

        # 7a wrong-sport path
        wrong = base / "NFL_Props.csv"; prior_big.to_csv(wrong, index=False); os.utime(wrong, (time.time()-72*3600,)*2)
        ok, _, rc = validate_feed_slate(cand, SP, prior_df=prior_big, path=wrong, sport_tokens=("NBA",),
                                        slate_facts=_facts(cand, E8, E8))
        if ok:
            f.append("7a wrong-sport path should reject")
        # 7b non-finite
        bf = _df(8, 94, bad_line=True)
        ok, _, rc = validate_feed_slate(bf, SP, prior_df=prior_big, path=p_stale, sport_tokens=("NBA",),
                                        slate_facts=_facts(bf, E8, E8))
        if ok:
            f.append("7b non-finite Line should reject")
        # 7c timestamp regression
        old = _df(8, 94, ts="2020-01-01 00:00:00"); newp = _df(8, 206, ts="2026-10-24 13:00:00")
        ok, _, rc = validate_feed_slate(old, SP, prior_df=newp, path=p_stale, sport_tokens=("NBA",),
                                        slate_facts=_facts(old, E8, E8))
        if ok:
            f.append("7c timestamp regression should reject")

        # 8. receipt bound to ANOTHER candidate (wrong sha)
        ok, _, rc = validate_feed_slate(cand, SP, prior_df=prior_big, path=p_stale, sport_tokens=("NBA",),
                                        slate_facts=_facts(cand, E8, E8, sha="deadbeef"))
        if ok or rc["reason_code"] != "RESPONSE_RECEIPT_MISSING" or rc["receipt_sha_bound"]:
            f.append(f"8 foreign-candidate sha must reject; {ok} {rc['reason_code']} bound={rc['receipt_sha_bound']}")

        # 9. atomic failure preserves prior byte-for-byte
        good = base / "atomic_nba.csv"; prior_big.to_csv(good, index=False); before = good.read_bytes()
        try:
            atomic_write_csv(pd.DataFrame(columns=prior_big.columns), good, required_cols=["Player"], min_rows=1)
            f.append("9 atomic below-min_rows should have raised")
        except CsvValidationError:
            if good.read_bytes() != before:
                f.append("9 atomic failure corrupted the prior artifact")

    # 10. no inheritance
    if GAME_LINES_SPEC.slate_aware or PLAYER_PROPS_SPEC.slate_aware or FUTURES_SPEC.slate_aware:
        f.append("10 only NBA props may be slate_aware")
    if not NBA_PLAYER_PROPS_SLATE_SPEC.slate_aware:
        f.append("10 NBA slate spec must be slate_aware")

    # 11. the denominator comes from an INDEPENDENT manifest FILE, not the props response
    import fetch_player_props as fpp
    with tempfile.TemporaryDirectory() as td:
        base = Path(td); (base / "data/odds").mkdir(parents=True, exist_ok=True)
        pd.DataFrame([{"Away": "Miami Heat", "Home": "Charlotte Hornets", "LastUpdated": "x"},
                      {"Away": "Brooklyn Nets", "Home": "Cleveland Cavaliers", "LastUpdated": "x"},
                      {"Away": "Milwaukee Bucks", "Home": "Philadelphia 76ers", "LastUpdated": "x"}]
                     ).to_csv(base / "data/odds/NBA_Odds.csv", index=False)
        orig = fpp.BASE_DIR
        fpp.BASE_DIR = base
        try:
            keys, src = fpp._eligible_event_keys("basketball_nba")
        finally:
            fpp.BASE_DIR = orig
        if len(keys) != 3 or not src or "NBA_Odds.csv" not in src:
            f.append(f"11 eligible manifest must come from the game-lines file; got {len(keys)} from {src}")

    print("=" * 64)
    print("QC: SLATE-AWARE VALIDATION (+ independent denominator, receipt binding)")
    print("=" * 64)
    if f:
        for x in f:
            print(f"[FAIL] {x}")
        return 1
    print("[OK] all slate-contract behaviors hold: independent coverage denominator, sha/run-id receipt "
          "binding, collapse-vs-comparable kept, completeness-vs-stale, structural rejects in both modes.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
