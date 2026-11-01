"""
QC for slate-aware GAME-LINES validation (incident 2026-11-01, bk-daily F5: NCAAF "68 rows < 50% of prior
164" every Sunday after Saturday's CFB slate is played).

Proves:
 1. Sunday rollover: prior 164 rows (incl. played games), manifest = the 41 still-scheduled events, candidate
    68 rows covering all 41 -> PUBLISH (CURRENT_SLATE_COMPLETE); the old absolute rule rejects the same frame
 2. genuine collapse: manifest has 41 still-scheduled events, candidate covers 5 -> REJECT
 3. forward-window row collapse: every event present but books/rows missing -> REJECT
 4. empty slice -> REJECT (with and without a manifest)
 5. manifest missing -> ABSOLUTE_FALLBACK (fail closed, explicit reason); unchanged rule still passes a
    non-collapsed candidate
 6. manifest stale (> max age) -> ABSOLUTE_FALLBACK with MANIFEST_STALE reason
 7. prior-file staleness is irrelevant once a fresh manifest reconciles; comparable fresh manifest still
    enforces the forward collapse test
 8. receipt binding: foreign sha / row-count mismatch / missing run_id -> REJECT (RESPONSE_RECEIPT_MISSING)
 9. provider error -> REJECT
10. --allow-collapse bypasses count checks only, never structural ones
11. structural rejects in CURRENT_SLATE mode (non-finite, wrong-sport path, timestamp regression, conflicts)
12. other sports unchanged: GAME_LINES_SPEC not slate-aware, only NFL/NCAAF routed, else-branch intact
13. manifest loader: latest snapshot only, played / in-grace / out-of-window games excluded, missing file ->
    empty + reason; never reads the odds artifact (CFBD-overwritable) or the candidate
14. loader -> validator end to end on the Sunday shape

Offline: synthetic frames + temp files. No network, no paid calls.
"""
from __future__ import annotations

import inspect
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

from services.feed_validation import (
    FOOTBALL_GAME_LINES_SLATE_SPEC, GAME_LINES_SPEC, candidate_sha256, validate_feed, validate_game_lines_slate,
)

SP = FOOTBALL_GAME_LINES_SLATE_SPEC
BOOKS = ["DraftKings", "FanDuel", "BetMGM", "Caesars"]
TS = "2026-11-01 08:29"
_results: list = []


def check(name, cond, detail=""):
    _results.append((name, bool(cond)))
    print(f"[{'ok' if cond else 'FAIL'}] {name}" + ("" if cond else f" -- {detail}"))


def _lines(event_ids, books_per_event, date="2026-11-07", time_="15:30", ts=TS, bad=False):
    rows = []
    for i, gid in enumerate(event_ids):
        nb = books_per_event[i] if isinstance(books_per_event, list) else books_per_event
        for b in range(nb):
            rows.append({"Date": date, "Time": time_, "Away": f"Away{gid}", "Home": f"Home{gid}",
                         "AwayFull": f"Away{gid}", "HomeFull": f"Home{gid}", "AwayML": 150, "HomeML": -170,
                         "Spread": ("nan" if bad else -3.5), "SpreadOdds": -110, "Total": 51.5,  # synthetic-fixture
                         "OverOdds": -110, "UnderOdds": -110, "Book": BOOKS[b % len(BOOKS)], "GameID": gid,  # synthetic-fixture
                         "LastUpdated": ts})
    cols = ["Date", "Time", "Away", "Home", "AwayFull", "HomeFull", "AwayML", "HomeML", "Spread", "SpreadOdds",
            "Total", "OverOdds", "UnderOdds", "Book", "GameID", "LastUpdated"]
    return pd.DataFrame(rows, columns=cols)


def _facts(df, eligible, manifest_rows, age=20.0, sha=None, rows=None, run_id="r1", errors=0):
    return {"run_id": run_id, "sport": "americanfootball_ncaaf",
            "candidate_sha256": candidate_sha256(df) if sha is None else sha,
            "candidate_rows": len(df) if rows is None else rows, "provider_errors": errors,
            "eligible_event_ids": sorted(eligible), "manifest_source": "data/tracking/NCAAF_LineMovementHistory.csv",
            "manifest_snapshot_at": "2026-10-31T09:30:00+00:00", "manifest_age_hours": age,
            "manifest_event_rows": manifest_rows, "bookmakers": BOOKS, "fetch_start": "s", "fetch_end": "e",
            "window_end": "w"}


def main() -> int:
    with tempfile.TemporaryDirectory() as td:
        base = Path(td)
        out = base / "NCAAF_Odds.csv"
        tok = ("NCAAF",)

        # Sunday shape: 41 next-week events (68 rows: 27 events x 2 books + 14 x 1 book) still scheduled;
        # prior = Saturday's 48 played games x 2 books (96 rows) + those same 41 events (68 rows) = 164.
        nxt = [f"n{i:02d}" for i in range(41)]
        bpe = [2] * 27 + [1] * 14
        sunday = _lines(nxt, bpe)
        played = _lines([f"p{i:02d}" for i in range(48)], 2, date="2026-10-31", ts="2026-10-31 08:00")
        prior = pd.concat([played, _lines(nxt, bpe, ts="2026-10-31 08:00")], ignore_index=True)
        prior.to_csv(out, index=False)
        check("setup: Sunday shape is 68 candidate rows vs 164 prior rows", len(sunday) == 68 and len(prior) == 164,
              f"{len(sunday)} vs {len(prior)}")

        # 1. Sunday rollover publishes; the old absolute rule (the defect) rejects the same frame.
        ok, errs, rc = validate_game_lines_slate(sunday, SP, prior_df=prior, path=out, sport_tokens=tok,
                                                 slate_facts=_facts(sunday, nxt, 68))
        check("1 Sunday rollover (68 vs 164, all 41 still-scheduled events covered) -> PUBLISH",
              ok and rc["baseline_mode"] == "CURRENT_SLATE" and rc["reason_code"] == "CURRENT_SLATE_COMPLETE"
              and rc["event_coverage"] == 1.0, f"{ok} {errs} {rc['reason_code']}")
        old_ok, old_errs = validate_feed(sunday, GAME_LINES_SPEC, prior_df=prior, path=out, sport_tokens=tok)
        check("1b defect reproduced: absolute rule rejects the same Sunday frame",
              (not old_ok) and any("collapse" in e for e in old_errs), str(old_errs))

        # 2. genuine collapse: manifest 41 events, candidate covers 5.
        few = _lines(nxt[:5], 2)
        ok, errs, rc = validate_game_lines_slate(few, SP, prior_df=prior, path=out, sport_tokens=tok,
                                                 slate_facts=_facts(few, nxt, 68))
        check("2 genuine collapse (5/41 still-scheduled events) -> REJECT CURRENT_SLATE_INCOMPLETE",
              (not ok) and rc["reason_code"] == "CURRENT_SLATE_INCOMPLETE" and rc["covered_events"] == 5,
              f"{ok} {rc['reason_code']}")
        # 2b. one missing event out of 41 (97.6%) passes the 90% floor; five missing (87.8%) does not.
        ok_a, _, _ = validate_game_lines_slate(_lines(nxt[:40], bpe[:40]), SP, prior_df=prior, path=out,
                                               sport_tokens=tok, slate_facts=_facts(_lines(nxt[:40], bpe[:40]), nxt, 68))
        c36 = _lines(nxt[:36], bpe[:36])
        ok_b, _, rc_b = validate_game_lines_slate(c36, SP, prior_df=prior, path=out, sport_tokens=tok,
                                                  slate_facts=_facts(c36, nxt, 68))
        check("2b coverage floor: 40/41 publishes, 36/41 rejects", ok_a and not ok_b, f"{ok_a} {ok_b} {rc_b['reason_code']}")

        # 3. forward-window row collapse: all 41 events present but 1 row each vs manifest 120 rows on them.
        thin = _lines(nxt, 1)
        ok, errs, rc = validate_game_lines_slate(thin, SP, prior_df=prior, path=out, sport_tokens=tok,
                                                 slate_facts=_facts(thin, nxt, 120))
        check("3 forward-window row collapse (41 rows vs manifest 120 on same events) -> REJECT",
              (not ok) and rc["reason_code"] == "FORWARD_WINDOW_COLLAPSE", f"{ok} {rc['reason_code']}")

        # 4. empty slice
        empty = _lines([], 0)
        ok, errs, rc = validate_game_lines_slate(empty, SP, prior_df=prior, path=out, sport_tokens=tok,
                                                 slate_facts=_facts(empty, nxt, 68))
        check("4a empty slice with manifest -> REJECT (structural empty-slice)",
              (not ok) and any("empty" in e for e in errs), str(errs))
        ok, errs, rc = validate_game_lines_slate(empty, SP, prior_df=prior, path=out, sport_tokens=tok,
                                                 slate_facts=None)
        check("4b empty slice without manifest -> REJECT", not ok, str(errs))
        ok, errs, rc = validate_game_lines_slate(empty, SP, prior_df=None, path=out, sport_tokens=tok,
                                                 slate_facts=None, allow_collapse=True)
        check("4c empty slice, no prior, override -> still REJECT", not ok, str(errs))

        # 5. manifest missing -> fail closed to the unchanged absolute rule, with an explicit reason.
        ok, errs, rc = validate_game_lines_slate(sunday, SP, prior_df=prior, path=out, sport_tokens=tok,
                                                 slate_facts=None)
        check("5a manifest missing -> ABSOLUTE_FALLBACK reject (MANIFEST_MISSING_ABSOLUTE_FALLBACK)",
              (not ok) and rc["baseline_mode"] == "ABSOLUTE_FALLBACK"
              and rc["reason_code"] == "MANIFEST_MISSING_ABSOLUTE_FALLBACK"
              and any("MANIFEST_MISSING" in e for e in errs), f"{ok} {rc['reason_code']} {errs}")
        ok, errs, rc = validate_game_lines_slate(sunday, SP, prior_df=prior, path=out, sport_tokens=tok,
                                                 slate_facts=_facts(sunday, [], 0))
        check("5b manifest present but zero still-scheduled events -> ABSOLUTE_FALLBACK reject",
              (not ok) and rc["reason_code"] == "MANIFEST_MISSING_ABSOLUTE_FALLBACK", f"{ok} {rc['reason_code']}")
        big = _lines([f"b{i:02d}" for i in range(50)], 2)
        ok_new, _, rc = validate_game_lines_slate(big, SP, prior_df=prior, path=out, sport_tokens=tok, slate_facts=None)
        ok_old, _ = validate_feed(big, GAME_LINES_SPEC, prior_df=prior, path=out, sport_tokens=tok)
        check("5c fallback == old rule on a non-collapsed candidate (100 vs 164 publishes in both)",
              ok_new and ok_old and rc["reason_code"] == "MANIFEST_MISSING_ABSOLUTE_FALLBACK", f"{ok_new} {ok_old}")

        # 6. manifest stale -> fallback.
        ok, errs, rc = validate_game_lines_slate(sunday, SP, prior_df=prior, path=out, sport_tokens=tok,
                                                 slate_facts=_facts(sunday, nxt, 68, age=300.0))
        check("6a stale manifest (300h > 192h) -> MANIFEST_STALE_ABSOLUTE_FALLBACK reject",
              (not ok) and rc["reason_code"] == "MANIFEST_STALE_ABSOLUTE_FALLBACK", f"{ok} {rc['reason_code']}")
        ok, errs, rc = validate_game_lines_slate(sunday, SP, prior_df=prior, path=out, sport_tokens=tok,
                                                 slate_facts=_facts(sunday, nxt, 68, age=None))
        check("6b manifest with unknown age -> treated stale, fallback reject",
              (not ok) and rc["manifest_reason"] == "MANIFEST_STALE", f"{ok} {rc['manifest_reason']}")

        # 7. prior staleness irrelevant under a fresh manifest; comparable fresh manifest still enforces collapse.
        import os, time as _t
        old = _t.time() - 96 * 3600
        os.utime(out, (old, old))
        ok, errs, rc = validate_game_lines_slate(sunday, SP, prior_df=prior, path=out, sport_tokens=tok,
                                                 slate_facts=_facts(sunday, nxt, 68, age=4.0))
        check("7a 96h-old prior file + fresh manifest -> PUBLISH", ok and rc["baseline_mode"] == "CURRENT_SLATE",
              f"{ok} {errs}")
        ok, errs, rc = validate_game_lines_slate(_lines(nxt, 1), SP, prior_df=_lines(nxt, 3), path=out,
                                                 sport_tokens=tok, slate_facts=_facts(_lines(nxt, 1), nxt, 123, age=4.0))
        check("7b comparable fresh baseline (same 41 events, 3 books -> 1 book) -> REJECT forward collapse",
              (not ok) and rc["reason_code"] == "FORWARD_WINDOW_COLLAPSE", f"{ok} {rc['reason_code']}")

        # 8. receipt binding.
        ok, _, rc = validate_game_lines_slate(sunday, SP, prior_df=prior, path=out, sport_tokens=tok,
                                              slate_facts=_facts(sunday, nxt, 68, sha="deadbeef"))
        check("8a foreign-candidate sha -> REJECT RESPONSE_RECEIPT_MISSING",
              (not ok) and rc["reason_code"] == "RESPONSE_RECEIPT_MISSING" and not rc["receipt_sha_bound"], rc["reason_code"])
        ok, _, rc = validate_game_lines_slate(sunday, SP, prior_df=prior, path=out, sport_tokens=tok,
                                              slate_facts=_facts(sunday, nxt, 68, rows=999))
        check("8b receipt candidate_rows mismatch -> REJECT", (not ok) and rc["reason_code"] == "RESPONSE_RECEIPT_MISSING",
              rc["reason_code"])
        ok, _, rc = validate_game_lines_slate(sunday, SP, prior_df=prior, path=out, sport_tokens=tok,
                                              slate_facts=_facts(sunday, nxt, 68, run_id=""))
        check("8c receipt without run_id -> REJECT", (not ok) and rc["reason_code"] == "RESPONSE_RECEIPT_MISSING",
              rc["reason_code"])

        # 9. provider error.
        ok, _, rc = validate_game_lines_slate(sunday, SP, prior_df=prior, path=out, sport_tokens=tok,
                                              slate_facts=_facts(sunday, nxt, 68, errors=1))
        check("9 provider error -> REJECT", (not ok) and rc["reason_code"] == "CURRENT_SLATE_INCOMPLETE", rc["reason_code"])

        # 10. override scope.
        ok, _, rc = validate_game_lines_slate(sunday, SP, prior_df=prior, path=out, sport_tokens=tok,
                                              slate_facts=None, allow_collapse=True)
        check("10a override + no manifest -> PUBLISH (same as old --allow-collapse)", ok, rc["reason_code"])
        ok, _, rc = validate_game_lines_slate(few, SP, prior_df=prior, path=out, sport_tokens=tok,
                                              slate_facts=_facts(few, nxt, 68), allow_collapse=True)
        check("10b override bypasses coverage", ok, rc["reason_code"])
        badf = _lines(nxt, bpe, bad=True)
        ok, _, rc = validate_game_lines_slate(badf, SP, prior_df=prior, path=out, sport_tokens=tok,
                                              slate_facts=_facts(badf, nxt, 68), allow_collapse=True)
        check("10c override never bypasses structural (non-finite Spread) -> REJECT", not ok, rc["reason_code"])
        ok, _, rc = validate_game_lines_slate(sunday, SP, prior_df=prior, path=out, sport_tokens=tok,
                                              slate_facts=_facts(sunday, nxt, 68, sha="deadbeef"), allow_collapse=True)
        check("10d override never bypasses receipt binding -> REJECT", not ok, rc["reason_code"])

        # 11. structural rejects in CURRENT_SLATE mode.
        ok, _, _ = validate_game_lines_slate(badf, SP, prior_df=prior, path=out, sport_tokens=tok,
                                             slate_facts=_facts(badf, nxt, 68))
        check("11a non-finite Spread -> REJECT", not ok)
        wrong = base / "NBA_Odds.csv"
        ok, errs, _ = validate_game_lines_slate(sunday, SP, prior_df=prior, path=wrong, sport_tokens=tok,
                                                slate_facts=_facts(sunday, nxt, 68))
        check("11b wrong-sport output path -> REJECT", (not ok) and any("sport tokens" in e for e in errs), str(errs))
        regress = _lines(nxt, bpe, ts="2020-01-01 00:00")
        ok, errs, _ = validate_game_lines_slate(regress, SP, prior_df=prior, path=out, sport_tokens=tok,
                                                slate_facts=_facts(regress, nxt, 68))
        check("11c timestamp regression -> REJECT", (not ok) and any("REGRESSION" in e for e in errs), str(errs))
        conflict = sunday.copy()
        dup = conflict.iloc[[0]].copy(); dup["Spread"] = -7.0
        conflict = pd.concat([conflict, dup], ignore_index=True)
        ok, errs, _ = validate_game_lines_slate(conflict, SP, prior_df=prior, path=out, sport_tokens=tok,
                                                slate_facts=_facts(conflict, nxt, 68))
        check("11d conflicting duplicate (same GameID+Book, different Spread) -> REJECT",
              (not ok) and any("CONFLICTING" in e for e in errs), str(errs))
        nocol = sunday.drop(columns=["LastUpdated"])
        ok, errs, rc = validate_game_lines_slate(nocol, SP, prior_df=prior, path=out, sport_tokens=tok,
                                                 slate_facts=_facts(nocol, nxt, 68))
        check("11e missing required column -> REJECT", (not ok) and rc["reason_code"] == "STRUCTURAL_REJECT", rc["reason_code"])

    # 12. other sports unchanged.
    import fetch_game_lines as fgl
    check("12a GAME_LINES_SPEC is NOT slate-aware (NBA/WNBA/MLB/NFL-preseason path unchanged)",
          not GAME_LINES_SPEC.slate_aware and GAME_LINES_SPEC.manifest_max_age_hours == 0.0)
    check("12b only NFL + NCAAF routed to slate-aware game-lines validation",
          fgl.GAME_LINES_SLATE_SPORTS == {"americanfootball_nfl", "americanfootball_ncaaf"}, str(fgl.GAME_LINES_SLATE_SPORTS))
    src = inspect.getsource(fgl.main)
    check("12c non-football branch still calls validate_feed(df, GAME_LINES_SPEC, ...) with the override",
          "validate_feed(df, GAME_LINES_SPEC, prior_df=prior" in src and "allow_collapse=allow_collapse" in src)
    same = [getattr(SP, f) == getattr(GAME_LINES_SPEC, f) for f in
            ("required_cols", "numeric_cols", "timestamp_col", "id_cols", "value_cols", "identity_cols",
             "min_rows", "collapse_ratio")]
    check("12d football slate spec keeps every GAME_LINES_SPEC structural field", all(same), str(same))

    # 13. manifest loader.
    now = datetime(2026, 11, 1, 10, 30, tzinfo=timezone.utc)   # Sunday 05:30 ET (EST, after DST end)
    with tempfile.TemporaryDirectory() as td:
        base = Path(td)
        (base / "data" / "tracking").mkdir(parents=True)
        (base / "data" / "odds").mkdir(parents=True)

        def snap_rows(snap_at, specs):
            return [{"SnapshotAt": snap_at, "Sport": "NCAAF", "Date": d, "Time": t, "Away": "A", "Home": "H",
                     "Book": b, "GameID": g, "Spread": -3.5, "LastUpdated": "x"} for (g, d, t, b) in specs]
        older = snap_rows("2026-10-30T05:30:10-07:00", [("old1", "2026-11-07", "12:00", "FanDuel")])
        latest = snap_rows("2026-10-31T05:30:13-07:00", [
            ("sat1", "2026-10-31", "12:00", "FanDuel"), ("sat1", "2026-10-31", "12:00", "DraftKings"),  # played
            ("late", "2026-11-01", "01:30", "FanDuel"),          # West-coast late game, kicked off before now
            ("soon", "2026-11-01", "05:45", "FanDuel"),          # inside 30-min grace
            ("tue1", "2026-11-03", "19:00", "FanDuel"), ("tue1", "2026-11-03", "19:00", "DraftKings"),
            ("sat2", "2026-11-07", "15:30", "FanDuel"),
            ("far", "2027-06-01", "12:00", "FanDuel"),           # beyond --days window
        ])
        pd.DataFrame(older + latest).to_csv(base / "data/tracking/NCAAF_LineMovementHistory.csv", index=False)
        # a CFBD-style odds artifact with different events must NOT feed the manifest
        pd.DataFrame([{"Date": "2026-11-07", "Time": "3:30 PM", "Away": "X", "Home": "Y", "GameID": "cfbd999",
                       "Book": "CFBD consensus"}]).to_csv(base / "data/odds/NCAAF_Odds.csv", index=False)
        ids, info = fgl._eligible_line_events("americanfootball_ncaaf", 130, now, base_dir=base)
        check("13a loader: latest snapshot only; played / in-grace / out-of-window excluded",
              ids == {"tue1", "sat2"}, f"{sorted(ids)} {info}")
        check("13b loader: manifest rows counted on eligible events (3) and snapshot age computed",
              info["event_rows"] == 3 and info["age_hours"] is not None and 21.9 < info["age_hours"] < 22.1, str(info))
        check("13c loader: source is the line-movement history, never the odds artifact or candidate",
              info["source"] == "data/tracking/NCAAF_LineMovementHistory.csv" and "cfbd999" not in ids, str(info))
        ids7, _ = fgl._eligible_line_events("americanfootball_ncaaf", 3, now, base_dir=base)
        check("13d loader: window honors --days (3 days keeps Tuesday, drops next Saturday)", ids7 == {"tue1"}, str(ids7))
        ids_nfl, info_nfl = fgl._eligible_line_events("americanfootball_nfl", 130, now, base_dir=base)
        check("13e loader: missing history file -> empty manifest with reason", (not ids_nfl) and info_nfl["reason"],
              str(info_nfl))

        # 14. loader -> validator, Sunday shape.
        cand = _lines(["tue1", "sat2"], [2, 1])
        prior_sat = pd.concat([_lines([f"p{i}" for i in range(10)], 2, date="2026-10-31", ts="2026-10-31 08:00"),
                               _lines(["tue1", "sat2"], [2, 1], ts="2026-10-31 08:00")], ignore_index=True)
        facts = {"run_id": "e2e", "sport": "americanfootball_ncaaf", "candidate_sha256": candidate_sha256(cand),
                 "candidate_rows": len(cand), "provider_errors": 0, "eligible_event_ids": sorted(ids),
                 "manifest_age_hours": info["age_hours"], "manifest_event_rows": info["event_rows"]}
        out = base / "data/odds/NCAAF_Odds.csv"
        ok, errs, rc = validate_game_lines_slate(cand, SP, prior_df=prior_sat, path=out, sport_tokens=("NCAAF",),
                                                 slate_facts=facts)
        old_ok, _ = validate_feed(cand, GAME_LINES_SPEC, prior_df=prior_sat, path=out, sport_tokens=("NCAAF",))
        check("14 end-to-end: 3 rows vs prior 23 publishes via manifest (old rule rejected it)",
              ok and not old_ok and rc["reason_code"] == "CURRENT_SLATE_COMPLETE", f"{ok} {errs} old={old_ok}")

    n_ok = sum(1 for _, c in _results if c)
    n_fail = len(_results) - n_ok
    print("=" * 64)
    print(f"QC: GAME-LINES SLATE-AWARE VALIDATION -- {n_ok} ok, {n_fail} FAIL")
    print("=" * 64)
    return 1 if n_fail else 0


if __name__ == "__main__":
    raise SystemExit(main())
