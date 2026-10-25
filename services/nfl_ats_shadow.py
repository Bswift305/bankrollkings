"""Decision Integrity — dark NFL ATS pilot: the shadow adapter (Phase 2C-dark, Rev 2).

One adapter AROUND the existing NFL ATS builder. It consumes the builder's board output
as READ-ONLY data, builds Decision-Integrity receipts in shadow/report-only mode, runs the
FULL applicable existing validator set, and compares membership hash, ordering, counts,
source health, and empty-state disposition against the builder's own output. It never
mutates the input, never persists, and never raises.

It FABRICATES NOTHING. The builder's board view must supply the governed identity evidence
(quality/profile/version/collision proof) for each row and full provenance (builder/build
id, config version, rule versions, ordering rule id/version, source fingerprints,
observation sequence). A row that supplies only a display label is honestly classified
non-authoritative and the shadow fails closed. Missing provenance fails the shadow.

Board-view contract (read-only mapping):
    {
      "sport","season","surface","universe":[grain,id,ver],"as_of": <UTC>,
      "provenance": {
        "build_id","config_version",
        "rule_versions": {"membership": <int>, "ordering": <int>, ...},
        "ordering_rule_id","ordering_rule_version",
        "source_fingerprints": [<str>, ...],   # non-empty; builder-supplied
        "observation_seq": <int>                # governed, per build
      },
      "rows": [ {"leaf","reason","def_version","params"?,
                 "identity": {"quality","key","base","ext"?,"collision_tested"?,
                              "profile"?,"profile_version"?,"collision_proof"?}} ],
      "counts": {leaf:int}, "expected_count": int, "empty_state": bool,
      "source_health_state": "SYNCHRONIZED"|"STALE"|"FAIL_CLOSED",
    }
"""

from __future__ import annotations

import hashlib
import json
import uuid
from typing import Any, Dict, List

from services.decision_receipts import (
    AuthorityClass, Clocks, EntityDisposition, EntityDispositionBatch, Identity, IdentityGrain,
    IdentityQuality, Integrity, Leaf, LiveEvidenceBoard, Projection, Receipt, ReceiptKind, Refs,
    ReplayClass, SchemaVersion, SourceHealthBody, SourceUpdatedStatus, Universe, Versions,
    HealthState, compute_membership_hash, seal_hashes, validate_receipt,
)
from services.decision_validators import (
    validate_reason_usage, validate_identity_collision, validate_nested_conservation,
    validate_count_reconciliation, validate_hierarchical_references, validate_canonical_replay,
)

_MEMBER = {"RENDERED", "SUPPRESSED"}
_ELIGIBLE_OR_MEMBER = {"RENDERED", "SUPPRESSED", "NONMEMBER"}
# Fixed namespace so deterministic receipt ids are reproducible across runs/machines.
_NS = uuid.UUID("6f9619ff-8b86-4d01-b42d-00cf4fc964ff")
_REQUIRED_PROVENANCE = ("build_id", "config_version", "rule_versions", "ordering_rule_id",
                        "ordering_rule_version", "source_fingerprints", "observation_seq")


def _require_provenance(bo: Dict[str, Any]) -> Dict[str, Any]:
    prov = bo.get("provenance")
    if not isinstance(prov, dict):
        raise ValueError("missing provenance block")
    missing = [k for k in _REQUIRED_PROVENANCE if not prov.get(k) and prov.get(k) != 0]
    if missing:
        raise ValueError(f"missing provenance fields: {missing}")
    if not isinstance(prov["source_fingerprints"], list) or not prov["source_fingerprints"]:
        raise ValueError("provenance.source_fingerprints must be a non-empty list")
    if not isinstance(prov["rule_versions"], dict) \
            or any(not isinstance(v, int) or isinstance(v, bool) for v in prov["rule_versions"].values()):
        raise ValueError("provenance.rule_versions must map to integers")
    if not isinstance(prov["observation_seq"], int) or isinstance(prov["observation_seq"], bool) \
            or prov["observation_seq"] <= 0:
        raise ValueError("provenance.observation_seq must be a positive integer")
    return prov


def _rid(prov: Dict[str, Any], kind: str) -> str:
    """Deterministic UUID from the build identity + source fingerprints + receipt kind.
    Different builds => different ids; replaying the identical build => identical ids."""
    key = "|".join([str(prov["build_id"]), str(prov["observation_seq"]),
                    "+".join(map(str, prov["source_fingerprints"])), kind])
    return str(uuid.uuid5(_NS, key))


def _input_hashes(prov: Dict[str, Any]) -> List[str]:
    # Digest each supplied source fingerprint to a 64-hex input hash (shape-stable;
    # the fingerprint itself is builder-supplied provenance, never fabricated here).
    return [hashlib.sha256(str(fp).encode("utf-8")).hexdigest() for fp in prov["source_fingerprints"]]


def _identity_from_view(idv: Dict[str, Any]) -> Identity:
    """Build the contract Identity VERBATIM from the builder-supplied identity evidence —
    no quality/collision/profile is invented. A view that supplies only a label will
    carry quality NAME_ONLY and fail closed downstream (R12/R13)."""
    if not isinstance(idv, dict) or "quality" not in idv or "key" not in idv or "base" not in idv:
        raise ValueError("row identity must supply quality + key + base (governed evidence)")
    return Identity(IdentityGrain.TEAM, dict(idv["base"]), dict(idv.get("ext", {})),
                    IdentityQuality[idv["quality"]], bool(idv.get("collision_tested", False)),
                    idv["key"], idv.get("profile"), idv.get("profile_version"),
                    idv.get("collision_proof"))


def _versions(prov: Dict[str, Any]) -> Versions:
    return Versions(str(prov["build_id"]), str(prov["config_version"]), dict(prov["rule_versions"]))


def _build_batch(bo, prov, ih) -> Receipt:
    grain, uid, uver = bo["universe"]
    base_seq = prov["observation_seq"] * 10
    rows = [EntityDisposition(r["team"], _identity_from_view(r["identity"]), Leaf(r["leaf"]),
                              r["reason"], int(r["def_version"]), r.get("params"))
            for r in bo["rows"]]
    return seal_hashes(Receipt(
        receipt_id=_rid(prov, "entity_disposition"), receipt_kind=ReceiptKind.ENTITY_DISPOSITION,
        schema_version=SchemaVersion(1, 0), surface_id=bo["surface"],
        universe=Universe(grain, uid, uver), created_seq=base_seq + 1, created_at=bo["as_of"],
        versions=_versions(prov), replay_class=ReplayClass.EVIDENCE_EQUIVALENT,
        authority_class=AuthorityClass.FACT, projection=Projection.INTERNAL,
        clocks=Clocks(bo["as_of"], SourceUpdatedStatus.NOT_PROVIDED, None, bo["as_of"]),
        input_hashes=ih, integrity=Integrity(), body=EntityDispositionBatch(rows)))


def _build_source_health(bo, prov) -> Receipt:
    grain, uid, uver = bo["universe"]
    base_seq = prov["observation_seq"] * 10
    return seal_hashes(Receipt(
        receipt_id=_rid(prov, "source_health"), receipt_kind=ReceiptKind.SOURCE_HEALTH,
        schema_version=SchemaVersion(1, 0), surface_id=bo["surface"],
        universe=Universe(grain, uid, uver), created_seq=base_seq, created_at=bo["as_of"],
        versions=_versions(prov), replay_class=ReplayClass.NON_REPLAYABLE,
        authority_class=AuthorityClass.DERIVED_CONTEXT, projection=Projection.INTERNAL,
        clocks=Clocks(bo["as_of"], SourceUpdatedStatus.NOT_PROVIDED, None, None), input_hashes=None,
        body=SourceHealthBody(HealthState(bo["source_health_state"]), bo["as_of"], {})))


def _build_board(bo, prov, batch, sh, ih) -> Receipt:
    grain, uid, uver = bo["universe"]
    base_seq = prov["observation_seq"] * 10
    return seal_hashes(Receipt(
        receipt_id=_rid(prov, "live_evidence"), receipt_kind=ReceiptKind.LIVE_EVIDENCE,
        schema_version=SchemaVersion(1, 0), surface_id=bo["surface"],
        universe=Universe(grain, uid, uver), created_seq=base_seq + 2, created_at=bo["as_of"],
        versions=_versions(prov), replay_class=ReplayClass.EVIDENCE_EQUIVALENT,
        authority_class=AuthorityClass.FACT, projection=Projection.INTERNAL,
        clocks=Clocks(bo["as_of"], SourceUpdatedStatus.NOT_PROVIDED, None, bo["as_of"]),
        input_hashes=ih, refs=Refs(entity_dispositions=batch.receipt_id, source_health=sh.receipt_id),
        body=LiveEvidenceBoard(compute_membership_hash(batch), dict(bo["counts"]),
                               int(bo["expected_count"]), str(prov["ordering_rule_id"]),
                               str(prov["ordering_rule_version"]))))


def run_shadow(builder_board_view: Any) -> dict:
    """Shadow/report-only. Returns a record; NEVER raises and NEVER mutates the input."""
    result = {
        "ok": False, "stage": "start", "error": None,
        "receipt_ids": {}, "membership_hash": None, "receipts_valid": None,
        "parity": {"membership": None, "ordering": None, "counts": None,
                   "source_health": None, "empty_state": None, "all": None},
        "diffs": [], "fail_closed": [],
    }
    try:
        bo = builder_board_view  # read-only; never assigned into
        prov = _require_provenance(bo if isinstance(bo, dict) else dict(bo))
        ih = _input_hashes(prov)
        batch = _build_batch(bo, prov, ih)
        sh = _build_source_health(bo, prov)
        board = _build_board(bo, prov, batch, sh, ih)
        result["receipt_ids"] = {"batch": batch.receipt_id, "board": board.receipt_id,
                                 "source_health": sh.receipt_id}
        result["membership_hash"] = board.body.membership_hash

        # FULL applicable validator set (existing suites; no duplicated logic).
        vchecks = [
            validate_receipt(batch), validate_receipt(sh), validate_receipt(board),
            validate_reason_usage(batch),
            validate_identity_collision(batch),
            validate_nested_conservation(batch, board),
            validate_count_reconciliation(board, batch),
            validate_hierarchical_references([batch, board, sh]),
            validate_canonical_replay(batch), validate_canonical_replay(sh),
            validate_canonical_replay(board),
        ]
        result["receipts_valid"] = all(v.ok for v in vchecks)
        for v in vchecks:
            result["diffs"].extend(v.errors)

        # Parity vs the builder's own declared board.
        builder_members = [r["team"] for r in bo["rows"] if r["leaf"] in _MEMBER]
        receipt_members = [r.identity.ext.get("team") for r in batch.body.rows
                           if isinstance(r.leaf, Leaf) and r.leaf.value in _MEMBER]
        tally: Dict[str, int] = {}
        for r in batch.body.rows:
            if isinstance(r.leaf, Leaf):
                tally[r.leaf.value] = tally.get(r.leaf.value, 0) + 1
        p = result["parity"]
        p["membership"] = set(builder_members) == set(receipt_members)
        p["ordering"] = builder_members == receipt_members
        p["counts"] = ({k: v for k, v in tally.items() if v}
                       == {k: v for k, v in dict(bo["counts"]).items() if v}
                       and int(bo["expected_count"]) == len(batch.body.rows))
        p["source_health"] = sh.body.state.value == bo["source_health_state"]
        members_n = len(receipt_members)
        p["empty_state"] = (members_n == 0) == bool(bo["empty_state"])
        p["all"] = all(v is True for k, v in p.items() if k != "all")

        # Source-health is fully fail-closed: a non-synchronized source can never yield
        # a healthy factual conclusion (members OR eligible/NONMEMBER). The honest board
        # disposition in those states is UNAVAILABLE/FAILED.
        synced = bo["source_health_state"] == HealthState.SYNCHRONIZED.value
        if not synced:
            result["fail_closed"].append(f"source_health_not_synchronized:{bo['source_health_state']}")
            if members_n > 0:
                result["fail_closed"].append("members_admitted_under_unhealthy_source")
            if any(r["leaf"] in _ELIGIBLE_OR_MEMBER for r in bo["rows"]):
                result["fail_closed"].append("eligible_conclusion_under_unhealthy_source")

        result["ok"] = bool(result["receipts_valid"] and p["all"] and synced
                            and not result["fail_closed"])
        result["stage"] = "complete"
    except Exception as exc:  # malformed input / missing provenance — recorded, never raised
        result["stage"] = "error"
        result["error"] = f"{type(exc).__name__}: {exc}"
        result["ok"] = False
    return result


__all__ = ["run_shadow"]
