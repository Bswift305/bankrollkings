"""Decision Integrity — dark NFL ATS pilot: the build_nfl_ats_wave shadow observer
(Phase 2C-dark local wiring, Rev 2).

`observe_build_nfl_ats_wave` is the SINGLE shared integration function. `build_nfl_ats_wave`
calls it on every return path; the QC calls the SAME function (no handwritten mirror).

It observes the builder's AUTHORITATIVE result — it does not recompute it:
  * membership and admitted ORDER come directly from `result['members']` (the builder's
    already-sorted output), rendered as RENDERED rows in that exact order;
  * the expected universe comes from `dec['per']`; each result member must resolve into it
    exactly once (drift between the sorted board and the decision universe fails closed);
  * remaining nonmembers are emitted in a deterministic canonical order (team-asc);
  * parity compares the RECEIPT membership/order against `result['members']` (passed to the
    adapter as `expected_members`), never against hook-derived rows.

Fail-closed health (the view itself carries the honest disposition): when the source is not
synchronized, every expected entity is UNAVAILABLE — no RENDERED/NONMEMBER streak leaves.

Clocks: `bk_captured` is the sidecar check clock; the source exposes no provider update clock
(null + NOT_PROVIDED); receipt `created_at` is captured SEPARATELY and is injectable for
deterministic replay. `content_fetched_at_utc` is a source-artifact clock and is NOT used as
the receipt creation time.

Governed evidence (collision-proof identity, build/config/rule versions, observation
sequence) is NEVER synthesized. The live call site passes `governed=None`, so the live ON
path records the governed-provenance gap (the runtime pilot is BLOCKED until those audited
sources exist). Tests pass a `governed` block to exercise the conformant mapping end to end.

OFF (default): returns None immediately — no view, no fingerprinting, no adapter/receipt
import, no work. Nothing is logged or persisted; the last record is exposed ONLY via the
internal test hook `last_record`.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from services.decision_shadow_boundary import shadow_enabled, shadow_if_enabled

_LAST: Dict[str, Any] = {}   # internal TEST hook only — never a log or a persisted store


def last_record() -> Optional[dict]:
    return _LAST.get("rec")


def _reset() -> None:
    _LAST.pop("rec", None)


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _identity(team: str, season: Any, governed: Optional[dict]) -> dict:
    gp = (governed or {}).get("identity_profiles", {}).get(team)
    if gp:  # governed collision evidence -> authoritative identity
        return {"quality": "DECLARED_COMPOSITE", "key": f"(nfl,{season},{team})",
                "base": {"sport": "nfl", "season": season}, "ext": {"team": team},
                "collision_tested": True, "profile": gp["profile"],
                "profile_version": gp["profile_version"], "collision_proof": gp["collision_proof"]}
    return {"quality": "NAME_ONLY", "key": team, "base": {"sport": "nfl", "season": season},
            "ext": {"team": team}, "collision_tested": False}


def _row(team, leaf, reason, season, governed):
    r = {"team": team, "leaf": leaf, "reason": reason, "identity": _identity(team, season, governed)}
    if governed and "reason_def_version" in governed:
        r["def_version"] = governed["reason_def_version"]
        if reason == "BELOW_THRESHOLD":
            r["params"] = {"threshold": governed.get("threshold", 3)}
    return r


def _board_view(result, dec, cur, season, governed, created_at) -> dict:
    sync = result["sync"]                                   # KeyError => isolated by caller
    synced = bool(sync.get("synchronized"))
    universe_teams = sorted((dec or {}).get("per", {}).keys())
    rows: List[dict] = []
    if not synced:
        # Fail-closed: no factual RENDERED/NONMEMBER under an unhealthy source.
        rows = [_row(t, "UNAVAILABLE", "SOURCE_UNAVAILABLE", season, governed) for t in universe_teams]
    else:
        members = result.get("members") or []              # AUTHORITATIVE order
        member_teams = [m["team"] for m in members]
        if len(set(member_teams)) != len(member_teams):
            raise ValueError("builder returned duplicate members")
        uni = set(universe_teams)
        for mt in member_teams:                              # each resolves into the universe once
            if universe_teams and mt not in uni:
                raise ValueError(f"builder member {mt!r} is not in the decision universe")
        rows = [_row(t, "RENDERED", "QUALIFIED", season, governed) for t in member_teams]
        rows += [_row(t, "NONMEMBER", "BELOW_THRESHOLD", season, governed)
                 for t in universe_teams if t not in set(member_teams)]
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
    if governed:
        view["provenance"] = {
            "build_id": governed["build_id"], "config_version": governed["config_version"],
            "rule_versions": governed["rule_versions"], "ordering_rule_id": "streak_desc_team_asc",
            "ordering_rule_version": governed["ordering_rule_version"],
            "source_fingerprints": [{"source_id": "nfl_games_parquet", "algorithm": "sha256",
                                     "digest": (cur or {}).get("content_sha256", "")}],
            "observation_seq": governed["observation_seq"]}
    return view


def observe_build_nfl_ats_wave(result: dict, dec: Optional[dict] = None, cur: Optional[dict] = None,
                               season: Any = None, governed: Optional[dict] = None,
                               created_at: Optional[str] = None) -> Optional[dict]:
    """The single shared observer. OFF => None (no work). Never raises; never mutates `result`.
    `created_at` (receipt creation) is injectable so replay fixtures are deterministic."""
    if not shadow_enabled():
        return None
    try:
        expected = [m["team"] for m in (result.get("members") or [])] if result.get(
            "sync", {}).get("synchronized") else []
        view = _board_view(result, dec, cur, season, governed, created_at or _utc_now())
        rec = shadow_if_enabled(view, expected_members=expected)
    except Exception as exc:
        rec = {"ok": False, "stage": "hook", "error": f"{type(exc).__name__}: {exc}"}
    _LAST["rec"] = rec
    return rec


__all__ = ["observe_build_nfl_ats_wave", "last_record"]
