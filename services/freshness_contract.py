"""
Bankroll Kings - the ONE declared freshness contract.
======================================================

Incident 2026-10-24 surfaced a contradiction: the availability report called NFL/NCAAF props
STALE (>6h) and PROBE_JUSTIFIED while qc_odds_feed called the SAME 39-40h files FRESH (<40h). Two
monitoring tools, two hand-picked thresholds, opposite verdicts on the same file. That is not
allowed. Every freshness decision in the platform now imports its window from HERE.

There are TWO clocks, because there are two different questions. They are declared together, each
labeled, so nothing is ambiguous -- but a tool must use the clock that matches its question:

  CLOCK A -- RENDER / LIVE-MARKET  (reads the feed's own `LastUpdated` column: the provider timestamp
      on the freshest row). Question: "is this current PRICE fresh enough to show as a live market?"
      A line/prop whose freshest provider timestamp is older than this is rendered stale / suppressed,
      never shown as a live current price. CUSTOMER-FACING (get_props_refresh_meta,
      get_lines_refresh_meta, the board fail-closed gates).

  CLOCK B -- REFRESH CADENCE  (reads the FILE mtime: when the refresh job last wrote the artifact).
      Question: "did the daily refresh job advance this artifact?" The daily operator refreshes every
      current-market feed once per ~24h cycle, so a file older than one cycle + margin means a cycle
      was missed (pipeline broken, or no new data was accepted). MONITORING-FACING (qc_odds_feed,
      report_feed_availability, generate_run_status).

These answer different questions, so they can legitimately differ for one feed (a file rewritten
hourly with 10h-old provider data is CLOCK-B fresh but CLOCK-A stale -- the job ran, the price is not
current). What is NOT allowed is two tools answering the SAME question with different numbers; both
monitoring tools now read CLOCK B from this module, so they cannot contradict.
"""
from __future__ import annotations

# ---- CLOCK A: render / live-market window (data LastUpdated timestamp), customer-facing ----
# A current price older than this by its own provider timestamp is not live. The live-market window,
# NOT a lax convenience value: an active-slate line that has not moved in 6h is stale and fails closed.
LIVE_MARKET_MAX_AGE_HOURS: float = 6.0

# ---- CLOCK B: refresh-cadence window (file mtime), monitoring-facing ----
# The daily operator writes every current-market feed once per ~24h cycle. 30h = one cycle + 6h margin,
# the same window Run Status already uses for its daily analysis artifacts (fresh_hours=30). A file
# older than this missed a cycle -> flag it. It will NOT flap under healthy daily operation: the next
# ~24h run resets the file age below 30h before it can trip. Grading advances as results finalize, so
# it gets two cycles + margin.
REFRESH_CADENCE_MAX_AGE_HOURS: dict[str, float] = {
    "game_lines": 30.0,
    "props": 30.0,
    "futures": 30.0,
    "grading": 54.0,
}

# Per-(family, SPORT) overrides. EMPTY today: every sport's props and game lines refresh on the same
# daily operator cadence, so the window is uniform and NFL/NCAAF get no special longer cadence (their
# 39-40h age in the incident was a MISSED cycle, correctly STALE -- not a legitimate slower feed). If a
# sport ever moves to a different cadence, declare it here WITH a one-line rationale, so "fresh vs
# stale" is never a per-tool guess.
REFRESH_CADENCE_OVERRIDES: dict[tuple[str, str], float] = {}

_VALID_FAMILIES = frozenset(REFRESH_CADENCE_MAX_AGE_HOURS)


def refresh_cadence_hours(family: str, sport: str | None = None) -> float:
    """CLOCK B window for a feed family (optionally sport-aware). Raises on an unknown family so a
    typo cannot silently fall back to a lax default."""
    if family not in _VALID_FAMILIES:
        raise KeyError(f"unknown feed family {family!r}; known: {sorted(_VALID_FAMILIES)}")
    if sport:
        override = REFRESH_CADENCE_OVERRIDES.get((family, sport.upper()))
        if override is not None:
            return override
    return REFRESH_CADENCE_MAX_AGE_HOURS[family]


def cadence_state(age_hours: float | None, family: str, sport: str | None = None) -> str:
    """MISSING / FRESH / STALE for a file age against the CLOCK-B cadence window."""
    if age_hours is None:
        return "MISSING"
    return "FRESH" if age_hours <= refresh_cadence_hours(family, sport) else "STALE"
