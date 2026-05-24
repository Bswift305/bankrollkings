from __future__ import annotations

from dataclasses import dataclass
from typing import Callable
import re


@dataclass(frozen=True)
class AuditResult:
    status: str
    rule: str
    player: str
    stat: str
    message: str
    featured: bool = False


RuleFn = Callable[[dict, dict], AuditResult | None]


def prop_key(prop: dict) -> tuple[str, str, str, str, str, str]:
    return (
        str(prop.get("player", "")).strip(),
        str(prop.get("team", "")).strip(),
        str(prop.get("stat", "")).strip().upper(),
        str(prop.get("direction", "")).strip().upper(),
        str(prop.get("line", "")).strip(),
        str(prop.get("matchup", "")).strip(),
    )


def fail(prop: dict, rule: str, message: str) -> AuditResult:
    return AuditResult("FAIL", rule, str(prop.get("player", "")), str(prop.get("stat", "")), message, bool(prop.get("_is_featured")))


def warn(prop: dict, rule: str, message: str) -> AuditResult:
    return AuditResult("WARN", rule, str(prop.get("player", "")), str(prop.get("stat", "")), message, bool(prop.get("_is_featured")))


def ok() -> AuditResult | None:
    return None


def _risk_score(prop: dict) -> float:
    for field in ("method_score", "market_confidence", "market_prob"):
        try:
            value = float(prop.get(field, 0) or 0)
        except Exception:
            value = 0.0
        if value > 0:
            return value
    return 0.0


def _range_gap(prop: dict) -> float:
    try:
        low = float(prop.get("line_low")) if prop.get("line_low") is not None else None
        high = float(prop.get("line_high")) if prop.get("line_high") is not None else None
    except Exception:
        low = high = None
    if low is None or high is None:
        return 0.0
    return abs(high - low)


def _trend_signal(prop: dict) -> tuple[str | None, int | None]:
    note = str(prop.get("trend_note", "") or "").strip().lower()
    if not note:
        return None, None
    sample_match = re.search(r"last\s+(\d+)\s+games?", note)
    sample_size = int(sample_match.group(1)) if sample_match else None
    if "stayed below" in note or "below " in note:
        return "UNDER", sample_size
    if "cleared" in note or "above " in note:
        return "OVER", sample_size
    return None, sample_size


def check_trend_direction_conflict(prop: dict, runtime: dict) -> AuditResult | None:
    direction = str(prop.get("direction", "")).strip().upper()
    trend_direction, sample_size = _trend_signal(prop)
    if trend_direction and trend_direction != direction and (sample_size or 3) >= 2:
        return fail(
            prop,
            "TREND_DIRECTION_CONFLICT",
            f"Trend note points {trend_direction} while the board is still showing {direction}.",
        )
    return ok()


def check_zero_required_under(prop: dict, runtime: dict) -> AuditResult | None:
    direction = str(prop.get("direction", "")).strip().upper()
    stat = str(prop.get("stat", "")).strip().upper()
    try:
        line = float(prop.get("line"))
    except Exception:
        line = None
    if direction == "UNDER" and stat in {"AST", "STL", "BLK"} and line is not None and line <= 0.5:
        return fail(
            prop,
            "ZERO_REQUIRED_UNDER",
            "Zero-required under: this ticket only cashes if the player records a literal zero.",
        )
    return ok()


def check_single_book_high_confidence(prop: dict, runtime: dict) -> AuditResult | None:
    try:
        book_count = int(prop.get("book_count", 0) or 0)
    except Exception:
        book_count = 0
    risk_score = _risk_score(prop)
    if book_count <= 1 and risk_score >= 75:
        if prop.get("_is_featured"):
            return fail(prop, "SINGLE_BOOK_HIGH_CONFIDENCE", f"Featured WNBA row is leaning on one book at {risk_score:.1f}.")
        return warn(prop, "SINGLE_BOOK_HIGH_CONFIDENCE", f"Single-book WNBA row still grades {risk_score:.1f}.")
    return ok()


def check_wide_line_range(prop: dict, runtime: dict) -> AuditResult | None:
    range_gap = _range_gap(prop)
    risk_score = _risk_score(prop)
    if range_gap >= 1.5 and risk_score >= 70:
        return fail(prop, "WIDE_LINE_RANGE", f"Book range is {range_gap:.1f}, too wide for a premium WNBA read.")
    if range_gap >= 1.0 and risk_score >= 68:
        return warn(prop, "WIDE_LINE_RANGE", f"Book range is {range_gap:.1f}, so this row needs caution.")
    return ok()


def check_low_sample_trend_featured(prop: dict, runtime: dict) -> AuditResult | None:
    trend_direction, sample_size = _trend_signal(prop)
    method_tags = {str(tag).strip().upper() for tag in (prop.get("method_tags") or []) if tag}
    if trend_direction and sample_size is not None and sample_size < 3 and (prop.get("_is_featured") or {"HOT HAND", "TREND READY"} & method_tags):
        return warn(prop, "LOW_SAMPLE_TREND", f"Trend support only covers the last {sample_size} games.")
    return ok()


RULES: tuple[RuleFn, ...] = (
    check_trend_direction_conflict,
    check_zero_required_under,
    check_single_book_high_confidence,
    check_wide_line_range,
    check_low_sample_trend_featured,
)


WARNING_ESCALATION_PRIOR_RUNS: dict[str, int] = {
    "SINGLE_BOOK_HIGH_CONFIDENCE": 1,
    "WIDE_LINE_RANGE": 1,
    "LOW_SAMPLE_TREND": 2,
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
