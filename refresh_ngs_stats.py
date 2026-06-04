from __future__ import annotations

import subprocess
import sys
from datetime import datetime


STEPS = [
    (
        "ngs_2025_aggregate",
        [sys.executable, "fetch_ngs_stats.py", "--season", "2025", "--season-types", "REG,POST", "--aggregate"],
        240,
    ),
    (
        "ngs_2025_weekly",
        [sys.executable, "fetch_ngs_stats.py", "--season", "2025", "--season-types", "REG,POST", "--weekly"],
        900,
    ),
]


def main() -> int:
    print("=" * 60)
    print("BANKROLL KINGS - NFL NEXT GEN STATS REFRESH")
    print("=" * 60)
    print(f"Started at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print()
    for label, command, timeout in STEPS:
        started = datetime.now()
        print(f"[STEP] {label} timeout={timeout}s", flush=True)
        try:
            result = subprocess.run(command, timeout=timeout)
        except subprocess.TimeoutExpired:
            elapsed = (datetime.now() - started).total_seconds()
            print(f"[FAIL] {label} timed out after {elapsed:.1f}s", flush=True)
            return 124
        elapsed = (datetime.now() - started).total_seconds()
        if result.returncode != 0:
            print(f"[FAIL] {label} exited with code {result.returncode} after {elapsed:.1f}s", flush=True)
            return result.returncode
        print(f"[PASS] {label} seconds={elapsed:.1f}", flush=True)
        print()
    print("NFL Next Gen Stats refresh completed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
