"""Decision Integrity — dark NFL ATS pilot: the application boundary (Phase 2C-dark).

This is the ONLY thing an application call site would touch. It is deliberately tiny
and dependency-free so that, when the flag is OFF (the default), there is ZERO receipt
work and ZERO import impact: the shadow adapter (which imports the receipt package) is
imported LAZILY, inside the enabled branch, so it never loads when the flag is off.

Contract for the (future, separately-authorized) call site:
    # after the existing builder has produced the page output, UNCHANGED:
    shadow = shadow_if_enabled(builder_board_view)   # returns None when OFF
It never raises, never returns a 500, never alters the builder output, and persists
nothing. The flag defaults OFF; only a local operator may turn it on.
"""

from __future__ import annotations

import os
from typing import Any, Optional

FLAG = "BK_DECISION_RECEIPTS_SHADOW"
_TRUTHY = {"1", "true", "on", "yes"}


def shadow_enabled(env: Optional[dict] = None) -> bool:
    """True only when the flag is explicitly set truthy. Default (unset) => OFF."""
    src = os.environ if env is None else env
    return str(src.get(FLAG, "0")).strip().lower() in _TRUTHY


def shadow_if_enabled(builder_board_view: Any, env: Optional[dict] = None) -> Optional[dict]:
    """Report-only shadow entry point.

    OFF (default): returns None immediately — imports nothing, does no receipt work,
    touches nothing. This is the application-boundary no-op that must have zero impact.

    ON (local operator only): lazily imports the adapter and runs the shadow comparison
    in report-only mode. ANY failure is captured into a record and returned; it is never
    raised, so the existing page is unaffected and cannot 500.
    """
    if not shadow_enabled(env):
        return None
    try:
        from services import nfl_ats_shadow  # lazy: only imported when the flag is ON
        return nfl_ats_shadow.run_shadow(builder_board_view)
    except Exception as exc:  # the boundary itself must never raise to the caller
        return {"ok": False, "stage": "boundary",
                "error": f"{type(exc).__name__}: {exc}", "parity": None, "receipts_valid": None}


__all__ = ["FLAG", "shadow_enabled", "shadow_if_enabled"]
