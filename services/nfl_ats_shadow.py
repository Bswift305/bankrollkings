"""Decision Integrity — dark NFL ATS pilot: the shadow adapter (Phase 2C-dark).

One adapter AROUND the existing NFL ATS builder. It consumes the builder's board output
as READ-ONLY data, builds Decision-Integrity receipts in shadow/report-only mode, and
compares membership hash, ordering, counts, source health, and empty-state disposition
against the builder's own output. It NEVER mutates the builder output, never persists
anything, and never raises — every failure is captured into the returned record so the
existing page is unaffected and cannot 500.

The builder's output is passed as a read-only "board view" mapping (what the existing
`build_nfl_ats_wave` already computes), so this module imports neither the builder nor
pandas/Flask:

    {
      "sport": "nfl", "season": 2026,
      "surface": "nfl_ats_wave",
      "universe": ["team", "nfl_ats_board_2026", "v1"],
      "as_of": "2026-10-26T13:05:00Z",          # UTC instant
      "rows": [ {"team": "PHI", "leaf": "RENDERED", "reason": "QUALIFIED",
                 "def_version": 1}, ... ],        # IN AUTHORITATIVE ORDER
      "counts": {"RENDERED": 2, "SUPPRESSED": 1, "NONMEMBER": 2},
      "expected_count": 5,
      "empty_state": false,
      "source_health_state": "SYNCHRONIZED",      # SYNCHRONIZED | STALE | FAIL_CLOSED
      "sort_rule_id": "streak_desc_team_asc", "sort_rule_version": "1",
    }

`run_shadow` returns a report-only record (dict); it does not raise.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, List

from services.decision_receipts import (
    AuthorityClass, Clocks, EntityDisposition, EntityDispositionBatch, Identity, IdentityGrain,
    IdentityQuality, Integrity, Leaf, LiveEvidenceBoard, Projection, Receipt, ReceiptKind, Refs,
    ReplayClass, SchemaVersion, SourceHealthBody, SourceUpdatedStatus, Universe, Versions,
    HealthState, compute_membership_hash, seal_hashes, validate_receipt,
)
from services.decision_validators import (
    validate_nested_conservation, validate_count_reconciliation,
)

_MEMBER = {"RENDERED", "SUPPRESSED"}
_BATCH_ID = "c0000000-0000-4000-8000-000000000001"
_BOARD_ID = "c0000000-0000-4000-8000-000000000002"
_SH_ID = "c0000000-0000-4000-8000-000000000003"


def _input_hash(bo: Dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(bo, sort_keys=True, default=str).encode("utf-8")).hexdigest()


def _team_identity(sport, season, team) -> Identity:
    return Identity(IdentityGrain.TEAM, {"sport": sport, "season": season}, {"team": team},
                    IdentityQuality.DECLARED_COMPOSITE, True, f"({sport},{season},{team})",
                    "team:sport+season", "v1", "unique-in-sport-season")


def _build_batch(bo: Dict[str, Any], ih: str) -> Receipt:
    sport, season = bo.get("sport", "nfl"), bo.get("season", 2026)
    grain, uid, uver = bo["universe"]
    rows = [EntityDisposition(r["team"], _team_identity(sport, season, r["team"]),
                              Leaf(r["leaf"]), r["reason"], int(r["def_version"]))
            for r in bo["rows"]]
    return seal_hashes(Receipt(
        receipt_id=_BATCH_ID, receipt_kind=ReceiptKind.ENTITY_DISPOSITION,
        schema_version=SchemaVersion(1, 0), surface_id=bo["surface"],
        universe=Universe(grain, uid, uver), created_seq=1, created_at=bo["as_of"],
        versions=Versions("shadow", "cfg", {"ats": 1}), replay_class=ReplayClass.EVIDENCE_EQUIVALENT,
        authority_class=AuthorityClass.FACT, projection=Projection.INTERNAL,
        clocks=Clocks(bo["as_of"], SourceUpdatedStatus.NOT_PROVIDED, None, bo["as_of"]),
        input_hashes=[ih], integrity=Integrity(), body=EntityDispositionBatch(rows)))


def _build_source_health(bo: Dict[str, Any], ih: str) -> Receipt:
    grain, uid, uver = bo["universe"]
    return seal_hashes(Receipt(
        receipt_id=_SH_ID, receipt_kind=ReceiptKind.SOURCE_HEALTH,
        schema_version=SchemaVersion(1, 0), surface_id=bo["surface"],
        universe=Universe(grain, uid, uver), created_seq=1, created_at=bo["as_of"],
        versions=Versions("shadow", "cfg", {"ats": 1}), replay_class=ReplayClass.NON_REPLAYABLE,
        authority_class=AuthorityClass.DERIVED_CONTEXT, projection=Projection.INTERNAL,
        clocks=Clocks(bo["as_of"], SourceUpdatedStatus.NOT_PROVIDED, None, None), input_hashes=None,
        body=SourceHealthBody(HealthState(bo["source_health_state"]), bo["as_of"], {})))


def _build_board(bo: Dict[str, Any], batch: Receipt, ih: str) -> Receipt:
    grain, uid, uver = bo["universe"]
    return seal_hashes(Receipt(
        receipt_id=_BOARD_ID, receipt_kind=ReceiptKind.LIVE_EVIDENCE,
        schema_version=SchemaVersion(1, 0), surface_id=bo["surface"],
        universe=Universe(grain, uid, uver), created_seq=2, created_at=bo["as_of"],
        versions=Versions("shadow", "cfg", {"ats": 1}), replay_class=ReplayClass.EVIDENCE_EQUIVALENT,
        authority_class=AuthorityClass.FACT, projection=Projection.INTERNAL,
        clocks=Clocks(bo["as_of"], SourceUpdatedStatus.NOT_PROVIDED, None, bo["as_of"]),
        input_hashes=[ih], refs=Refs(entity_dispositions=batch.receipt_id, source_health=_SH_ID),
        body=LiveEvidenceBoard(compute_membership_hash(batch), dict(bo["counts"]),
                               int(bo["expected_count"]), bo.get("sort_rule_id"),
                               bo.get("sort_rule_version"))))


def run_shadow(builder_board_view: Any) -> dict:
    """Shadow/report-only. Returns a record; NEVER raises and NEVER mutates the input."""
    result = {
        "ok": False, "stage": "start", "error": None,
        "membership_hash": None, "receipts_valid": None,
        "parity": {"membership": None, "ordering": None, "counts": None,
                   "source_health": None, "empty_state": None, "all": None},
        "diffs": [], "fail_closed": [],
    }
    try:
        bo = builder_board_view  # read-only; never assigned into
        ih = _input_hash(bo if isinstance(bo, dict) else dict(bo))
        batch = _build_batch(bo, ih)
        sh = _build_source_health(bo, ih)
        board = _build_board(bo, batch, ih)
        result["membership_hash"] = board.body.membership_hash

        # Validate the receipts with the EXISTING suites' validators (fail closed).
        vchecks = [validate_receipt(batch), validate_receipt(sh), validate_receipt(board),
                   validate_nested_conservation(batch, board),
                   validate_count_reconciliation(board, batch)]
        result["receipts_valid"] = all(v.ok for v in vchecks)
        for v in vchecks:
            result["diffs"].extend(v.errors)

        # Parity: receipts (built) vs the builder's own declared board.
        builder_members = [r["team"] for r in bo["rows"] if r["leaf"] in _MEMBER]
        receipt_members = [r.identity.ext["team"] for r in batch.body.rows
                           if isinstance(r.leaf, Leaf) and r.leaf.value in _MEMBER]
        # Counts parity compares the builder's DECLARED counts against the actual tally
        # of the rows (not the board's echo of those same declared counts).
        tally: Dict[str, int] = {}
        for r in batch.body.rows:
            if isinstance(r.leaf, Leaf):
                tally[r.leaf.value] = tally.get(r.leaf.value, 0) + 1
        p = result["parity"]
        p["membership"] = set(builder_members) == set(receipt_members)
        p["ordering"] = builder_members == receipt_members
        p["counts"] = {k: v for k, v in tally.items() if v} == \
            {k: v for k, v in dict(bo["counts"]).items() if v} \
            and int(bo["expected_count"]) == len(batch.body.rows)
        p["source_health"] = sh.body.state.value == bo["source_health_state"]
        members_n = len(receipt_members)
        p["empty_state"] = (members_n == 0) == bool(bo["empty_state"])
        p["all"] = all(v is True for k, v in p.items() if k != "all")

        # Fail-closed: members presented on a non-synchronized source.
        if bo["source_health_state"] != HealthState.SYNCHRONIZED.value and members_n > 0:
            result["fail_closed"].append("members_present_on_non_synchronized_source")

        result["ok"] = bool(result["receipts_valid"] and p["all"] and not result["fail_closed"])
        result["stage"] = "complete"
    except Exception as exc:  # malformed builder output, etc. — recorded, never raised
        result["stage"] = "error"
        result["error"] = f"{type(exc).__name__}: {exc}"
        result["ok"] = False
    return result


__all__ = ["run_shadow"]
