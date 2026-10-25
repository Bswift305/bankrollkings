"""Decision Integrity — dark NFL ATS pilot: the build_nfl_ats_wave shadow observer
(Phase 2C-dark local wiring, Rev 3).

`observe_build_nfl_ats_wave` is the SINGLE shared observer. `build_nfl_ats_wave` calls it on
every return path (only after a dependency-free flag check, so OFF imports nothing here); the
QC calls the SAME function (no mirror).

It observes the builder's AUTHORITATIVE result and INVENTS NOTHING:
  * membership + admitted ORDER come from `result['members']`; the expected universe comes
    from `dec['per']`; EVERY member must exist in that universe unconditionally (a missing or
    empty universe fails closed — `expected_universe_unavailable`);
  * remaining nonmembers are emitted in a deterministic team-asc order;
  * `sync['synchronized']` must be an ACTUAL boolean (no coercion); a non-synchronized source
    makes every expected entity UNAVAILABLE (no factual RENDERED/NONMEMBER);
  * governed rules are REQUIRED from the builder contract — `ordering_rule_id`,
    `ordering_rule_version`, `membership_threshold`, `reason_def_version` (plus identity
    profiles, build/config/rule versions, observation sequence). The hook hardcodes/defaults
    none of them, and cross-checks `membership_threshold` against the real builder constant
    passed by the call site (`builder_rules`).

The live call site passes `governed=None`, so the live ON path fails closed on missing
governed provenance (runtime pilot BLOCKED). `created_at` (receipt creation) is injectable for
deterministic replay. OFF (default): the observer returns None (and app.py does not even
import this module). Nothing is logged/persisted; the last record is exposed only via
`last_record` for tests.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from services.decision_shadow_boundary import shadow_enabled, shadow_if_enabled

_LAST: Dict[str, Any] = {}
_GOV_REQUIRED = ("build_id", "config_version", "rule_versions", "ordering_rule_id",
                 "ordering_rule_version", "membership_threshold", "reason_def_version",
                 "observation_seq", "identity_profiles")


def last_record() -> Optional[dict]:
    return _LAST.get("rec")


def _reset() -> None:
    _LAST.pop("rec", None)


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _finding(tag: str) -> dict:
    return {"ok": False, "stage": "complete", "error": None, "receipt_ids": {},
            "membership_hash": None, "receipts_valid": None,
            "parity": {"membership": None, "ordering": None, "counts": None,
                       "source_health": None, "empty_state": None, "all": None},
            "diffs": [], "fail_closed": [tag]}


def _identity(team: str, season: Any, governed: Optional[dict]) -> dict:
    gp = (governed or {}).get("identity_profiles", {}).get(team)
    if gp:
        return {"quality": "DECLARED_COMPOSITE", "key": f"(nfl,{season},{team})",
                "base": {"sport": "nfl", "season": season}, "ext": {"team": team},
                "collision_tested": True, "profile": gp["profile"],
                "profile_version": gp["profile_version"], "collision_proof": gp["collision_proof"]}
    return {"quality": "NAME_ONLY", "key": team, "base": {"sport": "nfl", "season": season},
            "ext": {"team": team}, "collision_tested": False}


def _row(team, leaf, reason, season, governed):
    r = {"team": team, "leaf": leaf, "reason": reason, "identity": _identity(team, season, governed)}
    if governed:  # def_version / threshold come from the governed contract, never defaulted
        r["def_version"] = governed["reason_def_version"]
        if reason == "BELOW_THRESHOLD":
            r["params"] = {"threshold": governed["membership_threshold"]}
    return r


def _board_view(result, dec, cur, season, governed, builder_rules, created_at,
                universe_teams) -> dict:
    sync = result["sync"]
    raw = sync.get("synchronized")
    if not isinstance(raw, bool):   # no coercion — "false"/1 are not booleans
        raise ValueError("sync.synchronized must be an actual boolean")
    synced = raw
    uni = set(universe_teams)
    if governed is not None:
        missing = [k for k in _GOV_REQUIRED if k not in governed]
        if missing:
            raise ValueError(f"governed contract missing {missing}")
        if builder_rules is not None and \
                governed["membership_threshold"] != builder_rules.get("membership_threshold"):
            raise ValueError("governed.membership_threshold does not match the builder constant")
    if synced:
        members = result.get("members") or []
        member_teams = [m["team"] for m in members]
        if len(set(member_teams)) != len(member_teams):
            raise ValueError("builder returned duplicate members")
        for mt in member_teams:        # unconditional — no empty-universe bypass
            if mt not in uni:
                raise ValueError(f"builder member {mt!r} is not in the decision universe")
        rows = [_row(t, "RENDERED", "QUALIFIED", season, governed) for t in member_teams]
        rows += [_row(t, "NONMEMBER", "BELOW_THRESHOLD", season, governed)
                 for t in universe_teams if t not in set(member_teams)]
    else:
        rows = [_row(t, "UNAVAILABLE", "SOURCE_UNAVAILABLE", season, governed) for t in universe_teams]
    counts: Dict[str, int] = {}
    for r in rows:
        counts[r["leaf"]] = counts.get(r["leaf"], 0) + 1
    view: Dict[str, Any] = {
        "sport": "nfl", "season": season, "surface": "nfl_ats_wave",
        "universe": ["team", f"nfl_ats_board_{season}", "v1"], "created_at": created_at,
        "clocks": {"bk_captured": sync.get("checked_at_utc"), "source_updated": None,
                   "source_updated_status": "NOT_PROVIDED", "event_effective": None},
        "rows": rows, "counts": counts, "expected_count": len(rows),
        "empty_state": not any(r["leaf"] == "RENDERED" for r in rows),
        "source_health_state": "SYNCHRONIZED" if synced else "STALE",
    }
    if governed is not None:
        view["provenance"] = {
            "build_id": governed["build_id"], "config_version": governed["config_version"],
            "rule_versions": governed["rule_versions"],
            "ordering_rule_id": governed["ordering_rule_id"],          # from contract, not invented
            "ordering_rule_version": governed["ordering_rule_version"],
            "source_fingerprints": [{"source_id": "nfl_games_parquet", "algorithm": "sha256",
                                     "digest": (cur or {}).get("content_sha256", "")}],
            "observation_seq": governed["observation_seq"]}
    return view


def observe_build_nfl_ats_wave(result: dict, dec: Optional[dict] = None, cur: Optional[dict] = None,
                               season: Any = None, governed: Optional[dict] = None,
                               builder_rules: Optional[dict] = None,
                               created_at: Optional[str] = None) -> Optional[dict]:
    """Single shared observer. OFF => None. Never raises; never mutates `result`."""
    if not shadow_enabled():
        return None
    try:
        universe_teams = sorted((dec or {}).get("per", {}).keys())
        if not universe_teams:
            # No audited independent NFL-team universe => cannot be a conserved empty board.
            rec = _finding("expected_universe_unavailable")
        else:
            synced = result.get("sync", {}).get("synchronized") is True
            expected = [m["team"] for m in (result.get("members") or [])] if synced else []
            view = _board_view(result, dec, cur, season, governed, builder_rules,
                               created_at or _utc_now(), universe_teams)
            rec = shadow_if_enabled(view, expected_members=expected)
    except Exception as exc:
        rec = {"ok": False, "stage": "hook", "error": f"{type(exc).__name__}: {exc}"}
    _LAST["rec"] = rec
    return rec


__all__ = ["observe_build_nfl_ats_wave", "last_record"]
