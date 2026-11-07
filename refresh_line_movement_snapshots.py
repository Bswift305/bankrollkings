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
import os
import subprocess
import sys
from pathlib import Path

from services import run_receipts
from services.run_outcomes import (BENIGN_LINES_NONPUBLISH, RUN_RECEIPT_MISMATCH, RUN_RECEIPT_MISSING,
                                   governed_lines_nonpublish)

BASE_DIR = Path(__file__).parent.resolve()

# (label, command, timeout, Odds API sport key whose fetch receipt proves the outcome)
STEPS = [
    ("MLB game lines", [sys.executable, "fetch_mlb_game_lines.py", "--days", "3"], 240, "baseball_mlb"),
    ("WNBA game lines", [sys.executable, "fetch_wnba_game_lines.py", "--days", "5"], 240, "basketball_wnba"),
]

# The ONLY benign non-zero exit: a GOVERNED no-game result (services.run_outcomes.BENIGN_LINES_NONPUBLISH =
# NO_GAMES_SCHEDULED, honoured only when this run's receipt names a schedule contract listed in
# GOVERNED_SCHEDULE_CONTRACTS -- none is governed today). NO_ACTIVE_EVENTS (the provider listed zero events)
# is a FAILURE: a zero-event provider answer is not a schedule contract (owner governed-only rule). Exit
# code 1 alone cannot distinguish a benign cause from a provider error, a validation reject, a cost-receipt
# failure, a publish failure or SCHEDULE_UNAVAILABLE -- so without governed proof a non-zero exit is a
# FAILURE, never "OK".
BENIGN_RECEIPT_OUTCOMES = BENIGN_LINES_NONPUBLISH


def _receipt_path(sport: str) -> Path:
    return BASE_DIR / "data" / "tracking" / f"_last_game_lines_fetch_{sport}.json"


def classify_step(returncode: int, sport: str, run_token: str) -> tuple[str, str]:
    """Return (status, detail) with status in {OK, SKIPPED_<benign outcome>, FAILED, RUN_RECEIPT_MISSING,
    RUN_RECEIPT_MISMATCH}.

    Receipt-identity contract (2026-11-04, extended to this runner): the receipt counts as THIS invocation's
    only when it carries THIS invocation's run token (passed to the child in run_receipts.STAGE_RUN_ENV and
    stamped by fetch_game_lines). File mtime is never consulted -- on a coarse-timestamp filesystem two
    successive writes can share an mtime, and a newer file can be another writer's. Missing / unreadable ->
    RUN_RECEIPT_MISSING; another (or no) token -> RUN_RECEIPT_MISMATCH. Both are failures, never OK."""
    path = _receipt_path(sport)
    try:
        receipt = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return RUN_RECEIPT_MISSING, f"exit {returncode}, no readable receipt for this invocation ({path.name})"
    if not isinstance(receipt, dict):
        return RUN_RECEIPT_MISSING, f"exit {returncode}, receipt is not an object"
    if not run_token or receipt.get("stage_run_id") != run_token:
        return RUN_RECEIPT_MISMATCH, (f"exit {returncode}, the receipt carries token "
                                      f"{str(receipt.get('stage_run_id'))[:8]!r}, not this invocation's")
    if returncode == 0:
        # OK only on positive proof (gate #2 finding #14): this run's receipt must say outcome == UPDATED AND
        # exit_code == 0. An absent / None / other outcome, or a missing or different exit_code, is FAILED --
        # a malformed or partial receipt carrying this run's token never reads as a publish.
        if receipt.get("outcome") == "UPDATED" and receipt.get("exit_code") == 0:
            return "OK", "published"
        return "FAILED", (f"exit 0 but this run's receipt does not prove a publish "
                          f"(outcome={receipt.get('outcome')!r}, exit_code={receipt.get('exit_code')!r})")
    if returncode == 1 and receipt.get("exit_code") == 1 \
            and receipt.get("outcome") in BENIGN_RECEIPT_OUTCOMES \
            and governed_lines_nonpublish(receipt):
        return f"SKIPPED_{receipt.get('outcome')}", (f"{receipt.get('outcome')} (proven by this run's receipt, "
                                                     f"schedule_contract={receipt.get('schedule_contract')})")
    if receipt:
        return "FAILED", f"exit {returncode}, outcome={receipt.get('outcome')}"
    return "FAILED", f"exit {returncode}, this invocation's receipt proves no benign cause"


def main() -> int:
    failures: list[tuple[str, str]] = []
    print("=" * 60)
    print("BANKROLL KINGS - LINE MOVEMENT SNAPSHOT CAPTURE")
    print("=" * 60)
    for label, command, timeout, sport in STEPS:
        print(f"\n[{label}]")
        run_token = run_receipts.new_token()          # identifies THIS invocation's receipt (never mtime)
        child_env = dict(os.environ)
        child_env[run_receipts.STAGE_RUN_ENV] = run_token
        try:
            result = subprocess.run(command, cwd=BASE_DIR, timeout=timeout, env=child_env)
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
        status, detail = classify_step(result.returncode, sport, run_token)
        if status != "OK" and not status.startswith("SKIPPED_"):
            failures.append((label, f"{status}: {detail}" if status != "FAILED" else detail))
            print(f"FAILED ({status}): {detail}")
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
