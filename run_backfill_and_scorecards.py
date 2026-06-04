from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent
MLB_HISTORY_PATH = BASE_DIR / "data" / "historical" / "MLB_Props_History.csv"
NFL_HISTORY_PATH = BASE_DIR / "data" / "historical" / "NFL_Props_History.csv"


def _run(label: str, command: list[str], *, required: bool = True) -> bool:
    print()
    print(f"[STEP] {label}")
    print(" ".join(command))
    result = subprocess.run(command, cwd=BASE_DIR)
    if result.returncode == 0:
        print(f"[PASS] {label}")
        return True
    print(f"[FAIL] {label} exited with code {result.returncode}")
    return not required


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run historical calibration builders and MLB/NFL launch scorecards."
    )
    parser.add_argument("--skip-backfill", action="store_true", help="Run scorecards only.")
    parser.add_argument("--skip-scorecards", action="store_true", help="Run backfills only.")
    parser.add_argument("--nfl-season", action="append", type=int, help="NFL season to include. Can be repeated.")
    parser.add_argument(
        "--mlb-fallback-date",
        default="",
        help="Optional date for MLB prop files that do not carry a game date. Prefer real MLB_Props_History.csv instead.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    ok = True

    if not args.skip_backfill:
        if MLB_HISTORY_PATH.exists() or args.mlb_fallback_date:
            mlb_cmd = [sys.executable, "build_mlb_historical_calibration.py"]
            if args.mlb_fallback_date:
                mlb_cmd.extend(["--fallback-date", args.mlb_fallback_date])
            ok = _run("MLB historical calibration", mlb_cmd, required=False) and ok
        else:
            print()
            print("[SKIP] MLB historical calibration")
            print("Missing data/historical/MLB_Props_History.csv. Add dated MLB prop history or pass --mlb-fallback-date for a smoke run.")

        if NFL_HISTORY_PATH.exists():
            nfl_cmd = [sys.executable, "build_nfl_historical_calibration.py"]
            for season in args.nfl_season or []:
                nfl_cmd.extend(["--season", str(season)])
            ok = _run("NFL historical calibration", nfl_cmd, required=False) and ok
        else:
            print()
            print("[SKIP] NFL historical calibration")
            print("Missing data/historical/NFL_Props_History.csv.")

    if not args.skip_scorecards:
        ok = _run("MLB 99 scorecard", [sys.executable, "run_mlb_99_scorecard.py"], required=False) and ok
        ok = _run("NFL 99 scorecard", [sys.executable, "run_nfl_99_scorecard.py"], required=False) and ok

    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
