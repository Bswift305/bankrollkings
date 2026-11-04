"""
Bankroll Kings - per-sport refresh OUTCOME vocabulary + receipt-based classifier.
=================================================================================

Incident 2026-10-24 directives #2/#3: a parent refresh step must derive its result from its children's
actual outcomes, and a props child that fetched zero rows must be treated as VALIDATION_FAILED (an
alerting state) UNTIL a sanitized response-shape receipt proves every response lacked all requested
markets -- only then is it the benign NO_MARKETS_POSTED. Zero output rows, or zero reported cost, never
prove "no markets" by themselves.

The vocabulary (one honest state per child):
  UPDATED            artifact advanced with freshly fetched rows            benign
  NO_ACTIVE_EVENTS   no events in the fetch window (off-season/between)      benign
  NO_MARKETS_POSTED  events exist, PROVEN no requested market on any event   benign
  VALIDATION_FAILED  rows failed validation / 0 rows not proven benign       ALERTING
  PROVIDER_ERROR     the provider errored on one or more events              ALERTING
  STALE              artifact did not advance and nothing benign explains it ALERTING
  SKIP               deliberately not run (season gate, missing key)         benign
  SKIPPED_BLOCKED_BY_LINES  not run: it needs fresh game lines and the lines
                     step failed this run (honest skip, never success)       ALERTING

Game-lines governance (2026-11, docs/game_lines_event_contract.md "Governed no-game result" and
"Single publisher + lock"):
  NO_GAMES_SCHEDULED a FRESH, AUTHORITATIVE, INDEPENDENT schedule affirmatively
                     says zero games for the governed Eastern service date;
                     decided BEFORE any paid call (zero credits)             benign
  SCHEDULE_UNAVAILABLE the provider returned zero events and no fresh
                     authoritative independent schedule can confirm a no-game
                     day (missing / stale / ambiguous / circular source):
                     fail closed, never an invented no-game result           ALERTING
  SKIPPED_LOCKED     another process holds the shared NBA game-lines publisher
                     lock; this run made no paid request and wrote nothing   ALERTING
  REUSED_FRESH       the other lines job published a receipt-verified lines
                     file inside the reuse window; reused, no paid request   benign
  REUSED_FRESH_AFTER_LOCK  this run WAITED for another holder of the lock,
                     then re-read the receipt + file hashes UNDER the lock and
                     found a valid publish inside the reuse window; reused,
                     no paid request (the collision is visible)               benign
  NO_FRESH_AFTER_LOCK  this run waited for another holder, re-read under the
                     lock, found NO valid fresh publish, and was told not to
                     fetch after contention: nothing published               ALERTING
  (The 90-min reuse window is duplicate-fetch suppression only; the executable
  boundary for customers stays the 6h CLOCK-A rule.)
An outcome in NEITHER set is unknown and is treated as alerting by is_alerting (fail closed).

Pure: stdlib only, no pandas, no app import -- safe to import from any refresh script.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

UPDATED = "UPDATED"
NO_ACTIVE_EVENTS = "NO_ACTIVE_EVENTS"
NO_MARKETS_POSTED = "NO_MARKETS_POSTED"
VALIDATION_FAILED = "VALIDATION_FAILED"
PROVIDER_ERROR = "PROVIDER_ERROR"
STALE = "STALE"
SKIP = "SKIP"
SKIPPED_BLOCKED_BY_LINES = "SKIPPED_BLOCKED_BY_LINES"
NO_GAMES_SCHEDULED = "NO_GAMES_SCHEDULED"
SCHEDULE_UNAVAILABLE = "SCHEDULE_UNAVAILABLE"
SKIPPED_LOCKED = "SKIPPED_LOCKED"
REUSED_FRESH = "REUSED_FRESH"
REUSED_FRESH_AFTER_LOCK = "REUSED_FRESH_AFTER_LOCK"
NO_FRESH_AFTER_LOCK = "NO_FRESH_AFTER_LOCK"
# Receipt-identity contract (2026-11-04): a governed NBA stage outcome comes ONLY from the stage's own per-run
# receipt (services/run_receipts). No receipt -> RUN_RECEIPT_MISSING; another run's token -> RUN_RECEIPT_MISMATCH.
RUN_RECEIPT_MISSING = "RUN_RECEIPT_MISSING"
RUN_RECEIPT_MISMATCH = "RUN_RECEIPT_MISMATCH"

BENIGN = frozenset({UPDATED, NO_ACTIVE_EVENTS, NO_MARKETS_POSTED, SKIP, NO_GAMES_SCHEDULED, REUSED_FRESH,
                    REUSED_FRESH_AFTER_LOCK})
ALERTING = frozenset({VALIDATION_FAILED, PROVIDER_ERROR, STALE, SKIPPED_BLOCKED_BY_LINES,
                      SCHEDULE_UNAVAILABLE, SKIPPED_LOCKED, NO_FRESH_AFTER_LOCK, RUN_RECEIPT_MISSING,
                      RUN_RECEIPT_MISMATCH})

# Lines-step outcomes that mean "a verified, current lines file is in place" (dependents may run).
LINES_READY = frozenset({UPDATED, REUSED_FRESH, REUSED_FRESH_AFTER_LOCK})

# Game-lines receipt outcomes that prove a benign NON-publish (nothing to fetch). Exit code alone can never
# prove one; a receipt written by THIS run must. SCHEDULE_UNAVAILABLE is deliberately absent.
BENIGN_LINES_NONPUBLISH = frozenset({NO_ACTIVE_EVENTS, NO_GAMES_SCHEDULED})


def is_alerting(outcome: str) -> bool:
    # Fail closed: only an outcome explicitly declared BENIGN is non-alerting. An unknown string (a new
    # child vocabulary word nobody classified) must never read as a clean run.
    return outcome not in BENIGN


def load_shape_receipt(base_dir: Path, sport_slug: str) -> dict | None:
    """Read data/tracking/_last_props_fetch_<slug>.json written by fetch_player_props. None if absent
    or unreadable (treated conservatively by the classifier)."""
    path = Path(base_dir) / "data" / "tracking" / f"_last_props_fetch_{sport_slug.replace('/', '_')}.json"
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def classify_props_child(exit_code: int, artifact_advanced: bool, receipt: dict | None) -> tuple[str, str]:
    """Return (OUTCOME, one-line detail). The receipt carries FACTS (events_found, rows_fetched, whether
    any requested market was present, provider errors); exit_code + artifact_advanced say whether the
    child published. NO_MARKETS_POSTED requires the receipt to PROVE it; absent proof, zero rows is
    VALIDATION_FAILED (directive #2)."""
    if receipt is None:
        # No evidence file. Do not invent a benign outcome.
        if exit_code == 0 and artifact_advanced:
            return UPDATED, "published new rows (no shape receipt present)"
        if exit_code == 0 and not artifact_advanced:
            return STALE, "child reported success but the artifact did not advance, and no receipt exists"
        return VALIDATION_FAILED, "child failed and no shape receipt exists to prove a benign cause"

    events = int(receipt.get("events_found") or 0)
    rows = int(receipt.get("rows_fetched") or 0)
    provider_errors = int(receipt.get("provider_error_count") or 0)
    proven_no_markets = bool(receipt.get("shape_proves_no_markets_posted"))
    present = receipt.get("markets_present_anywhere") or []

    if events == 0:
        return NO_ACTIVE_EVENTS, "no events in the fetch window"
    if rows == 0 and provider_errors > 0:
        return PROVIDER_ERROR, f"{provider_errors} event(s) errored and zero rows were fetched"
    if rows > 0 and artifact_advanced:
        return UPDATED, f"{rows} rows fetched and published"
    if rows > 0 and not artifact_advanced:
        return VALIDATION_FAILED, (f"{rows} rows fetched but the artifact did not advance "
                                   "(validation/collapse preserved last-known-good)")
    # rows == 0, no provider errors
    if proven_no_markets:
        return NO_MARKETS_POSTED, f"{events} event(s) in window but no requested market posted on any (proven)"
    return VALIDATION_FAILED, (f"zero rows but requested markets WERE present ({', '.join(present) or 'see receipt'}) "
                               "-- not proven NO_MARKETS_POSTED; treat as validation/parse failure")


def _mtime(path) -> float:
    try:
        return Path(path).stat().st_mtime
    except OSError:
        return 0.0


def props_step_outcome(base_dir, sport_slug: str, artifact_path, mtime_before: float,
                       exit_code: int, timed_out: bool) -> tuple[str, str, bool]:
    """Shared by every sport parent for its player-props child: classify from the shape receipt + whether
    the artifact advanced, so NBA / MLB / football all use the SAME vocabulary. Returns
    (outcome, detail, alerting)."""
    if timed_out:
        return PROVIDER_ERROR, "player-props fetch timed out", True
    advanced = _mtime(artifact_path) > mtime_before
    receipt = load_shape_receipt(base_dir, sport_slug)
    outcome, detail = classify_props_child(exit_code, advanced, receipt)
    return outcome, detail, is_alerting(outcome)


def record_child_outcomes(base_dir, parent: str, outcomes: dict[str, str]) -> None:
    """Write a structured per-parent child-outcome sidecar so the operator summary records the CHILD
    OUTCOME (the vocabulary) -- not merely the parent exit code (directive #3). Best-effort; one file per
    parent so parents never clobber each other."""
    path = Path(base_dir) / "data" / "tracking" / f"_child_outcomes_{parent}.json"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps({
            "parent": parent,
            "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "outcomes": outcomes,
            "degraded": any(is_alerting(o) for o in outcomes.values()),
        }, indent=2), encoding="utf-8")
        tmp.replace(path)
    except OSError:
        pass


def load_all_child_outcomes(base_dir) -> dict[str, dict]:
    """Merge every _child_outcomes_<parent>.json for the operator summary. Returns {parent: payload}."""
    out: dict[str, dict] = {}
    tracking = Path(base_dir) / "data" / "tracking"
    try:
        files = sorted(tracking.glob("_child_outcomes_*.json"))
    except OSError:
        return out
    for f in files:
        try:
            payload = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        parent = payload.get("parent") or f.stem.replace("_child_outcomes_", "")
        out[parent] = payload
    return out


def aggregate_parent(child_outcomes: dict[str, str]) -> tuple[str, bool]:
    """Aggregate children into a parent summary. Returns (summary, degraded). degraded is True when ANY
    child is alerting -- the parent must then NOT report a bare PASS. A parent with only benign children
    is clean (but still reports WHICH benign state each child reached)."""
    degraded = any(is_alerting(o) for o in child_outcomes.values())
    parts = ", ".join(f"{label}={outcome}" for label, outcome in child_outcomes.items())
    return parts, degraded
