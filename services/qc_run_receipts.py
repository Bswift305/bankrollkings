"""QC helper: make a FAKED NBA stage child honour the receipt-identity contract (services/run_receipts.py).

QCs that replace the stage child with a fake `subprocess.run` must now do what the real publisher does: write
this stage's OWN per-run receipt under the run token ensure_stage passed in the child env -- otherwise the stage
correctly reads RUN_RECEIPT_MISSING. The outcome is derived with the REAL publisher mapping functions
(nba_lines_publisher._fetch_outcome, run_outcomes.classify_props_child), never re-implemented, so a QC that
fakes a fetch receipt still exercises the production classification.

`receipt_sandbox()` points BK_NBA_RUN_RECEIPT_DIR at a qc_* temp dir for the duration (contained, never the
checkout's runtime dir) and restores the environment afterwards.
"""
from __future__ import annotations

import contextlib
import os
import tempfile
from pathlib import Path

from services import run_receipts

_NO_PRIOR_RUN = object()   # sentinel: the fake's fetch receipt is always "from this run"


@contextlib.contextmanager
def receipt_sandbox():
    saved = os.environ.get(run_receipts.RECEIPT_DIR_OVERRIDE_ENV)
    with tempfile.TemporaryDirectory(prefix="qc_runreceipts_") as td:
        os.environ[run_receipts.RECEIPT_DIR_OVERRIDE_ENV] = str(Path(td) / "receipts")
        try:
            yield Path(td) / "receipts"
        finally:
            if saved is None:
                os.environ.pop(run_receipts.RECEIPT_DIR_OVERRIDE_ENV, None)
            else:
                os.environ[run_receipts.RECEIPT_DIR_OVERRIDE_ENV] = saved


def token_from(env) -> str | None:
    return (env or {}).get(run_receipts.STAGE_RUN_ENV)


def lines_receipt(env, base_dir, rc: int, wrote_fetch_receipt: bool = True) -> str | None:
    """The real lines publisher's outcome for a child that exited `rc` (reading the fake's fetch receipt the way
    publish() does). Writes this stage's own receipt; returns the outcome (None when no token)."""
    from services import nba_lines_publisher as lp
    tok = token_from(env)
    if not tok:
        return None
    outcome = lp._fetch_outcome(base_dir, _NO_PRIOR_RUN if wrote_fetch_receipt else
                                (lp._read_json(lp.fetch_receipt_path(base_dir)) or {}).get("run_id"), rc)
    run_receipts.write(tok, "lines", {"caller": "qc_fake_child", "outcome": outcome, "exit_code": rc})
    return outcome


def props_receipt(env, base_dir, rc: int, artifact: Path, advanced: bool) -> str | None:
    """The real props publisher's outcome (publish(): UPDATED only with exit 0 and a published file, else
    classify_props_child over the shape receipt). Writes this stage's own receipt; returns the outcome."""
    from services.run_outcomes import UPDATED, VALIDATION_FAILED, classify_props_child, load_shape_receipt
    tok = token_from(env)
    if not tok:
        return None
    if rc == 0 and Path(artifact).is_file():
        outcome = UPDATED
    else:
        outcome, _detail = classify_props_child(rc if rc else 1, advanced,
                                                load_shape_receipt(Path(base_dir), "basketball_nba"))
        if rc == 0:
            outcome = VALIDATION_FAILED
    run_receipts.write(tok, "props", {"caller": "qc_fake_child", "outcome": outcome, "exit_code": rc})
    return outcome
