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

Pure: stdlib only, no pandas, no app import -- safe to import from any refresh script.
"""
from __future__ import annotations

import json
from pathlib import Path

UPDATED = "UPDATED"
NO_ACTIVE_EVENTS = "NO_ACTIVE_EVENTS"
NO_MARKETS_POSTED = "NO_MARKETS_POSTED"
VALIDATION_FAILED = "VALIDATION_FAILED"
PROVIDER_ERROR = "PROVIDER_ERROR"
STALE = "STALE"
SKIP = "SKIP"

BENIGN = frozenset({UPDATED, NO_ACTIVE_EVENTS, NO_MARKETS_POSTED, SKIP})
ALERTING = frozenset({VALIDATION_FAILED, PROVIDER_ERROR, STALE})


def is_alerting(outcome: str) -> bool:
    return outcome in ALERTING


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


def aggregate_parent(child_outcomes: dict[str, str]) -> tuple[str, bool]:
    """Aggregate children into a parent summary. Returns (summary, degraded). degraded is True when ANY
    child is alerting -- the parent must then NOT report a bare PASS. A parent with only benign children
    is clean (but still reports WHICH benign state each child reached)."""
    degraded = any(is_alerting(o) for o in child_outcomes.values())
    parts = ", ".join(f"{label}={outcome}" for label, outcome in child_outcomes.items())
    return parts, degraded
