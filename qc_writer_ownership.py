"""QC: single-writer ownership of the NFL graded prop-result artifacts (2026-10-24 clobber fix).

Fails if two registered pipelines target the same authoritative path, or if the code constants drift back
to sharing NFL_AllPropResults.csv between the in-season grader and the historical backfill. This is the
regression guard for the clobber: build_nfl_historical_calibration must write the BACKFILL file, and
normalize_result_metadata's NFL raw target must be the BACKFILL file -- never the live grader's file.

Deliberately light (no app import): it inspects the registry + the two modules that caused the clobber.
"""
from __future__ import annotations

from services.nfl_result_artifacts import WRITER_OWNERSHIP, LIVE_NAME, BACKFILL_NAME


def run_qc() -> dict:
    failures: list[str] = []
    checks: list[str] = []

    # 1. The registry itself must not map two pipelines onto one authoritative path.
    seen: dict[str, str] = {}
    for path_name, owner in WRITER_OWNERSHIP.items():
        checks.append(f"{path_name} -> {owner}")
    # invert: owner collisions are fine (one owner, many files); PATH collisions are the bug.
    # A dict can't hold duplicate keys, so assert the two expected authoritative files are distinct and
    # present, and that the live + backfill files are not the same name.
    if LIVE_NAME == BACKFILL_NAME:
        failures.append("LIVE_NAME == BACKFILL_NAME: the two artifacts share a path (the clobber).")
    for required in (LIVE_NAME, BACKFILL_NAME):
        if required not in WRITER_OWNERSHIP:
            failures.append(f"registry missing an owner for {required}")
    if WRITER_OWNERSHIP.get(LIVE_NAME) == WRITER_OWNERSHIP.get(BACKFILL_NAME):
        failures.append("live and backfill artifacts are registered to the SAME owner -- expected "
                        "distinct single writers.")

    # 2. The historical-backfill writer must NOT target the live file.
    try:
        import build_nfl_historical_calibration as bfc
        out_name = bfc.OUTPUT_PATH.name
        checks.append(f"build_nfl_historical_calibration.OUTPUT_PATH = {out_name}")
        if out_name == LIVE_NAME:
            failures.append(f"build_nfl_historical_calibration writes {LIVE_NAME} (the live grader's file) "
                            "-- this is the clobber; it must write the backfill file.")
        elif out_name != BACKFILL_NAME:
            failures.append(f"build_nfl_historical_calibration writes unexpected {out_name!r}; expected "
                            f"{BACKFILL_NAME}.")
    except Exception as exc:
        failures.append(f"could not inspect build_nfl_historical_calibration: {exc}")

    # 3. normalize_result_metadata's NFL raw target must be the backfill file, never the live file.
    try:
        import normalize_result_metadata as nrm
        nfl_raw_targets = [str(p.name) for sport, p, _ in nrm.TARGETS
                           if sport == "NFL" and "AllPropResults" in p.name
                           and "Scored" not in p.name]
        checks.append(f"normalize NFL raw targets = {nfl_raw_targets}")
        if LIVE_NAME in nfl_raw_targets:
            failures.append(f"normalize_result_metadata stamps {LIVE_NAME} (the live grader's file) with a "
                            "backfill model version -- it must target the backfill file.")
        if BACKFILL_NAME not in nfl_raw_targets:
            failures.append(f"normalize_result_metadata does not target {BACKFILL_NAME} for NFL.")
    except Exception as exc:
        failures.append(f"could not inspect normalize_result_metadata: {exc}")

    return {
        "checked_at": __import__("datetime").datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "clean": not failures,
        "pass_count": len(checks),
        "warning_count": 0,
        "failure_count": len(failures),
        "notes": "Single-writer-per-file ownership for NFL graded result artifacts.",
        "checks": checks,
        "failures": failures,
    }


def main() -> int:
    r = run_qc()
    print("=" * 64)
    print("WRITER OWNERSHIP QC -- NFL graded prop-result artifacts")
    print("=" * 64)
    for c in r["checks"]:
        print(f"  [ok] {c}")
    for f in r["failures"]:
        print(f"  [FAIL] {f}")
    print(f"Clean: {r['clean']}")
    return 0 if r["clean"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
