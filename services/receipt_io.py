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
  * stage-run attribution: see services/run_receipts.py -- each publisher invocation writes its OWN per-run
    receipt named by its run token, and a stage outcome is read only from that file (no shared-file/mtime
    fallback). The shared `_last_nba_*_publish.json` files are operational history only.
"""
from __future__ import annotations

import os
import time
from pathlib import Path

from services.run_receipts import STAGE_RUN_ENV  # noqa: E402  (single definition)
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
