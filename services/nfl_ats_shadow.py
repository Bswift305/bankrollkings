"""Decision Integrity — dark NFL ATS pilot: the shadow adapter (Phase 2C-dark, Rev 3).

One adapter AROUND the existing NFL ATS builder. It consumes the builder's board output
as READ-ONLY data, builds Decision-Integrity receipts in shadow/report-only mode, runs the
full applicable existing validator set, and compares membership hash, ordering, counts,
source health, and empty-state disposition against the builder's output. It never mutates
the input, never persists, and never raises.

It FABRICATES NOTHING and COERCES NOTHING. The builder's board view must supply, in typed
governed form:
  * complete provenance (build id, config version, the NAMED rule versions `membership`
    and `ordering`, ordering rule id/version, STRUCTURED source fingerprints, observation
    sequence);
  * the three clocks separately — `created_at` (receipt creation), and a `clocks` block
    with `bk_captured`, `source_updated` + `source_updated_status`, `event_effective`;
  * per-row governed identity evidence (quality/key/base/ext + profile/version/collision
    proof), with booleans that are actual booleans.
Receipt ids are derived from the COMPLETE build context (a canonical fingerprint of the
entire view) so any materially-distinct build gets distinct immutable ids, while an
identical replay reproduces them. Any missing/malformed/coerced field fails closed.
"""

from __future__ import annotations

import hashlib
import json
import re
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
_NS = uuid.UUID("6f9619ff-8b86-4d01-b42d-00cf4fc964ff")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_FP_ALGORITHMS = frozenset({"sha256"})
_COMPOSITE = {"DECLARED_COMPOSITE", "COMPOSITE_NAME_EVENT"}


def _canonical(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, default=str, ensure_ascii=False)


def _build_fingerprint(bo: Dict[str, Any]) -> str:
    """A fingerprint of the ENTIRE governed build context (provenance, surface, universe,
    clocks, rows/counts/health — everything in the view). Any materially-distinct build
    yields a distinct fingerprint; an identical view reproduces it."""
    return hashlib.sha256(_canonical(bo).encode("utf-8")).hexdigest()


def _rid(build_fp: str, kind: str) -> str:
    return str(uuid.uuid5(_NS, f"{build_fp}:{kind}"))


def _require_provenance(bo: Dict[str, Any]) -> Dict[str, Any]:
    prov = bo.get("provenance")
    if not isinstance(prov, dict):
        raise ValueError("missing provenance block")
    for k in ("build_id", "config_version", "ordering_rule_id", "ordering_rule_version"):
        if not isinstance(prov.get(k), str) or not prov.get(k).strip():
            raise ValueError(f"provenance.{k} must be a non-empty string")
    rv = prov.get("rule_versions")
    if not isinstance(rv, dict):
        raise ValueError("provenance.rule_versions must be a map")
    for k in ("membership", "ordering"):  # named keys REQUIRED (not any int dict)
        if not isinstance(rv.get(k), int) or isinstance(rv.get(k), bool):
            raise ValueError(f"provenance.rule_versions['{k}'] must be an integer")
    obs = prov.get("observation_seq")
    if not isinstance(obs, int) or isinstance(obs, bool) or obs <= 0:
        raise ValueError("provenance.observation_seq must be a positive integer")
    _require_fingerprints(prov.get("source_fingerprints"))
    return prov


def _require_fingerprints(fps: Any) -> List[str]:
    """Structured, verifiable source fingerprints — not laundered label hashes. Each is
    {source_id, algorithm (allowlisted), digest (64 lowercase hex)}. Blank/malformed/
    duplicate/unsupported => fail closed. Returns the supplied verified digests directly."""
    if not isinstance(fps, list) or not fps:
        raise ValueError("provenance.source_fingerprints must be a non-empty list")
    digests, seen = [], set()
    for fp in fps:
        if not isinstance(fp, dict):
            raise ValueError("each source_fingerprint must be a mapping")
        sid, alg, dig = fp.get("source_id"), fp.get("algorithm"), fp.get("digest")
        if not isinstance(sid, str) or not sid.strip():
            raise ValueError("source_fingerprint.source_id must be a non-empty string")
        if alg not in _FP_ALGORITHMS:
            raise ValueError(f"source_fingerprint.algorithm {alg!r} is not allowlisted")
        if not isinstance(dig, str) or not _HEX64.match(dig):
            raise ValueError("source_fingerprint.digest must be 64 lowercase hex")
        if sid in seen:
            raise ValueError(f"duplicate source_fingerprint.source_id {sid!r}")
        seen.add(sid)
        digests.append(dig)
    return digests


def _clocks_from_view(bo: Dict[str, Any], *, event: bool) -> Clocks:
    """Build Clocks from the view's SEPARATE clock declarations. `as_of`/`created_at` is
    NEVER copied into bk_captured/source_updated/event_effective. Unknown source_updated
    stays null with its governed status; naive timestamps fail downstream validation."""
    clk = bo.get("clocks")
    if not isinstance(clk, dict):
        raise ValueError("missing clocks block")
    if "source_updated_status" not in clk or clk["source_updated_status"] not in \
            SourceUpdatedStatus.__members__:
        raise ValueError("clocks.source_updated_status must be PRESENT|UNKNOWN|NOT_PROVIDED")
    if not isinstance(clk.get("bk_captured"), str):
        raise ValueError("clocks.bk_captured must be provided (a string instant)")
    ee = clk.get("event_effective") if event else None
    return Clocks(bk_captured=clk["bk_captured"],
                  source_updated_status=SourceUpdatedStatus[clk["source_updated_status"]],
                  source_updated=clk.get("source_updated"), event_effective=ee)


def _identity_from_view(idv: Any) -> Identity:
    """Build the contract Identity from TYPE-VALIDATED, governed evidence. No coercion:
    booleans must be booleans, composite profiles must be present. A label-only identity
    (NAME_ONLY) is accepted structurally but fails closed as an admitted member downstream."""
    if not isinstance(idv, dict):
        raise ValueError("row identity must be a mapping")
    for f in ("quality", "key", "base"):
        if f not in idv:
            raise ValueError(f"row identity missing {f}")
    q = idv["quality"]
    if q not in IdentityQuality.__members__:
        raise ValueError(f"unknown identity quality {q!r}")
    if not isinstance(idv["key"], str) or not idv["key"].strip():
        raise ValueError("identity.key must be a non-empty string")
    base = idv["base"]
    if not isinstance(base, dict) or not base.get("sport") or not base.get("season"):
        raise ValueError("identity.base must be a map carrying sport + season")
    ext = idv.get("ext", {})
    if not isinstance(ext, dict):
        raise ValueError("identity.ext must be a map")
    ct = idv.get("collision_tested", False)
    if not isinstance(ct, bool):  # "false"/1 are NOT booleans — never coerce
        raise ValueError("identity.collision_tested must be an actual boolean")
    profile, pver, cproof = idv.get("profile"), idv.get("profile_version"), idv.get("collision_proof")
    if q in _COMPOSITE:
        if not ct:
            raise ValueError("composite identity requires collision_tested=true")
        for name, val in (("profile", profile), ("profile_version", pver), ("collision_proof", cproof)):
            if not isinstance(val, str) or not val.strip():
                raise ValueError(f"composite identity requires a non-empty {name}")
        if not ext.get("team"):
            raise ValueError("team composite identity requires ext.team")
    return Identity(IdentityGrain.TEAM, dict(base), dict(ext), IdentityQuality[q], ct,
                    idv["key"], profile, pver, cproof)


def _versions(prov: Dict[str, Any]) -> Versions:
    return Versions(prov["build_id"], prov["config_version"], dict(prov["rule_versions"]))


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
        ih = _require_fingerprints(prov["source_fingerprints"])  # verified digests, used directly
        if not isinstance(bo.get("created_at"), str):
            raise ValueError("missing created_at (receipt creation clock)")
        grain, uid, uver = bo["universe"]
        uni = Universe(grain, uid, uver)
        vers = _versions(prov)
        base_seq = prov["observation_seq"] * 10
        build_fp = _build_fingerprint(bo if isinstance(bo, dict) else dict(bo))

        rows = [EntityDisposition(r["team"], _identity_from_view(r["identity"]), Leaf(r["leaf"]),
                                  r["reason"], int(r["def_version"]), r.get("params"))
                for r in bo["rows"]]
        batch = seal_hashes(Receipt(
            receipt_id=_rid(build_fp, "entity_disposition"), receipt_kind=ReceiptKind.ENTITY_DISPOSITION,
            schema_version=SchemaVersion(1, 0), surface_id=bo["surface"], universe=uni,
            created_seq=base_seq + 1, created_at=bo["created_at"], versions=vers,
            replay_class=ReplayClass.EVIDENCE_EQUIVALENT, authority_class=AuthorityClass.FACT,
            projection=Projection.INTERNAL, clocks=_clocks_from_view(bo, event=True),
            input_hashes=ih, integrity=Integrity(), body=EntityDispositionBatch(rows)))
        sh = seal_hashes(Receipt(
            receipt_id=_rid(build_fp, "source_health"), receipt_kind=ReceiptKind.SOURCE_HEALTH,
            schema_version=SchemaVersion(1, 0), surface_id=bo["surface"], universe=uni,
            created_seq=base_seq, created_at=bo["created_at"], versions=vers,
            replay_class=ReplayClass.NON_REPLAYABLE, authority_class=AuthorityClass.DERIVED_CONTEXT,
            projection=Projection.INTERNAL, clocks=_clocks_from_view(bo, event=False), input_hashes=None,
            body=SourceHealthBody(HealthState(bo["source_health_state"]),
                                  bo["clocks"]["bk_captured"], {})))
        board = seal_hashes(Receipt(
            receipt_id=_rid(build_fp, "live_evidence"), receipt_kind=ReceiptKind.LIVE_EVIDENCE,
            schema_version=SchemaVersion(1, 0), surface_id=bo["surface"], universe=uni,
            created_seq=base_seq + 2, created_at=bo["created_at"], versions=vers,
            replay_class=ReplayClass.EVIDENCE_EQUIVALENT, authority_class=AuthorityClass.FACT,
            projection=Projection.INTERNAL, clocks=_clocks_from_view(bo, event=True), input_hashes=ih,
            refs=Refs(entity_dispositions=batch.receipt_id, source_health=sh.receipt_id),
            body=LiveEvidenceBoard(compute_membership_hash(batch), dict(bo["counts"]),
                                   int(bo["expected_count"]), prov["ordering_rule_id"],
                                   prov["ordering_rule_version"])))
        result["receipt_ids"] = {"batch": batch.receipt_id, "board": board.receipt_id,
                                 "source_health": sh.receipt_id}
        result["membership_hash"] = board.body.membership_hash

        vchecks = [
            validate_receipt(batch), validate_receipt(sh), validate_receipt(board),
            validate_reason_usage(batch), validate_identity_collision(batch),
            validate_nested_conservation(batch, board), validate_count_reconciliation(board, batch),
            validate_hierarchical_references([batch, board, sh]),
            validate_canonical_replay(batch), validate_canonical_replay(sh),
            validate_canonical_replay(board),
        ]
        result["receipts_valid"] = all(v.ok for v in vchecks)
        for v in vchecks:
            result["diffs"].extend(v.errors)

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
    except Exception as exc:
        result["stage"] = "error"
        result["error"] = f"{type(exc).__name__}: {exc}"
        result["ok"] = False
    return result


__all__ = ["run_shadow"]
