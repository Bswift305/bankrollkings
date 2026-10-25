"""Decision Integrity — dark NFL ATS pilot: the build_nfl_ats_wave call-site hook
(Phase 2C-dark local wiring).

Maps the REAL builder's inputs/results into the shadow adapter's board view and runs the
shadow in report-only mode. It is the only thing the `build_nfl_ats_wave` call site touches.

Boundaries:
  * Flag OFF (default) => `observe_nfl_ats_wave` returns None immediately: no view is
    constructed, no fingerprinting, no adapter/receipt import, no work. (The call site
    also checks the flag before importing this module.)
  * The view is built EXCLUSIVELY from real builder data. Governed evidence the builder
    does not provide — collision-proof identity, rule/build versions, observation sequence
    — is NOT synthesized; its absence makes the shadow fail closed. Teams without a
    supplied collision proof are honestly classified NAME_ONLY.
  * The builder's return value is never touched (read-only); shadow exceptions are isolated
    here and never propagate to the route.
  * Nothing is logged or persisted. The last shadow record is exposed ONLY through an
    internal test hook (`last_record`).

`governed` is an optional block a FUTURE builder enhancement would supply (collision
proofs + versions + observation sequence). The current builder passes it as None, so the
shadow records the governed-provenance gap rather than faking conformance.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from services.decision_shadow_boundary import shadow_enabled, shadow_if_enabled

_WAVE_MIN_STREAK = 3
_LAST: Dict[str, Any] = {}   # internal TEST hook only — never a log or a persisted store


def last_record() -> Optional[dict]:
    """Test-only accessor for the most recent shadow record."""
    return _LAST.get("rec")


def _reset() -> None:
    _LAST.pop("rec", None)


def _board_view(result: dict, dec: Optional[dict], cur: Optional[dict], season: Any,
                governed: Optional[dict]) -> dict:
    sync = result["sync"]                                  # KeyError here => isolated upstream
    health = "SYNCHRONIZED" if bool(sync.get("synchronized")) else "STALE"
    per = (dec or {}).get("per", {})
    rows, counts = [], {}
    gp_all = (governed or {}).get("identity_profiles", {})
    for team, s in per.items():
        cover = s.get("cover_streak", 0)
        leaf, reason = ("RENDERED", "QUALIFIED") if cover >= _WAVE_MIN_STREAK \
            else ("NONMEMBER", "BELOW_THRESHOLD")
        gp = gp_all.get(team)
        if gp:  # governed collision evidence supplied -> authoritative identity
            identity = {"quality": "DECLARED_COMPOSITE", "key": f"(nfl,{season},{team})",
                        "base": {"sport": "nfl", "season": season}, "ext": {"team": team},
                        "collision_tested": True, "profile": gp["profile"],
                        "profile_version": gp["profile_version"], "collision_proof": gp["collision_proof"]}
        else:   # no collision proof from the builder -> honest NAME_ONLY (fails closed as a member)
            identity = {"quality": "NAME_ONLY", "key": team,
                        "base": {"sport": "nfl", "season": season}, "ext": {"team": team},
                        "collision_tested": False}
        row = {"team": team, "leaf": leaf, "reason": reason, "identity": identity}
        if governed and "reason_def_version" in governed:
            row["def_version"] = governed["reason_def_version"]
            if reason == "BELOW_THRESHOLD":
                row["params"] = {"threshold": governed.get("threshold", _WAVE_MIN_STREAK)}
        rows.append(row)
        counts[leaf] = counts.get(leaf, 0) + 1

    view: Dict[str, Any] = {
        "sport": "nfl", "season": season, "surface": "nfl_ats_wave",
        "universe": ["team", f"nfl_ats_board_{season}", "v1"],
        "clocks": {"bk_captured": sync.get("checked_at_utc"), "source_updated": None,
                   "source_updated_status": "NOT_PROVIDED", "event_effective": None},
        "rows": rows, "counts": counts, "expected_count": len(rows),
        "empty_state": not any(r["leaf"] == "RENDERED" for r in rows),
        "source_health_state": health,
    }
    if sync.get("content_fetched_at_utc"):
        view["created_at"] = sync["content_fetched_at_utc"]   # real receipt-creation clock
    # Provenance ONLY from real governed inputs — never synthesized. Absent => fail closed.
    if governed:
        view["provenance"] = {
            "build_id": governed["build_id"], "config_version": governed["config_version"],
            "rule_versions": governed["rule_versions"],
            "ordering_rule_id": "streak_desc_team_asc",
            "ordering_rule_version": governed["ordering_rule_version"],
            "source_fingerprints": [{"source_id": "nfl_games_parquet", "algorithm": "sha256",
                                     "digest": (cur or {}).get("content_sha256", "")}],
            "observation_seq": governed["observation_seq"],
        }
    return view


def observe_nfl_ats_wave(result: dict, dec: Optional[dict] = None, cur: Optional[dict] = None,
                         season: Any = None, governed: Optional[dict] = None) -> Optional[dict]:
    """Called from build_nfl_ats_wave AFTER it computes its result. OFF => None (no work).
    Never raises; never mutates `result`."""
    if not shadow_enabled():
        return None                                  # zero work / imports when OFF
    try:
        view = _board_view(result, dec, cur, season, governed)
        rec = shadow_if_enabled(view)
    except Exception as exc:                          # isolate any hook/mapping failure
        rec = {"ok": False, "stage": "hook", "error": f"{type(exc).__name__}: {exc}"}
    _LAST["rec"] = rec
    return rec


__all__ = ["observe_nfl_ats_wave", "last_record"]
