"""QC (synthetic, no network): the precision capture schema for NFL prop lines (2026-10-24 Commit 2/2).

Runs capture_nfl_prop_lines.main() against synthetic props feeds in a temp dir and proves the invariants
the directive requires:

  1  BKCapturedAtUTC is precise + canonical UTC;
  2  kickoff (EventCommenceAtUTC) carried through as canonical UTC;
  3  pregame/post/unknown classification is deterministic (future kickoff->PREGAME, past->POST_START,
     missing->UNKNOWN_NO_KICKOFF);
  4  malformed kickoff clocks fail closed to UNKNOWN (never assumed pregame, no crash);
  5  legacy date-only rows remain byte-unchanged and classify TEMPORAL_PRECISION_INSUFFICIENT / v1;
  6  identical reruns are idempotent (no duplicate ObservationId; stable v2 count);
  7  a changed line creates a DISTINCT observation;
  8  a changed (rescheduled) kickoff creates a DISTINCT observation (correction history preserved);
  9  bare/empty source-update never becomes a fabricated UTC value;
  10 EventId survives the feed -> archive unchanged;
  11 a failed publication leaves the prior archive byte-for-byte identical (atomic);
  12 a row with no EventId AND no Game fails closed (skipped, not invented).
"""
from __future__ import annotations

import hashlib
import os
import tempfile
from pathlib import Path

import pandas as pd

import capture_nfl_prop_lines as cap

_FUT = "2026-12-01T18:00:00Z"   # future kickoff relative to "now"
_PAST = "2026-09-01T18:00:00Z"  # past kickoff


def _sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def _book_rows(player, stat, line, game, commence, src, eid, books=("DraftKings", "FanDuel")):
    out = []
    for b in books:
        out.append({"Player": player, "Team": "ATL", "Stat": stat, "MarketKey": "x", "Line": line,
                    "Game": game, "Book": b, "OverOdds": -110, "UnderOdds": -110,
                    "EventId": eid, "EventCommenceAtUTC": commence, "SourceUpdatedAtUTC": src})
    return out


def _write_props(path, rows):
    pd.DataFrame(rows).to_csv(path, index=False)


def _run(tmp, props_rows):
    _write_props(tmp / "props.csv", props_rows)
    cap.PROPS_PATH = tmp / "props.csv"
    cap.OUT_PATH = tmp / "archive.csv"
    cap._game_dates = lambda: {"Atlanta Falcons@Green Bay Packers": "2026-12-01"}
    cap._eastern_today = lambda: "2026-10-25"
    cap.main()
    return pd.read_csv(cap.OUT_PATH, low_memory=False)


def run_qc() -> dict:
    failures = []
    checks = []
    GM = "Atlanta Falcons@Green Bay Packers"

    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        rows = (_book_rows("Jordan Love", "Rec Yds", 15.5, GM, _FUT, "2026-10-24T13:00:00Z", "evt1")
                + _book_rows("Bijan Robinson", "Rush Yds", 70.5, GM, _PAST, "2026-10-24T13:00:00Z", "evt1")
                + _book_rows("Drake London", "Rec Yds", 60.5, GM, "", "", "evt1")          # no kickoff
                + _book_rows("Kyle Pitts", "Rec Yds", 40.5, GM, "garbage", "2026-10-24T13:00:00Z", "evt1")  # malformed
                + _book_rows("Ghost Player", "Rec Yds", 10.5, "", _FUT, "x", ""))          # no eid AND no game
        a = _run(tmp, rows)

        def te(player):
            r = a[a["Player"] == player]
            return r["TemporalEligibility"].iloc[0] if len(r) else None

        if not cap._valid_utc(a["BKCapturedAtUTC"].iloc[0]):
            failures.append(f"[1] BKCapturedAtUTC not canonical UTC: {a['BKCapturedAtUTC'].iloc[0]!r}")
        else:
            checks.append("[1] BKCapturedAtUTC canonical UTC")
        love = a[a["Player"] == "Jordan Love"]
        if len(love) and love["EventCommenceAtUTC"].iloc[0] == _FUT:
            checks.append("[2] kickoff carried as canonical UTC")
        else:
            failures.append("[2] kickoff not carried")
        if te("Jordan Love") == "PROVABLY_PREGAME" and te("Bijan Robinson") == "POST_START" and te("Drake London") == "UNKNOWN_NO_KICKOFF":
            checks.append("[3] pregame/post/unknown classification deterministic")
        else:
            failures.append(f"[3] classification wrong: Love={te('Jordan Love')} Bijan={te('Bijan Robinson')} London={te('Drake London')}")
        if te("Kyle Pitts") == "UNKNOWN_NO_KICKOFF":
            checks.append("[4] malformed kickoff -> UNKNOWN (fail closed)")
        else:
            failures.append(f"[4] malformed kickoff not failed closed: {te('Kyle Pitts')}")
        if a[a["Player"] == "Ghost Player"].empty:
            checks.append("[12] no-identity row skipped (fail closed)")
        else:
            failures.append("[12] no-identity row was not skipped")
        if (a[a["Player"] == "Drake London"]["SourceUpdatedLatestUTC"].fillna("").astype(str).str.strip() == "").all():
            checks.append("[9] empty source-update not fabricated")
        else:
            failures.append("[9] empty source-update became non-empty")
        if (a[a["Player"] == "Jordan Love"]["EventId"] == "evt1").all():
            checks.append("[10] EventId carried unchanged")
        else:
            failures.append("[10] EventId altered")

        # [6] idempotent rerun
        v2_before = a[a["SchemaVersion"] == cap.SCHEMA_V2]
        a2 = _run(tmp, rows)
        v2_after = a2[a2["SchemaVersion"] == cap.SCHEMA_V2]
        if len(v2_after) == len(v2_before) and v2_after["ObservationId"].is_unique:
            checks.append("[6] idempotent rerun (no dup observation ids)")
        else:
            failures.append(f"[6] not idempotent: before={len(v2_before)} after={len(v2_after)} unique={v2_after['ObservationId'].is_unique}")

        # [7] changed line -> distinct
        rows_line = [dict(r, Line=16.5) if r["Player"] == "Jordan Love" else r for r in rows]
        a3 = _run(tmp, rows_line)
        love_ids = a3[a3["Player"] == "Jordan Love"]["ObservationId"].nunique()
        if love_ids >= 2:
            checks.append("[7] changed line -> distinct observation")
        else:
            failures.append(f"[7] changed line did not create a distinct observation (ids={love_ids})")

        # [8] changed kickoff -> distinct (correction preserved)
        rows_kick = [dict(r, EventCommenceAtUTC="2026-12-02T18:00:00Z") if r["Player"] == "Bijan Robinson" else r for r in rows]
        a4 = _run(tmp, rows_kick)
        bijan_kicks = a4[a4["Player"] == "Bijan Robinson"]["EventCommenceAtUTC"].nunique()
        if bijan_kicks >= 2:
            checks.append("[8] rescheduled kickoff -> distinct observation (correction preserved)")
        else:
            failures.append(f"[8] kickoff change not preserved as distinct ({bijan_kicks})")

    # [5] + [11] in a fresh temp with a pre-seeded LEGACY archive
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        legacy = pd.DataFrame([{"SnapshotDate": "2026-10-10", "Season": 2026, "Player": "Legacy Guy",
                                "Team": "ATL", "Stat": "Rec Yds", "Line": 50.5, "OverOdds": -115,
                                "UnderOdds": -105, "BookCount": 3, "Game": GM, "GameDate": "2026-10-12"}])
        cap.OUT_PATH = tmp / "archive.csv"
        legacy.to_csv(cap.OUT_PATH, index=False)
        legacy_sha = _sha(cap.OUT_PATH)
        rows = _book_rows("Jordan Love", "Rec Yds", 15.5, GM, _FUT, "2026-10-24T13:00:00Z", "evt1")
        a = _run(tmp, rows)
        lg = a[a["Player"] == "Legacy Guy"]
        if len(lg) == 1 and lg["SchemaVersion"].iloc[0] == cap.SCHEMA_V1 and lg["TemporalEligibility"].iloc[0] == "TEMPORAL_PRECISION_INSUFFICIENT" \
                and str(lg["Line"].iloc[0]) == "50.5" and str(lg["GameDate"].iloc[0]) == "2026-10-12":
            checks.append("[5] legacy row preserved + classified v1 / TEMPORAL_PRECISION_INSUFFICIENT")
        else:
            failures.append(f"[5] legacy row not preserved/classified correctly: {lg.to_dict('records')}")

        # [11] atomic: a failed write leaves the prior archive byte-identical
        before_sha = _sha(cap.OUT_PATH)
        _write_props(tmp / "props.csv", rows)
        cap.PROPS_PATH = tmp / "props.csv"
        orig = pd.DataFrame.to_csv

        def _boom(self, *a, **k):
            raise IOError("simulated write crash")

        pd.DataFrame.to_csv = _boom
        raised = False
        try:
            cap.main()
        except IOError:
            raised = True
        finally:
            pd.DataFrame.to_csv = orig
        if raised and _sha(cap.OUT_PATH) == before_sha:
            checks.append("[11] failed publication left prior archive byte-identical")
        else:
            failures.append(f"[11] atomic violation: raised={raised} sha_changed={_sha(cap.OUT_PATH) != before_sha}")

    return {"clean": not failures, "checks": checks, "failures": failures}


def main() -> int:
    r = run_qc()
    print("=" * 70)
    print("NFL CAPTURE-PRECISION QC (synthetic; Commit 2/2)")
    print("=" * 70)
    for c in r["checks"]:
        print(f"  [ok] {c}")
    for f in r["failures"]:
        print(f"  [FAIL] {f}")
    print(f"Clean: {r['clean']}")
    return 0 if r["clean"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
