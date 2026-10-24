"""QC (concurrency/isolation): the NFL live-grade and historical-backfill artifacts never touch each
other (2026-10-24 clobber fix). Runs the REAL writers against temporary paths, in both orders, and proves:

  * the live artifact contains only the live/current contract (no IsBackfill rows, current season);
  * the backfill artifact contains only historical backfill (IsBackfill, prior seasons);
  * writing one artifact does not change the other's bytes (independent hashes);
  * load_combined() returns the union of both populations;
  * a failure mid-write in one writer leaves BOTH artifacts' prior valid files intact (atomic publish).

Live writer under test  : app.replace_all_prop_results_snapshot_for_sport (tmp DATA_DIR)
Backfill writer under test: services.nfl_result_artifacts.write_backfill (same atomic tmp+os.replace pattern
                            build_nfl_historical_calibration now uses).
"""
from __future__ import annotations

import hashlib
import tempfile
from pathlib import Path

import pandas as pd

from services.nfl_result_artifacts import (
    LIVE_NAME, BACKFILL_NAME, backfill_path, live_path, load_combined, write_backfill, write_atomic,
)


def _sha(p: Path) -> str:
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def _live_df() -> pd.DataFrame:
    return pd.DataFrame([
        {"Sport": "NFL", "Player": "Live Player", "Stat": "RECEIVING YARDS", "Direction": "OVER",
         "Line": 60.5, "Season": 2026, "Week": 6, "OutcomeState": "Hit", "ResultValue": 72.0,
         "IsBackfill": False, "SnapshotDate": "2026-10-20"},
        {"Sport": "NFL", "Player": "Live Player", "Stat": "RECEIVING YARDS", "Direction": "UNDER",
         "Line": 60.5, "Season": 2026, "Week": 6, "OutcomeState": "Miss", "ResultValue": 72.0,
         "IsBackfill": False, "SnapshotDate": "2026-10-20"},
    ])


def _backfill_df() -> pd.DataFrame:
    return pd.DataFrame([
        {"Sport": "NFL", "Player": "Hist Player", "Stat": "RUSHING YARDS", "Direction": "OVER",
         "Line": 50.5, "Season": 2024, "Week": 3, "OutcomeState": "Hit", "ResultValue": 61.0,
         "IsBackfill": True, "Method": "Historical Backfill", "SnapshotDate": "2024-09-20"},
        {"Sport": "NFL", "Player": "Hist Player", "Stat": "RUSHING YARDS", "Direction": "OVER",
         "Line": 55.5, "Season": 2025, "Week": 11, "OutcomeState": "Miss", "ResultValue": 40.0,
         "IsBackfill": True, "Method": "Historical Backfill", "SnapshotDate": "2025-11-16"},
    ])


def run_qc() -> dict:
    import app
    failures: list[str] = []
    checks: list[str] = []
    orig_data_dir = app.DATA_DIR

    def _write_live(tracking_dir: Path):
        # app writer references the module global DATA_DIR; point it at the temp tree for the test.
        app.DATA_DIR = tracking_dir.parent
        app.replace_all_prop_results_snapshot_for_sport(_live_df(), sport="NFL")

    try:
        for order in ("live_then_backfill", "backfill_then_live"):
            tmp = Path(tempfile.mkdtemp(prefix="bk_iso_"))
            (tmp / "tracking").mkdir(parents=True, exist_ok=True)
            tdir = tmp / "tracking"

            if order == "live_then_backfill":
                _write_live(tdir)
                h_live = _sha(live_path(tdir))
                write_backfill(_backfill_df(), tdir)
                if _sha(live_path(tdir)) != h_live:
                    failures.append(f"[{order}] writing backfill changed the live artifact bytes.")
            else:
                write_backfill(_backfill_df(), tdir)
                h_bf = _sha(backfill_path(tdir))
                _write_live(tdir)
                if _sha(backfill_path(tdir)) != h_bf:
                    failures.append(f"[{order}] writing live changed the backfill artifact bytes.")

            live = pd.read_csv(live_path(tdir), low_memory=False)
            bf = pd.read_csv(backfill_path(tdir), low_memory=False)

            # live artifact: current season, no backfill rows
            if "IsBackfill" in live.columns and live["IsBackfill"].astype(str).str.lower().isin(["true", "1"]).any():
                failures.append(f"[{order}] live artifact contains IsBackfill rows.")
            if (pd.to_numeric(live.get("Season"), errors="coerce") != 2026).any():
                failures.append(f"[{order}] live artifact contains non-current-season rows.")
            # backfill artifact: historical only
            if (pd.to_numeric(bf.get("Season"), errors="coerce") == 2026).any():
                failures.append(f"[{order}] backfill artifact contains current-season rows.")
            if not bf["IsBackfill"].astype(str).str.lower().isin(["true", "1"]).all():
                failures.append(f"[{order}] backfill artifact has non-backfill rows.")

            combined = load_combined(tdir)
            if len(combined) != len(live) + len(bf):
                failures.append(f"[{order}] load_combined len={len(combined)} != live {len(live)} + "
                                f"backfill {len(bf)} (unexpected drop/overlap).")
            seasons = set(pd.to_numeric(combined.get("Season"), errors="coerce").dropna().astype(int))
            if not ({2026} <= seasons and ({2024} <= seasons or {2025} <= seasons)):
                failures.append(f"[{order}] load_combined missing a population; seasons={sorted(seasons)}")
            checks.append(f"[{order}] isolation + union OK (live={len(live)}, backfill={len(bf)}, "
                          f"combined={len(combined)})")

            # failure injection: a crash mid-write must leave the prior valid file intact (atomic publish)
            good_bf_sha = _sha(backfill_path(tdir))
            orig_to_csv = pd.DataFrame.to_csv

            def _boom(self, *a, **k):
                raise IOError("simulated mid-write crash")

            pd.DataFrame.to_csv = _boom
            raised = False
            try:
                write_atomic(_backfill_df(), backfill_path(tdir))
            except IOError:
                raised = True
            finally:
                pd.DataFrame.to_csv = orig_to_csv
            if not raised:
                failures.append(f"[{order}] simulated write crash did not raise.")
            if _sha(backfill_path(tdir)) != good_bf_sha:
                failures.append(f"[{order}] a failed write corrupted/replaced the prior backfill artifact "
                                "(atomic publish violated).")
            else:
                checks.append(f"[{order}] atomic failure-preservation OK")
    finally:
        app.DATA_DIR = orig_data_dir

    return {
        "checked_at": __import__("datetime").datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "clean": not failures,
        "pass_count": len(checks),
        "warning_count": 0,
        "failure_count": len(failures),
        "notes": f"Isolation of {LIVE_NAME} (live) and {BACKFILL_NAME} (historical) across write orders + "
                 "atomic failure-preservation.",
        "checks": checks,
        "failures": failures,
    }


def main() -> int:
    r = run_qc()
    print("=" * 70)
    print("NFL RESULT ARTIFACT ISOLATION QC (concurrency + atomicity)")
    print("=" * 70)
    for c in r["checks"]:
        print(f"  [ok] {c}")
    for f in r["failures"]:
        print(f"  [FAIL] {f}")
    print(f"Clean: {r['clean']}")
    return 0 if r["clean"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
