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

import json
import subprocess
import sys
from pathlib import Path

from services.run_outcomes import BENIGN_LINES_NONPUBLISH

BASE_DIR = Path(__file__).parent.resolve()

# (label, command, timeout, Odds API sport key whose fetch receipt proves the outcome)
STEPS = [
    ("MLB game lines", [sys.executable, "fetch_mlb_game_lines.py", "--days", "3"], 240, "baseball_mlb"),
    ("WNBA game lines", [sys.executable, "fetch_wnba_game_lines.py", "--days", "5"], 240, "basketball_wnba"),
]

# The ONLY benign non-zero exits: a proven no-event / no-game window, proven by a receipt written by THIS
# run (services.run_outcomes.BENIGN_LINES_NONPUBLISH = NO_ACTIVE_EVENTS, NO_GAMES_SCHEDULED). Exit code 1
# alone cannot distinguish that from a provider error, a validation reject, a cost-receipt failure, a
# publish failure or SCHEDULE_UNAVAILABLE (provider empty, no authoritative schedule) -- so without that
# proof a non-zero exit is a FAILURE, never "OK" (2026-11 correction).
BENIGN_RECEIPT_OUTCOMES = BENIGN_LINES_NONPUBLISH


def _receipt_path(sport: str) -> Path:
    return BASE_DIR / "data" / "tracking" / f"_last_game_lines_fetch_{sport}.json"


def _mtime(path: Path) -> float:
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0


def classify_step(returncode: int, sport: str, receipt_mtime_before: float) -> tuple[str, str]:
    """Return (status, detail) with status in {OK, SKIPPED_<benign outcome>, FAILED}."""
    path = _receipt_path(sport)
    fresh = _mtime(path) > receipt_mtime_before
    receipt = None
    if fresh:
        try:
            receipt = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            receipt = None
    if returncode == 0:
        if receipt is not None and receipt.get("outcome") not in (None, "UPDATED"):
            return "FAILED", f"exit 0 but this run's receipt says outcome={receipt.get('outcome')}"
        return "OK", "published"
    if returncode == 1 and receipt and receipt.get("exit_code") == 1 \
            and receipt.get("outcome") in BENIGN_RECEIPT_OUTCOMES:
        return f"SKIPPED_{receipt.get('outcome')}", (f"{receipt.get('outcome')} (proven by this run's receipt)")
    if receipt:
        return "FAILED", f"exit {returncode}, outcome={receipt.get('outcome')}"
    return "FAILED", f"exit {returncode}, no fresh receipt proving a benign cause"


def main() -> int:
    failures: list[tuple[str, str]] = []
    print("=" * 60)
    print("BANKROLL KINGS - LINE MOVEMENT SNAPSHOT CAPTURE")
    print("=" * 60)
    for label, command, timeout, sport in STEPS:
        print(f"\n[{label}]")
        receipt_before = _mtime(_receipt_path(sport))
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
        # fetch_game_lines returns 1 for EVERY non-publish (provider error, validation reject, cost receipt,
        # publish failure, or a genuine zero-event window). Only this run's receipt can prove the benign one.
        status, detail = classify_step(result.returncode, sport, receipt_before)
        if status == "FAILED":
            failures.append((label, detail))
            print(f"FAILED: {detail}")
        elif status.startswith("SKIPPED_"):
            print(f"SKIPPED (benign): {detail}")
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
