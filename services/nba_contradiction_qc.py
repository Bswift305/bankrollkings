from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import pandas as pd


@dataclass(frozen=True)
class AuditResult:
    status: str
    rule: str
    player: str
    stat: str
    message: str
    featured: bool = False


RuleFn = Callable[[dict, dict], AuditResult | None]


def prop_key(prop: dict) -> tuple[str, str, str, str, str]:
    return (
        str(prop.get("player", "")).strip(),
        str(prop.get("team", "")).strip(),
        str(prop.get("stat", "")).strip().upper(),
        str(prop.get("direction", "")).strip().upper(),
        str(prop.get("line", "")).strip(),
    )


def fail(prop: dict, rule: str, message: str) -> AuditResult:
    return AuditResult("FAIL", rule, str(prop.get("player", "")), str(prop.get("stat", "")), message, bool(prop.get("_is_featured")))


def warn(prop: dict, rule: str, message: str) -> AuditResult:
    return AuditResult("WARN", rule, str(prop.get("player", "")), str(prop.get("stat", "")), message, bool(prop.get("_is_featured")))


def ok() -> AuditResult | None:
    return None


def hours_since(value) -> float | None:
    if value in (None, "", float("nan")):
        return None
    try:
        ts = pd.to_datetime(value, errors="coerce")
        if pd.isna(ts):
            return None
        now = pd.Timestamp.now(tz=ts.tz) if getattr(ts, "tzinfo", None) else pd.Timestamp.now()
        return float((now - ts).total_seconds()) / 3600.0
    except Exception:
        return None


def build_injury_context_age(injuries: pd.DataFrame | None, return_overrides: pd.DataFrame | None) -> float | None:
    freshness_pool: list[str] = []
    if injuries is not None and not injuries.empty and "Updated" in injuries.columns:
        freshness_pool.extend(injuries["Updated"].dropna().astype(str).tolist())
    if return_overrides is not None and not return_overrides.empty and "Updated" in return_overrides.columns:
        freshness_pool.extend(return_overrides["Updated"].dropna().astype(str).tolist())
    if not freshness_pool:
        return None
    freshest = pd.to_datetime(pd.Series(freshness_pool), errors="coerce").max()
    return hours_since(freshest)


def check_conflicted_in_featured(prop: dict, runtime: dict) -> AuditResult | None:
    verdict = str(prop.get("play_verdict", "PLAY") or "PLAY").upper()
    if prop.get("_is_featured") and verdict in {"CONFLICTED", "PASS"}:
        return fail(prop, "CONFLICTED_IN_FEATURED", f"Featured surface includes verdict {verdict}.")
    return ok()


def check_return_squeeze_over(prop: dict, runtime: dict) -> AuditResult | None:
    situations = {str(tag).strip().upper() for tag in (prop.get("situations") or []) if tag}
    direction = str(prop.get("direction", "")).upper()
    confidence = float(prop.get("confidence", 0) or 0)
    if "RETURN SQUEEZE" in situations and direction == "OVER":
        if prop.get("_is_featured"):
            return fail(prop, "RETURN_SQUEEZE_OVER", f"RETURN SQUEEZE active but featured OVER is still live at {confidence:.1f}.")
        if confidence >= 70:
            return warn(prop, "RETURN_SQUEEZE_OVER", f"RETURN SQUEEZE active and OVER still grades {confidence:.1f}.")
    return ok()


def check_role_down_promoted_over(prop: dict, runtime: dict) -> AuditResult | None:
    situations = {str(tag).strip().upper() for tag in (prop.get("situations") or []) if tag}
    direction = str(prop.get("direction", "")).upper()
    confidence = float(prop.get("confidence", 0) or 0)
    if direction == "OVER" and {"ROLE DOWN", "MIN-", "SHOT VOL-", "L5 FADE"} & situations:
        if prop.get("_is_featured"):
            return fail(prop, "ROLE_DOWN_PROMOTED_OVER", "Featured OVER conflicts with role-down or fade tags.")
        if confidence >= 72:
            return warn(prop, "ROLE_DOWN_PROMOTED_OVER", f"OVER still grades {confidence:.1f} despite role-down pressure.")
    return ok()


def check_minutes_negative_over_featured(prop: dict, runtime: dict) -> AuditResult | None:
    situations = {str(tag).strip().upper() for tag in (prop.get("situations") or []) if tag}
    direction = str(prop.get("direction", "")).upper()
    confidence = float(prop.get("confidence", 0) or 0)
    has_minutes_decline = bool({"MIN-", "TREND MIN-", "SNAP MIN-", "PROJ MIN-"} & situations)
    if direction == "OVER" and has_minutes_decline:
        if prop.get("_is_featured"):
            return fail(prop, "MIN_NEGATIVE_OVER_FEATURED", "Featured OVER conflicts with a negative minutes signal.")
        if confidence >= 72:
            return fail(prop, "MIN_NEGATIVE_OVER_BOARD", f"OVER still grades {confidence:.1f} despite negative minutes signals.")
    return ok()


def check_support_return_risk_featured(prop: dict, runtime: dict) -> AuditResult | None:
    role_label = str(prop.get("role_label", "") or "").strip().upper()
    direction = str(prop.get("direction", "")).upper()
    return_impact_pct = float(prop.get("return_impact_pct", 0) or 0)
    if role_label == "SUPPORT" and direction == "OVER" and return_impact_pct >= 6:
        if prop.get("_is_featured"):
            return fail(prop, "SUPPORT_RETURN_RISK_FEATURED", f"Support-role OVER is featured with return impact {return_impact_pct:.1f}.")
        if float(prop.get("confidence", 0) or 0) >= 68:
            return warn(prop, "SUPPORT_RETURN_RISK_FEATURED", f"Support-role OVER still grades high with return impact {return_impact_pct:.1f}.")
    return ok()


def check_run_conflict_promoted(prop: dict, runtime: dict) -> AuditResult | None:
    direction = str(prop.get("direction", "")).upper()
    current_run_side = str(prop.get("current_run_side", "")).strip().lower()
    current_streak = int(prop.get("current_streak", 0) or 0)
    run_conflict = (
        (direction == "OVER" and current_run_side == "under") or
        (direction == "UNDER" and current_run_side == "over")
    )
    if run_conflict and current_streak >= 2:
        if prop.get("_is_featured"):
            return fail(prop, "RUN_CONFLICT_FEATURED", f"Featured play conflicts with a {current_run_side} run of {current_streak}.")
        if float(prop.get("confidence", 0) or 0) >= 70:
            return warn(prop, "RUN_CONFLICT_PROMOTED", f"Confidence {float(prop.get('confidence', 0) or 0):.1f} survives a {current_run_side} run of {current_streak}.")
    return ok()


def check_sample_divergence(prop: dict, runtime: dict) -> AuditResult | None:
    live_over = prop.get("live_line_over_rate")
    live_under = prop.get("live_line_under_rate")
    weighted_over = prop.get("weighted_over_rate")
    weighted_under = prop.get("weighted_under_rate")
    direction = str(prop.get("direction", "")).upper()
    if direction == "OVER":
        live = float(live_over or 0) / 100 if live_over is not None else None
        weighted = float(weighted_over or 0) / 100 if weighted_over is not None else None
    else:
        live = float(live_under or 0) / 100 if live_under is not None else None
        weighted = float(weighted_under or 0) / 100 if weighted_under is not None else None
    if live is None or weighted is None:
        return ok()
    divergence = abs(live - weighted)
    if divergence >= 0.25 and prop.get("_is_featured"):
        return warn(prop, "SAMPLE_DIVERGENCE", f"Live-line and weighted playoff samples diverge by {divergence:.0%}.")
    return ok()


def check_stale_injury_state(prop: dict, runtime: dict) -> AuditResult | None:
    age = runtime.get("injury_context_age_hours")
    if age is None:
        return ok()
    situations = {str(tag).strip().upper() for tag in (prop.get("situations") or []) if tag}
    needs_fresh_context = bool({"RETURN RISK", "RETURN-", "RETURN SQUEEZE", "INJ BOOST"} & situations)
    if needs_fresh_context and prop.get("_is_featured") and age > 4:
        return fail(prop, "STALE_INJURY_STATE", f"Injury/return context is {age:.1f}h old on a featured prop.")
    if needs_fresh_context and age > 8:
        return fail(prop, "STALE_INJURY_STATE", f"Injury/return context is {age:.1f}h old.")
    return ok()


def check_market_gate_featured(prop: dict, runtime: dict) -> AuditResult | None:
    market_gate = str(prop.get("market_gate", "CLEAR") or "CLEAR").upper()
    if prop.get("_is_featured") and market_gate == "HOLD":
        return fail(prop, "MARKET_GATE_HOLD", "Featured prop is blocked by market gate HOLD.")
    if prop.get("_is_featured") and market_gate == "SPLIT MARKET":
        return warn(prop, "MARKET_GATE_SPLIT", "Featured prop still carries SPLIT MARKET risk.")
    return ok()


def check_volatility_featured(prop: dict, runtime: dict) -> AuditResult | None:
    volatility = str(prop.get("volatility_flag", "STABLE") or "STABLE").upper()
    confidence = float(prop.get("confidence", 0) or 0)
    if prop.get("_is_featured") and volatility == "HIGH":
        return fail(prop, "VOLATILITY_HIGH_FEATURED", "Featured prop carries HIGH volatility.")
    if prop.get("_is_featured") and volatility == "ELEVATED":
        return fail(prop, "VOLATILITY_ELEVATED_FEATURED", "Featured prop carries elevated volatility.")
    if not prop.get("_is_featured") and volatility in {"HIGH", "ELEVATED"} and confidence >= 75:
        return fail(prop, "VOLATILITY_ELEVATED_BOARD", f"{volatility.title()} volatility conflicts with a {confidence:.1f} confidence board play.")
    return ok()


def check_featured_min_confidence(prop: dict, runtime: dict) -> AuditResult | None:
    confidence = float(prop.get("confidence", 0) or 0)
    if prop.get("_is_featured") and confidence < 70:
        return fail(prop, "FEATURED_MIN_CONFIDENCE", f"Featured prop confidence is only {confidence:.1f}.")
    return ok()


RULES: tuple[RuleFn, ...] = (
    check_conflicted_in_featured,
    check_return_squeeze_over,
    check_role_down_promoted_over,
    check_minutes_negative_over_featured,
    check_support_return_risk_featured,
    check_run_conflict_promoted,
    check_sample_divergence,
    check_stale_injury_state,
    check_market_gate_featured,
    check_volatility_featured,
    check_featured_min_confidence,
)


WARNING_ESCALATION_PRIOR_RUNS: dict[str, int] = {
    "SAMPLE_DIVERGENCE": 1,
}


def audit_props(props: list[dict], runtime: dict | None = None, rules: tuple[RuleFn, ...] = RULES) -> dict:
    runtime = dict(runtime or {})
    failures: list[AuditResult] = []
    warnings: list[AuditResult] = []
    passes = 0
    warning_history = runtime.get("warning_history_map") or {}
    for prop in props:
        prop_failed = False
        for rule in rules:
            result = rule(prop, runtime)
            if result is None:
                continue
            if result.status == "WARN":
                history_key = (result.rule, result.player, result.stat, bool(result.featured))
                prior_runs = int(warning_history.get(history_key, 0) or 0)
                prior_run_threshold = int(WARNING_ESCALATION_PRIOR_RUNS.get(result.rule, 2))
                if prior_runs >= prior_run_threshold:
                    result = AuditResult(
                        "FAIL",
                        f"AGED_{result.rule}",
                        result.player,
                        result.stat,
                        f"{result.message} Warning has persisted for {prior_runs + 1} consecutive QC runs.",
                        result.featured,
                    )
            if result.status == "FAIL":
                failures.append(result)
                prop_failed = True
            elif result.status == "WARN":
                warnings.append(result)
        if not prop_failed:
            passes += 1
    return {
        "pass_count": passes,
        "warning_count": len(warnings),
        "failure_count": len(failures),
        "warnings": warnings,
        "failures": failures,
        "clean": len(failures) == 0,
    }
