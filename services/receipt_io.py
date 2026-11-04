"""Receipt write + stage-run attribution helpers for the NBA market publishers (v5 race fix, 2026-11-04).

Race this fixes (qc_nba_market_orchestrator (5), ~1 in 4 runs on Windows): when a lines lock holder exits, its
parent (services/nba_market.ensure_stage -> classify_lines) READS `_last_nba_lines_publish.json` at the same
moment the waiting publisher -- which has just acquired the lock -- REPLACES that file with its own
NO_FRESH_AFTER_LOCK receipt. On Windows `os.replace` onto a file another process has open fails with
PermissionError (WinError 5); the publisher swallowed it as a [WARN], so the waiter's parent then read the
HOLDER's receipt (PROVIDER_ERROR) as its own -- receipts were attributed only by mtime.

Two parts:
  * replace_with_retry: bounded retry of the atomic replace on PermissionError only (a reader's open handle is
    held for milliseconds); any other error, or the budget running out, still raises.
  * stage-run attribution: services/nba_market.ensure_stage passes a per-stage token in STAGE_RUN_ENV; both
    publishers stamp it as `stage_run_id` on every publisher receipt; the classifiers only accept a receipt
    carrying THIS stage's token, and a receipt from another stage run is never adopted (fail closed).
"""
from __future__ import annotations

import os
import time
from pathlib import Path

STAGE_RUN_ENV = "BK_NBA_STAGE_RUN_ID"
REPLACE_RETRY_SECONDS = 5.0


def current_stage_run_id():
    """The validated per-stage token (32 lowercase hex) from the environment, or None."""
    tok = str(os.environ.get(STAGE_RUN_ENV, "")).strip()
    if len(tok) == 32 and all(ch in "0123456789abcdef" for ch in tok):
        return tok
    return None


def replace_with_retry(tmp, path, budget_seconds: float = REPLACE_RETRY_SECONDS) -> None:
    """os.replace(tmp, path), retrying ONLY PermissionError (Windows sharing violation while another process
    has `path` open) until budget_seconds have elapsed; then the last error is raised."""
    deadline = time.monotonic() + max(0.0, float(budget_seconds))
    delay = 0.01
    while True:
        try:
            os.replace(str(tmp), str(path))
            return
        except PermissionError:
            if time.monotonic() >= deadline:
                raise
            time.sleep(delay)
            delay = min(delay * 2, 0.2)


def write_text_atomic(path, text: str, budget_seconds: float = REPLACE_RETRY_SECONDS) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    replace_with_retry(tmp, path, budget_seconds)


# ------------------------------------------------------------------------------------------------ per-run receipts
# The shared "_last_nba_*_publish.json" is a single slot: when two publishers finish close together (a lock holder
# and the waiter it released), the later write replaces the earlier one before the earlier stage's parent has
# classified it. So every publisher receipt is ALSO written to a file named by its stage-run token, which nothing
# else ever writes; services/nba_market classifies a stage from that file. Kept 7 days (housekeeping in
# prune_stage_run_receipts), under the gitignored data/tracking/.
STAGE_RUN_DIRNAME = "nba_stage_runs"
STAGE_RUN_KEEP_DAYS = 7


def stage_run_receipt_path(shared_receipt_path, stage_run_id: str, kind: str) -> Path:
    return Path(shared_receipt_path).parent / STAGE_RUN_DIRNAME / f"{stage_run_id}.{kind}.json"


def write_stage_run_copy(shared_receipt_path, kind: str, text: str) -> None:
    """Write this run's own copy of a publisher receipt (no-op without a stage-run token)."""
    tok = current_stage_run_id()
    if tok:
        write_text_atomic(stage_run_receipt_path(shared_receipt_path, tok, kind), text)


def prune_stage_run_receipts(shared_receipt_path, keep_days: float = STAGE_RUN_KEEP_DAYS) -> int:
    d = Path(shared_receipt_path).parent / STAGE_RUN_DIRNAME
    cutoff = time.time() - keep_days * 86400
    n = 0
    try:
        for p in d.glob("*.json"):
            try:
                if p.stat().st_mtime < cutoff:
                    p.unlink()
                    n += 1
            except OSError:
                pass
    except OSError:
        pass
    return n
