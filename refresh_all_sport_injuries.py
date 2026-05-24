"""
Refresh injury files across all supported sports.

NBA continues to use the official NBA injury pipeline.
WNBA/NFL/MLB use the ESPN-based cross-sport fetcher.
NCAAF currently preserves manual/last-good data until a live endpoint is added.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


BASE_DIR = Path(__file__).parent.resolve()

STEPS = [
    ("NBA injuries", [sys.executable, "fetch_injuries.py"]),
    ("WNBA injuries", [sys.executable, "fetch_wnba_injuries.py"]),
    ("NFL injuries", [sys.executable, "fetch_nfl_injuries.py"]),
    ("MLB injuries", [sys.executable, "fetch_mlb_injuries.py"]),
    ("NCAAF injuries", [sys.executable, "fetch_ncaaf_injuries.py"]),
]


def main() -> int:
    failures = []
    print("=" * 70)
    print("BANKROLL KINGS - ALL-SPORT INJURY REFRESH")
    print("=" * 70)
    for label, command in STEPS:
        print(f"\n[{label}]")
        try:
            result = subprocess.run(command, cwd=BASE_DIR, check=False)
        except Exception as exc:
            failures.append((label, str(exc)))
            print(f"FAILED: {exc}")
            continue
        if result.returncode != 0:
            failures.append((label, f"exit {result.returncode}"))
            print(f"FAILED: exit {result.returncode}")
        else:
            print("OK")
    print("\n" + "=" * 70)
    if failures:
        print(f"Completed with {len(failures)} failure(s):")
        for label, message in failures:
            print(f"- {label}: {message}")
        return 1
    print("All sport injury refresh steps completed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
