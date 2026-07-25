"""Frequent intraday capture of MLB + WNBA game-line snapshots.

Why this exists: the daily refresh captures game lines ONCE per day, so an in-season game
(on the board ~1-2 days before it's played) only ever gets 1-2 snapshots -- not enough for
an open->current movement read, which is why Market Movers had no data. Running this every
few hours lets real movement accumulate across a game's life.

Scope is deliberate: only the two in-season sports whose games turn over daily and whose
lines move intraday. Football (NFL/NCAAF) stays on the daily cadence -- its advance lines
are weeks out, move slowly, and accrue plenty of depth over that long window on one/day.

Lightweight and memory-safe: each step is an Odds API call + a CSV append via
fetch_game_lines (no `app` import, no heavy archiving), so it is safe to run often on the
single-worker box.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

BASE_DIR = Path(__file__).parent.resolve()

STEPS = [
    ("MLB game lines", [sys.executable, "fetch_mlb_game_lines.py", "--days", "3"], 240),
    ("WNBA game lines", [sys.executable, "fetch_wnba_game_lines.py", "--days", "5"], 240),
]


def main() -> int:
    failures: list[tuple[str, str]] = []
    print("=" * 60)
    print("BANKROLL KINGS - LINE MOVEMENT SNAPSHOT CAPTURE")
    print("=" * 60)
    for label, command, timeout in STEPS:
        print(f"\n[{label}]")
        try:
            result = subprocess.run(command, cwd=BASE_DIR, timeout=timeout)
        except subprocess.TimeoutExpired:
            failures.append((label, "timeout"))
            print("FAILED: timeout")
            continue
        except Exception as exc:
            failures.append((label, str(exc)))
            print(f"FAILED: {exc}")
            continue
        # fetch_game_lines returns 1 when no new rows were fetched (existing CSV preserved) —
        # that is a benign "nothing to add", not a failure.
        if result.returncode not in (0, 1):
            failures.append((label, f"exit {result.returncode}"))
            print(f"FAILED: exit {result.returncode}")
        else:
            print("OK")

    print("\n" + "=" * 60)
    if failures:
        print(f"Completed with {len(failures)} failure(s):")
        for label, message in failures:
            print(f"- {label}: {message}")
        return 1
    print("All line-movement snapshots captured.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
