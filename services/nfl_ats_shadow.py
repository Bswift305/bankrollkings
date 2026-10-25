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
    HealthState, canonical_identity, compute_membership_hash, seal_hashes, validate_receipt, _dumps,
)
from services.decision_validators import (
    validate_reason_usage, validate_identity_collision, validate_nested_conservation,
    validate_count_reconciliation, validate_hierarchical_references, validate_canonical_replay,
)

_MEMBER = {"RENDERED", "SUPPRESSED"}
_ELIGIBLE_OR_MEMBER = {"RENDERED", "SUPPRESSED", "NONMEMBER"}
# This adapter is NFL-ATS-specific: the declared surface/sport/universe profile it binds to.
_EXPECTED_SPORT = "nfl"
_EXPECTED_SURFACE = "nfl_ats_wave"
_EXPECTED_GRAIN = "team"
_NFL_ATS_BOARD_ID = re.compile(r"^nfl_ats_board_\d{4}$")
_NS = uuid.UUID("6f9619ff-8b86-4d01-b42d-00cf4fc964ff")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_FP_ALGORITHMS = frozenset({"sha256"})
_COMPOSITE = {"DECLARED_COMPOSITE", "COMPOSITE_NAME_EVENT"}


def _canonical(obj: Any) -> str:
    # No `default=` — an unsupported object raises TypeError rather than being silently
    # stringified into something that would influence immutable receipt ids.
    return json.dumps(obj, sort_keys=True, ensure_ascii=False)


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


_LEAF_VALUES = frozenset(l.value for l in Leaf)


def _int(v, name):
    if not isinstance(v, int) or isinstance(v, bool):
        raise ValueError(f"{name} must be an integer (got {type(v).__name__})")
    return v


def _bool(v, name):
    if not isinstance(v, bool):
        raise ValueError(f"{name} must be a boolean (got {type(v).__name__})")
    return v


def _str(v, name):
    if not isinstance(v, str) or not v.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return v


def _validate_identity_shape(idv: Any) -> None:
    if not isinstance(idv, dict):
        raise ValueError("row identity must be a mapping")
    for f in ("quality", "key", "base"):
        if f not in idv:
            raise ValueError(f"row identity missing {f}")
    if idv["quality"] not in IdentityQuality.__members__:
        raise ValueError(f"unknown identity quality {idv['quality']!r}")
    _str(idv["key"], "identity.key")
    base = idv["base"]
    if not isinstance(base, dict) or not base.get("sport") or not base.get("season"):
        raise ValueError("identity.base must be a map carrying sport + season")
    if not isinstance(idv.get("ext", {}), dict):
        raise ValueError("identity.ext must be a map")
    _bool(idv.get("collision_tested", False), "identity.collision_tested")
    if idv["quality"] in _COMPOSITE:
        if idv.get("collision_tested") is not True:
            raise ValueError("composite identity requires collision_tested=true")
        for name in ("profile", "profile_version", "collision_proof"):
            _str(idv.get(name), f"composite identity.{name}")
        if not idv.get("ext", {}).get("team"):
            raise ValueError("team composite identity requires ext.team")


def _validate_board_view(bo: Any) -> None:
    """STRICT input-contract boundary. Runs BEFORE fingerprinting or receipt construction.
    Every governed field must already be the correct type — nothing is coerced. Any
    violation raises ValueError, so the shadow fails at the input stage and returns no
    receipt ids."""
    if not isinstance(bo, dict):
        raise ValueError("board view must be a mapping")
    _str(bo.get("sport"), "sport")
    _str(bo.get("surface"), "surface")
    board_season = _int(bo.get("season"), "season")
    _str(bo.get("created_at"), "created_at")
    uni = bo.get("universe")
    if not isinstance(uni, (list, tuple)) or len(uni) != 3:
        raise ValueError("universe must be [grain, id, version]")
    for i, part in enumerate(uni):
        _str(part, f"universe[{i}]")
    # NFL-ATS surface/sport/universe binding (this adapter is surface-specific).
    if bo["sport"] != _EXPECTED_SPORT:
        raise ValueError(f"sport must be {_EXPECTED_SPORT!r} for the NFL ATS adapter")
    if bo["surface"] != _EXPECTED_SURFACE:
        raise ValueError(f"surface must be {_EXPECTED_SURFACE!r} for the NFL ATS adapter")
    grain_, uid_, _uver = uni
    if grain_ != _EXPECTED_GRAIN:
        raise ValueError(f"NFL ATS universe grain must be {_EXPECTED_GRAIN!r} (got {grain_!r})")
    if not _NFL_ATS_BOARD_ID.match(uid_):
        raise ValueError("NFL ATS universe id must be the declared board family nfl_ats_board_<year>")
    if uid_ != f"nfl_ats_board_{board_season}":
        raise ValueError(f"universe id {uid_!r} must match the board season {board_season}")
    # clocks
    clk = bo.get("clocks")
    if not isinstance(clk, dict):
        raise ValueError("clocks must be a mapping")
    _str(clk.get("bk_captured"), "clocks.bk_captured")
    if clk.get("source_updated_status") not in SourceUpdatedStatus.__members__:
        raise ValueError("clocks.source_updated_status must be PRESENT|UNKNOWN|NOT_PROVIDED")
    for k in ("source_updated", "event_effective"):
        if clk.get(k) is not None and not isinstance(clk.get(k), str):
            raise ValueError(f"clocks.{k} must be a string instant or null")
    # provenance (+ structured fingerprints)
    _require_provenance(bo)
    # source health
    if bo.get("source_health_state") not in HealthState.__members__:
        raise ValueError("source_health_state must be SYNCHRONIZED|STALE|FAIL_CLOSED")
    _bool(bo.get("empty_state"), "empty_state")
    # rows
    rows = bo.get("rows")
    if not isinstance(rows, list):
        raise ValueError("rows must be a list")
    seen_identity = {}
    for i, r in enumerate(rows):
        if not isinstance(r, dict):
            raise ValueError(f"rows[{i}] must be a mapping")
        _str(r.get("team"), f"rows[{i}].team")
        _str(r.get("leaf"), f"rows[{i}].leaf")
        if r["leaf"] not in _LEAF_VALUES:
            raise ValueError(f"rows[{i}].leaf {r['leaf']!r} is not a terminal leaf")
        _str(r.get("reason"), f"rows[{i}].reason")
        _int(r.get("def_version"), f"rows[{i}].def_version")
        if "params" in r and not isinstance(r["params"], dict):
            raise ValueError(f"rows[{i}].params must be a mapping")
        _validate_identity_shape(r.get("identity"))
        # Cross-field identity integrity: the identity must describe the SAME entity and
        # universe as the row/board (not merely be individually well-typed).
        idv = r["identity"]
        if idv["base"].get("sport") != bo["sport"]:
            raise ValueError(f"rows[{i}] identity.base.sport {idv['base'].get('sport')!r} != board "
                             f"sport {bo['sport']!r}")
        isn = idv["base"].get("season")
        if not isinstance(isn, int) or isinstance(isn, bool) or isn != board_season:
            raise ValueError(f"rows[{i}] identity.base.season must be a non-boolean integer equal to "
                             f"the board season {board_season}")
        et = idv.get("ext", {}).get("team")
        if idv["quality"] in _COMPOSITE or et is not None:
            if not isinstance(et, str) or not et.strip() or et != r["team"]:
                raise ValueError(f"rows[{i}] identity.ext.team {et!r} must equal the row team "
                                 f"{r['team']!r}")
        # Canonical identity uniqueness across EVERY row (members and nonmembers alike).
        ci = _dumps(canonical_identity(_identity_from_view(idv)))
        if ci in seen_identity:
            raise ValueError(f"rows[{i}] duplicate canonical identity (also rows[{seen_identity[ci]}]) "
                             "— exactly one row per canonical identity")
        seen_identity[ci] = i
    # counts: non-negative ints keyed only by terminal leaf values
    counts = bo.get("counts")
    if not isinstance(counts, dict):
        raise ValueError("counts must be a mapping")
    for k, v in counts.items():
        if k not in _LEAF_VALUES:
            raise ValueError(f"counts key {k!r} is not a terminal leaf value")
        _int(v, f"counts[{k!r}]")
        if v < 0:
            raise ValueError(f"counts[{k!r}] must be non-negative")
    exp = _int(bo.get("expected_count"), "expected_count")
    if exp != sum(counts.values()):
        raise ValueError(f"expected_count {exp} != sum(counts) {sum(counts.values())}")
    # JSON-serializable (no coercion): reject unsupported objects up front.
    try:
        _canonical(bo)
    except TypeError as exc:
        raise ValueError(f"board view is not JSON-serializable: {exc}")


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


def _identity_from_view(idv: Dict[str, Any]) -> Identity:
    """Build the contract Identity from already-type-validated governed evidence
    (see _validate_identity_shape). No coercion: values are used as supplied."""
    _validate_identity_shape(idv)
    return Identity(IdentityGrain.TEAM, dict(idv["base"]), dict(idv.get("ext", {})),
                    IdentityQuality[idv["quality"]], idv.get("collision_tested", False),
                    idv["key"], idv.get("profile"), idv.get("profile_version"),
                    idv.get("collision_proof"))


def _versions(prov: Dict[str, Any]) -> Versions:
    return Versions(prov["build_id"], prov["config_version"], dict(prov["rule_versions"]))


def run_shadow(builder_board_view: Any, expected_members: Any = None) -> dict:
    """Shadow/report-only. Returns a record; NEVER raises and NEVER mutates the input.
    `expected_members`, when provided, is the builder's AUTHORITATIVE admitted-member order;
    parity then compares the RECEIPT membership/order against it (not against the view rows)."""
    result = {
        "ok": False, "stage": "start", "error": None,
        "receipt_ids": {}, "membership_hash": None, "receipts_valid": None,
        "parity": {"membership": None, "ordering": None, "counts": None,
                   "source_health": None, "empty_state": None, "all": None},
        "diffs": [], "fail_closed": [],
    }
    try:
        bo = builder_board_view  # read-only; never assigned into
        _validate_board_view(bo)   # strict input contract — before fingerprint/receipts
        prov = bo["provenance"]
        ih = _require_fingerprints(prov["source_fingerprints"])  # verified digests, used directly
        grain, uid, uver = bo["universe"]
        uni = Universe(grain, uid, uver)
        vers = _versions(prov)
        base_seq = prov["observation_seq"] * 10
        build_fp = _build_fingerprint(bo if isinstance(bo, dict) else dict(bo))

        rows = [EntityDisposition(r["team"], _identity_from_view(r["identity"]), Leaf(r["leaf"]),
                                  r["reason"], r["def_version"], r.get("params"))
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
                                   bo["expected_count"], prov["ordering_rule_id"],
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
                       and bo["expected_count"] == len(batch.body.rows))
        p["source_health"] = sh.body.state.value == bo["source_health_state"]
        members_n = len(receipt_members)
        p["empty_state"] = (members_n == 0) == bo["empty_state"]
        # Authoritative parity: the RECEIPT membership/order vs the builder's own members
        # (closes the circularity — not a comparison against hook-derived rows).
        if expected_members is not None:
            p["builder_membership"] = set(receipt_members) == set(expected_members)
            p["builder_ordering"] = receipt_members == list(expected_members)
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
