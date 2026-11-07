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
from datetime import datetime, timezone
from pathlib import Path

from services import linemove_status, run_receipts
from services.run_outcomes import (BENIGN_LINES_NONPUBLISH, CONFIG_MISSING, EXIT_HARD_FAILURE, EXIT_OK,
                                   RUN_RECEIPT_MISMATCH, RUN_RECEIPT_MISSING, governed_lines_nonpublish,
                                   is_exact_int, typed_hard_failure)

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


def classify_step(returncode: int, sport: str, run_token: str, output: str = "") -> tuple[str, str]:
    """Return (status, detail) with status in {OK, SKIPPED_<governed outcome>, FAILED, RUN_RECEIPT_MISSING,
    RUN_RECEIPT_MISMATCH, UNCONFIGURED_SPORT, CONFIG_MISSING, BLOCKED_QUOTA}. Only OK and SKIPPED_* are not
    failures.

    Frozen runner semantics (owner, 2026-11-07), in precedence order:
      * a typed hard failure printed by the child (UNCONFIGURED_SPORT / CONFIG_MISSING / BLOCKED_QUOTA) -> that
        status, whatever the exit code (Safeguard A markers);
      * no readable receipt for THIS invocation -> RUN_RECEIPT_MISSING; another / no token -> RUN_RECEIPT_MISMATCH;
      * OK only when the process exited 0 AND this run's receipt says outcome == "UPDATED" AND exit_code is the
        integer 0 (never a bool, float or string);
      * SKIPPED_NO_GAMES_SCHEDULED only for exit 1 + receipt exit_code integer 1 + a GOVERNED schedule contract;
      * everything else -- missing, blank, unknown or contradictory outcome, NO_ACTIVE_EVENTS, ungoverned claims,
        exit >=2, signals -- is FAILED.

    Receipt-identity contract (2026-11-04, extended to this runner): the receipt counts as THIS invocation's
    only when it carries THIS invocation's run token (passed to the child in run_receipts.STAGE_RUN_ENV and
    stamped by fetch_game_lines). File mtime is never consulted -- on a coarse-timestamp filesystem two
    successive writes can share an mtime, and a newer file can be another writer's. Missing / unreadable ->
    RUN_RECEIPT_MISSING; another (or no) token -> RUN_RECEIPT_MISMATCH. Both are failures, never OK."""
    typed = typed_hard_failure(output)
    if typed:
        return typed, f"exit {returncode}, child reported {typed} (typed hard failure, never a skip)"
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
    if receipt.get("outcome") == CONFIG_MISSING:
        return CONFIG_MISSING, f"exit {returncode}, this run's receipt records CONFIG_MISSING (refused before any request)"
    if returncode == EXIT_OK:
        # OK only on positive proof (gate #2 finding #14): this run's receipt must say outcome == UPDATED AND
        # exit_code is the INTEGER 0. An absent / None / blank / unknown outcome, or a missing, different or
        # non-int exit_code (True, 0.0, "0"), is FAILED -- a malformed receipt never reads as a publish.
        if receipt.get("outcome") == "UPDATED" and is_exact_int(receipt.get("exit_code"), 0):
            return "OK", "published"
        return "FAILED", (f"exit 0 but this run's receipt does not prove a publish "
                          f"(outcome={receipt.get('outcome')!r}, exit_code={receipt.get('exit_code')!r})")
    if returncode == 1 and is_exact_int(receipt.get("exit_code"), 1) \
            and receipt.get("outcome") in BENIGN_RECEIPT_OUTCOMES \
            and governed_lines_nonpublish(receipt):
        return f"SKIPPED_{receipt.get('outcome')}", (f"{receipt.get('outcome')} (proven by this run's receipt, "
                                                     f"schedule_contract={receipt.get('schedule_contract')})")
    if receipt:
        return "FAILED", f"exit {returncode}, outcome={receipt.get('outcome')}"
    return "FAILED", f"exit {returncode}, this invocation's receipt proves no benign cause"


def _publish_summary(invocation_id: str, step_rows: list[dict], exit_code: int) -> bool:
    """Publish THIS invocation's summary through the governed, durable status store (services.linemove_status).
    MANDATORY: returns False on ANY failure (location, permission, write, replace, fsync, read-back), and the
    caller then exits 2 even when every child succeeded. A failure also tries to mark this invocation
    PUBLICATION_FAILED so Run Status degrades at once (and never reports an older summary as current)."""
    payload = {
        "invocation_id": invocation_id,
        "finished_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "exit_code": int(exit_code),
        "steps": step_rows,
        "failed_steps": [r["label"] for r in step_rows if r["status"] != "OK" and not r["status"].startswith("SKIPPED_")],
    }
    try:
        path = linemove_status.publish(linemove_status.SUMMARY_FILE, payload)
    except Exception as exc:   # noqa: BLE001 -- ANY failure (incl. a non-OSError) is a publication failure
        marked = linemove_status.mark_publication_failed(invocation_id, str(exc))
        print(f"FAILED: line-movement summary NOT published ({exc}); invocation marked PUBLICATION_FAILED="
              f"{marked}. Exiting 2 (no internal failure may be hidden).")
        return False
    print(f"Run summary published: {path.name} (invocation {invocation_id[:8]})")
    return True


def main() -> int:
    failures: list[tuple[str, str]] = []
    step_rows: list[dict] = []
    print("=" * 60)
    print("BANKROLL KINGS - LINE MOVEMENT SNAPSHOT CAPTURE")
    print("=" * 60)
    invocation_id = linemove_status.new_invocation_id()
    try:
        # FIRST: bind Run Status to THIS invocation. If even the marker cannot be published durably and safely,
        # refuse to run (no provider call) and exit 2 -- the run's result could never be reported honestly.
        linemove_status.begin(invocation_id)
    except Exception as exc:   # noqa: BLE001 -- ANY failure to bind this invocation refuses the run
        print(f"FAILED: cannot publish the line-movement invocation marker ({exc}). No step run; exit 2.")
        return EXIT_HARD_FAILURE
    print(f"Invocation {invocation_id}")
    for label, command, timeout, sport in STEPS:
        print(f"\n[{label}]")
        run_token = run_receipts.new_token()          # identifies THIS invocation's receipt (never mtime)
        child_env = dict(os.environ)
        child_env[run_receipts.STAGE_RUN_ENV] = run_token
        try:
            result = subprocess.run(command, cwd=BASE_DIR, timeout=timeout, env=child_env,
                                    capture_output=True, text=True)
        except subprocess.TimeoutExpired:
            failures.append((label, "timeout"))
            step_rows.append({"label": label, "sport": sport, "status": "FAILED", "detail": "timeout"})
            print("FAILED: timeout")
            continue
        except Exception as exc:
            failures.append((label, str(exc)))
            step_rows.append({"label": label, "sport": sport, "status": "FAILED", "detail": str(exc)[:200]})
            print(f"FAILED: {exc}")
            continue
        output = "\n".join(part for part in (result.stdout, result.stderr) if part)
        if output:
            print(output.rstrip())   # keep the child's output in the journal (captured only to classify it)
        # fetch_game_lines returns 1 for EVERY non-publish (provider error, validation reject, cost receipt,
        # publish failure, or a genuine zero-event window). Only this run's receipt can prove the benign one.
        status, detail = classify_step(result.returncode, sport, run_token, output)
        step_rows.append({"label": label, "sport": sport, "status": status, "detail": detail[:200],
                          "child_exit": result.returncode})
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
        # Frozen 2026-11-07: this runner exits ONLY 0 (every step OK or a governed skip) or 2 (any failure).
        # It never returns 1, so prod bk-linemove.service's SuccessExitStatus=1 can never read a failure as
        # SUCCESS (a governed skip is reported as 0 with its reason printed above, not as a 1).
        _publish_summary(invocation_id, step_rows, EXIT_HARD_FAILURE)
        return EXIT_HARD_FAILURE
    if not _publish_summary(invocation_id, step_rows, EXIT_OK):
        return EXIT_HARD_FAILURE          # every child succeeded, but the result could not be published
    print("All line-movement snapshots captured.")
    return EXIT_OK




def _entry() -> int:
    """Process entry: an UNCAUGHT exception would make Python exit 1, which prod bk-linemove's
    SuccessExitStatus=1 reads as SUCCESS. Any unexpected exception is therefore a hard failure, exit 2."""
    try:
        code = main()
    except Exception:   # noqa: BLE001
        import traceback
        traceback.print_exc()
        print("FAILED: unexpected exception in the line-movement runner; exit 2.")
        return EXIT_HARD_FAILURE
    return code if code in (EXIT_OK, EXIT_HARD_FAILURE) else EXIT_HARD_FAILURE


if __name__ == "__main__":
    raise SystemExit(_entry())
