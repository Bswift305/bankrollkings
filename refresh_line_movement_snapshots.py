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

from services.run_outcomes import EXIT_HARD_FAILURE, STEP_FAIL, STEP_PASS, classify_step_exit

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
            result = subprocess.run(command, cwd=BASE_DIR, timeout=timeout, capture_output=True, text=True)
        except subprocess.TimeoutExpired:
            failures.append((label, "timeout"))
            print("FAILED: timeout")
            continue
        except Exception as exc:
            failures.append((label, str(exc)))
            print(f"FAILED: {exc}")
            continue
        output = "\n".join(part for part in (result.stdout, result.stderr) if part)
        if output:
            print(output.rstrip())   # keep the child's output in the journal (captured only to classify it)
        # fetch_game_lines returns 1 for EVERY non-publish: provider error, empty rows, validation reject,
        # cost-receipt failure, publish failure. Owner decision 2026-11-04: exit 1 is benign ONLY with a
        # GOVERNED SKIPPED_OFF_SEASON / NO_GAMES_SCHEDULED claim; otherwise it is a FAILURE, never "OK".
        # (The NBA v6 branch replaces this with token-identified receipts; keep the two consistent.)
        status, reason = classify_step_exit(result.returncode, output)
        if status == STEP_FAIL:
            failures.append((label, f"exit {result.returncode} ({reason})"))
            print(f"FAILED: exit {result.returncode} ({reason})")
        elif status == STEP_PASS:
            print("OK")
        else:
            print(f"OK ({status} {reason})")

    print("\n" + "=" * 60)
    if failures:
        print(f"Completed with {len(failures)} failure(s):")
        for label, message in failures:
            print(f"- {label}: {message}")
        # HARD failure -> >=2. Exit 1 is reserved for benign no-new-rows, and prod bk-linemove.service has
        # SuccessExitStatus=1, so returning 1 here would read as SUCCESS to systemd.
        return EXIT_HARD_FAILURE
    print("All line-movement snapshots captured.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
