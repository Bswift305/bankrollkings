from __future__ import annotations

from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True)
class AuditResult:
    status: str
    rule: str
    player: str
    stat: str
    message: str
    featured: bool = False


RuleFn = Callable[[dict, dict], AuditResult | None]


def fail(play: dict, rule: str, message: str) -> AuditResult:
    return AuditResult("FAIL", rule, str(play.get("player", "")), str(play.get("stat", "")), message, bool(play.get("_is_featured")))


def warn(play: dict, rule: str, message: str) -> AuditResult:
    return AuditResult("WARN", rule, str(play.get("player", "")), str(play.get("stat", "")), message, bool(play.get("_is_featured")))


def ok() -> AuditResult | None:
    return None


def game_script_tags(play: dict) -> set[str]:
    raw_values = [
        play.get("game_script_tags"),
        play.get("game_tags"),
        play.get("GameScriptTags"),
        play.get("situations"),
    ]
    tags: set[str] = set()
    for raw in raw_values:
        if isinstance(raw, (list, tuple, set)):
            parts = raw
        else:
            parts = str(raw or "").replace(",", "|").split("|")
        for part in parts:
            tag = str(part or "").strip().upper().replace(" ", "_")
            if tag:
                tags.add(tag)
    return tags


def play_direction(play: dict) -> str:
    return str(play.get("direction", play.get("Direction", "")) or "").strip().upper()


def check_partial_support_featured(play: dict, runtime: dict) -> AuditResult | None:
    governance_tier = str(play.get("governance_tier", "") or "").strip().lower()
    trust_score = float(play.get("trust_score", 0) or 0)
    if play.get("_is_featured") and governance_tier in {"partial", "fade"}:
        return fail(play, "PARTIAL_SUPPORT_FEATURED", f"Featured NFL play carries governance tier {governance_tier}.")
    if governance_tier == "partial" and trust_score >= 80:
        return warn(play, "PARTIAL_SUPPORT_BOARD", f"Partial-support NFL play still grades {trust_score:.1f}.")
    return ok()


def check_tight_support_featured(play: dict, runtime: dict) -> AuditResult | None:
    governance_tier = str(play.get("governance_tier", "") or "").strip().lower()
    trust_score = float(play.get("trust_score", 0) or 0)
    if play.get("_is_featured") and governance_tier == "tight" and trust_score >= 80:
        return warn(play, "TIGHT_SUPPORT_FEATURED", f"Tight-support NFL play is featured at {trust_score:.1f}.")
    return ok()


def check_tight_support_yardage_featured(play: dict, runtime: dict) -> AuditResult | None:
    governance_tier = str(play.get("governance_tier", "") or "").strip().lower()
    stat = str(play.get("stat", "") or "").strip()
    trust_score = float(play.get("trust_score", 0) or 0)
    if play.get("_is_featured") and governance_tier == "tight" and stat in {"Rec Yds", "Rush Yds", "Pass Yds"} and trust_score >= 78:
        return fail(
            play,
            "TIGHT_SUPPORT_YARDAGE_FEATURED",
            f"{stat} is still leaning on a tight-support bucket at {trust_score:.1f}, which is too fragile to feature cleanly.",
        )
    return ok()


def check_low_hit_rate_featured(play: dict, runtime: dict) -> AuditResult | None:
    hit_rate = float(play.get("governance_hit_rate", 0) or 0)
    trust_score = float(play.get("trust_score", 0) or 0)
    if play.get("_is_featured") and hit_rate > 0 and hit_rate < 50 and trust_score >= 78:
        return fail(
            play,
            "LOW_HIT_RATE_FEATURED",
            f"Featured NFL play is coming from a support bucket that is only hitting {hit_rate:.1f}%.",
        )
    return ok()


def check_fade_board_score(play: dict, runtime: dict) -> AuditResult | None:
    governance_tier = str(play.get("governance_tier", "") or "").strip().lower()
    trust_score = float(play.get("trust_score", 0) or 0)
    if governance_tier == "fade" and trust_score >= 72:
        if play.get("_is_featured"):
            return fail(play, "FADE_FEATURED", f"Featured NFL play still carries a fade governance tier at {trust_score:.1f}.")
        return warn(play, "FADE_BOARD_SCORE", f"Fade-tier NFL play still grades {trust_score:.1f}.")
    return ok()


def check_minimum_support_sample(play: dict, runtime: dict) -> AuditResult | None:
    resolved = int(play.get("governance_resolved", 0) or 0)
    if play.get("_is_featured") and resolved < 100:
        return fail(play, "LOW_SUPPORT_SAMPLE_FEATURED", f"Featured NFL play only has {resolved} resolved support samples.")
    return ok()


def check_trailing_rush_over(play: dict, runtime: dict) -> AuditResult | None:
    stat = str(play.get("stat", "") or "").strip().upper()
    direction = play_direction(play)
    trust_score = float(play.get("trust_score", 0) or 0)
    tags = game_script_tags(play)
    if stat == "RUSH YDS" and direction == "OVER" and {"PROJECTED_TRAIL", "PROJECTED_BLOWOUT_TRAIL"} & tags and trust_score >= 65:
        return warn(
            play,
            "TRAILING_RUSH_OVER_RISK",
            "Team is projected to trail, so rushing volume can disappear if game script goes pass-heavy.",
        )
    return ok()


def check_wind_pass_or_receiver_over(play: dict, runtime: dict) -> AuditResult | None:
    stat = str(play.get("stat", "") or "").strip().upper()
    direction = play_direction(play)
    trust_score = float(play.get("trust_score", 0) or 0)
    tags = game_script_tags(play)
    if stat in {"PASS YDS", "REC YDS"} and direction == "OVER" and "WIND_15_PLUS" in tags and trust_score >= 65:
        return warn(
            play,
            "WIND_PASS_OVER_RISK",
            "Wind is 15+ mph, which historically pressures passing and receiving yardage overs.",
        )
    return ok()


def check_blowout_pass_over(play: dict, runtime: dict) -> AuditResult | None:
    stat = str(play.get("stat", "") or "").strip().upper()
    direction = play_direction(play)
    trust_score = float(play.get("trust_score", 0) or 0)
    tags = game_script_tags(play)
    if stat in {"PASS YDS", "PASS ATT", "PASS COMP"} and direction == "OVER" and {"PROJECTED_CLEAR_WIN", "PROJECTED_BLOWOUT_WIN"} & tags and trust_score >= 72:
        return warn(
            play,
            "BLOWOUT_PASS_OVER_RISK",
            "Projected comfortable win can reduce late passing volume if the team shifts into clock control.",
        )
    return ok()


RULES: tuple[RuleFn, ...] = (
    check_partial_support_featured,
    check_tight_support_featured,
    check_tight_support_yardage_featured,
    check_low_hit_rate_featured,
    check_fade_board_score,
    check_minimum_support_sample,
    check_trailing_rush_over,
    check_wind_pass_or_receiver_over,
    check_blowout_pass_over,
)


WARNING_ESCALATION_PRIOR_RUNS: dict[str, int] = {
    "TIGHT_SUPPORT_FEATURED": 1,
    "FADE_BOARD_SCORE": 1,
}


def audit_plays(plays: list[dict], runtime: dict | None = None, rules: tuple[RuleFn, ...] = RULES) -> dict:
    runtime = dict(runtime or {})
    failures: list[AuditResult] = []
    warnings: list[AuditResult] = []
    passes = 0
    warning_history = runtime.get("warning_history_map") or {}
    for play in plays:
        play_failed = False
        for rule in rules:
            result = rule(play, runtime)
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
                play_failed = True
            elif result.status == "WARN":
                warnings.append(result)
        if not play_failed:
            passes += 1
    return {
        "pass_count": passes,
        "warning_count": len(warnings),
        "failure_count": len(failures),
        "warnings": warnings,
        "failures": failures,
        "clean": len(failures) == 0,
    }
