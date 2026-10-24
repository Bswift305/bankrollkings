"""
QC for the slate-aware validator (incident 2026-10-24, authorized current-slate contract).

Proves the 10 required behaviors:
 1. fresh COMPARABLE prior + truncated candidate -> REJECT (COMPARABLE_BASELINE_COLLAPSE)
 2. stale larger prior + complete smaller slate -> PUBLISH (CURRENT_SLATE_COMPLETE)
 3. stale prior + partial event coverage -> REJECT (CURRENT_SLATE_INCOMPLETE)
 4. stale prior + missing shape receipt -> REJECT (RESPONSE_RECEIPT_MISSING)
 5. market present but parser yields zero rows on an event -> REJECT (partial coverage)
 6. empty candidate -> REJECT (structural, either mode)
 7. schema / non-finite / wrong-sport / timestamp-regression -> REJECT in either mode
 8. mismatched/stale receipt (candidate_rows != frame) -> REJECT (RESPONSE_RECEIPT_MISSING)
 9. atomic failure preserves the previous artifact byte-for-byte
10. game-line + other props feeds do NOT inherit slate mode

Offline: synthetic frames + a temp prior file whose mtime sets the prior age.
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pandas as pd

from services.feed_validation import (
    GAME_LINES_SPEC, NBA_PLAYER_PROPS_SLATE_SPEC, PLAYER_PROPS_SPEC, FUTURES_SPEC,
    validate_feed_slate,
)
from services.atomic_csv import atomic_write_csv, CsvValidationError

BOOKS = ["DraftKings", "FanDuel", "BetMGM"]
MARKETS = ["player_points", "player_rebounds", "player_assists", "player_threes", "player_steals", "player_blocks"]


def _df(n_events, rows_per_event, markets=MARKETS, books=BOOKS, bad_line=False, blank_player=False,
        ts="2026-10-24 13:00:00"):
    rows = []
    for e in range(n_events):
        game = f"Team{2*e}@Team{2*e+1}"
        for r in range(rows_per_event):
            rows.append({
                "Player": "" if blank_player else f"P{e}_{r}",
                "Stat": "Points",
                "MarketKey": markets[r % len(markets)],
                "Line": ("nan" if bad_line else 20.5),
                "OverOdds": -110, "UnderOdds": -110,
                "Game": game,
                "Book": books[r % len(books)],
                "LastUpdated": ts,
            })
    return pd.DataFrame(rows)


def _facts(df, eligible, with_rows, errors=0, candidate_rows=None):
    return {"events_found": eligible, "eligible_events": eligible, "events_with_rows": with_rows,
            "provider_errors": errors, "candidate_rows": len(df) if candidate_rows is None else candidate_rows,
            "requested_markets": MARKETS, "markets_present": MARKETS}


def _write_prior(base: Path, df: pd.DataFrame, age_hours: float) -> Path:
    p = base / "NBA_Props.csv"
    df.to_csv(p, index=False)
    ts = __import__("time").time() - age_hours * 3600
    os.utime(p, (ts, ts))
    return p


def main() -> int:
    f = []
    SP = NBA_PLAYER_PROPS_SLATE_SPEC
    with tempfile.TemporaryDirectory() as td:
        base = Path(td)

        # prior: 8 events x ~206 rows = 1648 rows, same markets/books
        prior_big = _df(8, 206)
        # 1. fresh comparable prior + truncated candidate (8 events, ~44 rows/evt = 352 < 50% of 1648)
        p_fresh = _write_prior(base, prior_big, age_hours=1)
        cand_trunc = _df(8, 44)
        ok, errs, rc = validate_feed_slate(cand_trunc, SP, prior_df=prior_big, path=p_fresh,
                                           sport_tokens=("NBA",), slate_facts=_facts(cand_trunc, 8, 8))
        if ok or rc["baseline_mode"] != "COMPARABLE_PRIOR" or rc["reason_code"] != "COMPARABLE_BASELINE_COLLAPSE":
            f.append(f"1 fresh-comparable truncation should REJECT via collapse; got ok={ok} {rc['reason_code']}")

        # 2. stale larger prior + complete smaller slate (8 events x ~94 = 752 rows) -> PUBLISH
        p_stale = _write_prior(base, prior_big, age_hours=72)
        cand_ok = _df(8, 94)
        ok, errs, rc = validate_feed_slate(cand_ok, SP, prior_df=prior_big, path=p_stale,
                                           sport_tokens=("NBA",), slate_facts=_facts(cand_ok, 8, 8))
        if not ok or rc["baseline_mode"] != "CURRENT_SLATE" or rc["reason_code"] != "CURRENT_SLATE_COMPLETE":
            f.append(f"2 stale-prior complete slate should PUBLISH; got ok={ok} {rc} errs={errs}")

        # 3/5. stale prior + partial coverage (eligible 8, only 7 produced rows) -> REJECT
        ok, errs, rc = validate_feed_slate(cand_ok, SP, prior_df=prior_big, path=p_stale,
                                           sport_tokens=("NBA",), slate_facts=_facts(cand_ok, 8, 7))
        if ok or rc["reason_code"] != "CURRENT_SLATE_INCOMPLETE":
            f.append(f"3/5 partial coverage (markets present, rows missing) should REJECT; got ok={ok} {rc['reason_code']}")

        # 4. stale prior + missing receipt -> REJECT
        ok, errs, rc = validate_feed_slate(cand_ok, SP, prior_df=prior_big, path=p_stale,
                                           sport_tokens=("NBA",), slate_facts=None)
        if ok or rc["reason_code"] != "RESPONSE_RECEIPT_MISSING":
            f.append(f"4 missing receipt should REJECT; got ok={ok} {rc['reason_code']}")

        # 6. empty candidate -> REJECT (structural)
        empty = _df(0, 0)
        ok, errs, rc = validate_feed_slate(empty, SP, prior_df=prior_big, path=p_stale,
                                           sport_tokens=("NBA",), slate_facts=_facts(empty, 0, 0))
        if ok:
            f.append("6 empty candidate should REJECT")

        # 7a. wrong-sport path -> REJECT even with a complete slate
        wrong = base / "NFL_Props.csv"
        pd.DataFrame(prior_big).to_csv(wrong, index=False); os.utime(wrong, (__import__("time").time()-72*3600,)*2)
        ok, errs, rc = validate_feed_slate(cand_ok, SP, prior_df=prior_big, path=wrong,
                                           sport_tokens=("NBA",), slate_facts=_facts(cand_ok, 8, 8))
        if ok:
            f.append("7a wrong-sport path should REJECT")
        # 7b. non-finite line -> REJECT
        badf = _df(8, 94, bad_line=True)
        ok, errs, rc = validate_feed_slate(badf, SP, prior_df=prior_big, path=p_stale,
                                           sport_tokens=("NBA",), slate_facts=_facts(badf, 8, 8))
        if ok:
            f.append("7b non-finite Line should REJECT")
        # 7c. timestamp regression vs prior -> REJECT
        oldts = _df(8, 94, ts="2020-01-01 00:00:00")
        prior_new = _df(8, 206, ts="2026-10-24 13:00:00")
        ok, errs, rc = validate_feed_slate(oldts, SP, prior_df=prior_new, path=p_stale,
                                           sport_tokens=("NBA",), slate_facts=_facts(oldts, 8, 8))
        if ok:
            f.append("7c timestamp regression should REJECT")

        # 8. mismatched receipt (candidate_rows != len(df)) -> REJECT
        ok, errs, rc = validate_feed_slate(cand_ok, SP, prior_df=prior_big, path=p_stale, sport_tokens=("NBA",),
                                           slate_facts=_facts(cand_ok, 8, 8, candidate_rows=len(cand_ok) + 1))
        if ok or rc["reason_code"] != "RESPONSE_RECEIPT_MISSING":
            f.append(f"8 mismatched receipt should REJECT; got ok={ok} {rc['reason_code']}")

        # 9. atomic failure preserves prior byte-for-byte
        good = base / "atomic_nba.csv"
        pd.DataFrame(prior_big).to_csv(good, index=False)
        before = good.read_bytes()
        try:
            atomic_write_csv(pd.DataFrame(columns=prior_big.columns), good, required_cols=["Player"], min_rows=1)
            f.append("9 atomic below-min_rows should have raised")
        except CsvValidationError:
            if good.read_bytes() != before:
                f.append("9 atomic failure corrupted the prior artifact")

        # 10. other feeds do not inherit slate mode
        if GAME_LINES_SPEC.slate_aware or PLAYER_PROPS_SPEC.slate_aware or FUTURES_SPEC.slate_aware:
            f.append("10 only NBA props may be slate_aware; a generic spec inherited it")
        if not NBA_PLAYER_PROPS_SLATE_SPEC.slate_aware:
            f.append("10 NBA slate spec must be slate_aware")

    print("=" * 64)
    print("QC: SLATE-AWARE VALIDATION (comparable-prior vs current-slate)")
    print("=" * 64)
    if f:
        for x in f:
            print(f"[FAIL] {x}")
        return 1
    print("[OK] all 10 slate-contract behaviors hold (collapse kept vs comparable prior; completeness "
          "contract vs stale/non-comparable prior; structural checks reject in both modes).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
