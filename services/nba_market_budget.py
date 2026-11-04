"""
NBA market refresh TIMEOUT CONTRACT -- the one place every NBA lines/props time budget is defined (v5).
======================================================================================================

Read by: services/nba_market.py (stage commands + subprocess timeouts), refresh_nba_daily.py (bk-daily's
game_lines / player_props step timeouts), refresh_nba_market.py (the orchestrator) and
ops/bk-nba-market-refresh.service (TimeoutStartSec, asserted equal by qc_nba_market_orchestrator.py).
Nothing else may hard-code these numbers.

Contract (asserted in qc_nba_market_orchestrator.py):
  stage_timeout(stage) = LOCK_WAIT_SECONDS + <stage> EXECUTION budget
  bk-daily step timeout for a stage  >= LOCK_WAIT_SECONDS + that stage's execution budget
  orchestrator service timeout       >= stage_timeout(lines) + stage_timeout(props) + ORCHESTRATOR_OVERHEAD
A stage child that overruns its timeout is killed; the kernel releases its lock (process_lock) and its
atomic publish never half-lands, so a timeout is an honest PROVIDER_ERROR, never a partial write.

VALUES -- derived from production audit -- see docs/game_lines_event_contract.md "Timeout contract".
MEASURED (coordinator-derived from a read-only audit of every prod daily_operator log, NBA section, step
`seconds=`, audit date 2026-11-04; OWNER-APPROVED 2026-11-04):
  NBA game_lines    n=40  min 0.7  p50 0.9  p90 1.5  p95 1.7  max 1.8 s
  NBA player_props  n=38  min 0.7  p50 0.9  p90 1.8  p95 2.0  max 2.8 s
  (the 15-event five-day props refresh on 2026-11-02 took 2.0 s; samples include some fast
  validation-reject runs, so they are fetch+validate+publish times for 1-15 events.)
Derivation:
  lines execution 30 s  ~ 16x the observed max (1.8 s)
  props execution 60 s  ~ 20x the observed max (2.8 s); covers the per-market fallback (up to 6
                         single-market calls per event) on a full slate
  lock wait       30 s  the other holder's critical section is at most one lines+props cycle (~5 s observed)
  overhead        30 s  orchestrator process outside both stages
These replace v4's PROVISIONAL 120 s wait / 240 s steps. Do not inflate them to silence a timeout; change them
only from a new audit, recorded here and in the doc.
"""
from __future__ import annotations

PROVISIONAL = False   # measured (audit 2026-11-04); owner-approved 2026-11-04
SOURCE = ("MEASURED: prod daily_operator logs, audit 2026-11-04 (game_lines n=40 p95 1.7 s max 1.8 s; "
          "player_props n=38 p95 2.0 s max 2.8 s); owner-approved 2026-11-04 -- see "
          "docs/game_lines_event_contract.md 'Timeout contract'")

# Audit evidence kept next to the constants (seconds).
AUDIT = {
    "audit_date": "2026-11-04",
    "owner_approved": "2026-11-04",
    "lines": {"n": 40, "min": 0.7, "p50": 0.9, "p90": 1.5, "p95": 1.7, "max": 1.8},
    "props": {"n": 38, "min": 0.7, "p50": 0.9, "p90": 1.8, "p95": 2.0, "max": 2.8},
}

# name -> seconds. One table; every other number is derived from it.
TIMEOUT_TABLE: dict[str, int] = {
    "lock_wait_seconds": 30,              # MEASURED: other holder's critical section <= one cycle (~5 s)
    "lines_execution_seconds": 30,        # MEASURED: ~16x observed max 1.8 s
    "props_execution_seconds": 60,        # MEASURED: ~20x observed max 2.8 s; covers per-market fallback
    "orchestrator_overhead_seconds": 30,  # orchestrator process overhead outside both stages
}

LOCK_WAIT_SECONDS = TIMEOUT_TABLE["lock_wait_seconds"]
LINES_EXECUTION_SECONDS = TIMEOUT_TABLE["lines_execution_seconds"]
PROPS_EXECUTION_SECONDS = TIMEOUT_TABLE["props_execution_seconds"]
ORCHESTRATOR_OVERHEAD_SECONDS = TIMEOUT_TABLE["orchestrator_overhead_seconds"]

_EXECUTION = {"lines": LINES_EXECUTION_SECONDS, "props": PROPS_EXECUTION_SECONDS}


def execution_seconds(stage: str) -> int:
    return _EXECUTION[stage]


def stage_timeout(stage: str) -> int:
    """Subprocess timeout for one stage: the bounded lock wait plus that stage's execution budget. Used for
    bk-daily's step AND the orchestrator's stage (same number, same place)."""
    return LOCK_WAIT_SECONDS + execution_seconds(stage)


LINES_STAGE_TIMEOUT = stage_timeout("lines")   # 60
PROPS_STAGE_TIMEOUT = stage_timeout("props")   # 90
# systemd TimeoutStartSec for ops/bk-nba-market-refresh.service (QC asserts the unit file says this number).
SERVICE_TIMEOUT_SECONDS = LINES_STAGE_TIMEOUT + PROPS_STAGE_TIMEOUT + ORCHESTRATOR_OVERHEAD_SECONDS   # 180


def invariant_violations(step_timeouts: dict[str, int] | None = None) -> list[str]:
    """Empty when the contract holds. `step_timeouts` = {stage: bk-daily step timeout} to check as well."""
    bad = []
    for name, value in TIMEOUT_TABLE.items():
        if not isinstance(value, int) or value <= 0:
            bad.append(f"{name} must be a positive integer number of seconds (got {value!r})")
    for stage in ("lines", "props"):
        if stage_timeout(stage) < LOCK_WAIT_SECONDS + execution_seconds(stage):
            bad.append(f"{stage} stage timeout < lock wait + execution budget")
        if execution_seconds(stage) < AUDIT[stage]["max"]:
            bad.append(f"{stage} execution budget below the audited max duration")
        got = (step_timeouts or {}).get(stage)
        if step_timeouts is not None and (got is None or got < LOCK_WAIT_SECONDS + execution_seconds(stage)):
            bad.append(f"bk-daily {stage} step timeout {got} < lock wait {LOCK_WAIT_SECONDS} + execution "
                       f"{execution_seconds(stage)}")
    if SERVICE_TIMEOUT_SECONDS < LINES_STAGE_TIMEOUT + PROPS_STAGE_TIMEOUT + ORCHESTRATOR_OVERHEAD_SECONDS:
        bad.append("orchestrator service timeout < both stage timeouts + overhead")
    return bad


def as_receipt() -> dict:
    return {"provisional": PROVISIONAL, "source": SOURCE, **TIMEOUT_TABLE,
            "lines_stage_timeout": LINES_STAGE_TIMEOUT, "props_stage_timeout": PROPS_STAGE_TIMEOUT,
            "service_timeout_seconds": SERVICE_TIMEOUT_SECONDS}
