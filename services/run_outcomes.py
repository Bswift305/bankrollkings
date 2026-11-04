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
import re
from datetime import datetime, timezone
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


_PARENT_RE = re.compile(r"^[a-z0-9_]{1,64}$")


def record_child_outcomes(base_dir, parent: str, outcomes: dict[str, str]) -> None:
    """Write a structured per-parent child-outcome sidecar so the operator summary records the CHILD
    OUTCOME (the vocabulary) -- not merely the parent exit code (directive #3). Best-effort; one file per
    parent so parents never clobber each other.

    D11: EVERY sidecar is stamped with the operator run id inherited from run_daily (BK_OPERATOR_RUN_ID).
    Outside the operator the stamp is null -- a tokenless sidecar is legacy history and never a current
    outcome. Written atomically (0600, no symlink, contained in data/tracking); `at` is UTC ISO-Z."""
    from services.operator_run import atomic_write_json, env_run_id, utc_now_iso
    if not _PARENT_RE.match(str(parent)):
        return
    tracking = Path(base_dir) / "data" / "tracking"
    path = tracking / f"_child_outcomes_{parent}.json"
    try:
        atomic_write_json(path, {
            "parent": parent,
            "run_id": env_run_id(),
            "at": utc_now_iso(),
            "outcomes": outcomes,
            "degraded": any(is_alerting(o) for o in outcomes.values()),
        })
    except (OSError, ValueError):
        pass


def partition_child_outcomes(base_dir, run_id) -> tuple[dict[str, dict], dict[str, dict], dict[str, dict]]:
    """Split every _child_outcomes_<parent>.json into (this_run, other_runs, legacy) by EXACT run id.

      this_run    stamped with exactly `run_id` -> the only sidecars that may be current outcomes;
      other_runs  stamped with a DIFFERENT valid run id (a parent that did not run this time: an aborted
                  chain, an out-of-set sport) -> {parent: {run_id, at}}, labelling only;
      legacy      tokenless / malformed stamp (pre-D11 or written outside the operator) -> {parent: {at}},
                  legacy history only, NEVER current.
    No (valid) run id -> nothing is current. A symlinked sidecar is ignored."""
    from services.operator_run import valid_run_id
    current: dict[str, dict] = {}
    other: dict[str, dict] = {}
    legacy: dict[str, dict] = {}
    tracking = Path(base_dir) / "data" / "tracking"
    try:
        files = sorted(tracking.glob("_child_outcomes_*.json"))
    except OSError:
        return current, other, legacy
    for f in files:
        if f.is_symlink():
            continue
        try:
            payload = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(payload, dict):
            continue
        parent = f.stem.replace("_child_outcomes_", "")
        stamp = payload.get("run_id")
        if valid_run_id(run_id) and stamp == run_id:
            current[parent] = payload
        elif valid_run_id(stamp):
            other[parent] = {"run_id": stamp, "at": payload.get("at")}
        else:
            legacy[parent] = {"at": payload.get("at")}
    return current, other, legacy


def load_all_child_outcomes(base_dir, run_id) -> dict[str, dict]:
    """The CURRENT run's child outcomes for the operator summary: {parent: payload}, only sidecars stamped
    with exactly `run_id` (D11: a stale or tokenless sidecar is never folded in)."""
    return partition_child_outcomes(base_dir, run_id)[0]


def aggregate_parent(child_outcomes: dict[str, str]) -> tuple[str, bool]:
    """Aggregate children into a parent summary. Returns (summary, degraded). degraded is True when ANY
    child is alerting -- the parent must then NOT report a bare PASS. A parent with only benign children
    is clean (but still reports WHICH benign state each child reached)."""
    degraded = any(is_alerting(o) for o in child_outcomes.values())
    parts = ", ".join(f"{label}={outcome}" for label, outcome in child_outcomes.items())
    return parts, degraded
