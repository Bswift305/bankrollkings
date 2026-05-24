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


def check_support_only_featured(play: dict, runtime: dict) -> AuditResult | None:
    governance_tier = str(play.get("governance_tier", "") or "").strip().lower()
    trust_score = float(play.get("trust_score", play.get("fit_score", 0)) or 0)
    if play.get("_is_featured") and governance_tier in {"partial", "fade"}:
        return fail(play, "SUPPORT_ONLY_FEATURED", f"Featured CFB prop is still grading from a {governance_tier} support bucket.")
    if governance_tier == "partial" and trust_score >= 74:
        return warn(play, "PARTIAL_SUPPORT_BOARD", f"Partial-support CFB prop is still grading {trust_score:.1f}.")
    return ok()


def check_tight_support_featured(play: dict, runtime: dict) -> AuditResult | None:
    governance_tier = str(play.get("governance_tier", "") or "").strip().lower()
    stat_family = str(play.get("stat_family", "") or "").strip().lower()
    trust_score = float(play.get("trust_score", play.get("fit_score", 0)) or 0)
    if play.get("_is_featured") and governance_tier == "tight" and trust_score >= 78:
        return warn(play, "TIGHT_SUPPORT_FEATURED", f"Tight-support CFB prop is being promoted at {trust_score:.1f}.")
    if play.get("_is_featured") and governance_tier == "tight" and stat_family in {"passing", "receiving"} and trust_score >= 76:
        return fail(play, "TIGHT_YARDAGE_FEATURED", f"{play.get('stat')} still leans on a tight support bucket, which is too fragile for a lead CFB prop.")
    return ok()


def check_low_support_sample(play: dict, runtime: dict) -> AuditResult | None:
    resolved = int(play.get("governance_resolved", 0) or 0)
    if play.get("_is_featured") and resolved < 120:
        return fail(play, "LOW_SUPPORT_SAMPLE_FEATURED", f"Featured CFB prop only has {resolved} resolved support samples.")
    return ok()


def check_low_hit_rate_featured(play: dict, runtime: dict) -> AuditResult | None:
    hit_rate = float(play.get("governance_hit_rate", 0) or 0)
    trust_score = float(play.get("trust_score", play.get("fit_score", 0)) or 0)
    if play.get("_is_featured") and hit_rate > 0 and hit_rate < 50 and trust_score >= 72:
        return fail(play, "LOW_HIT_RATE_FEATURED", f"Featured CFB prop is coming from a support bucket hitting only {hit_rate:.1f}%.")
    return ok()


def check_single_book_featured(play: dict, runtime: dict) -> AuditResult | None:
    book_count = int(play.get("book_count", 0) or 0)
    trust_score = float(play.get("trust_score", play.get("fit_score", 0)) or 0)
    if play.get("_is_featured") and book_count <= 1 and trust_score >= 74:
        return warn(play, "SINGLE_BOOK_FEATURED", "Featured CFB prop is leaning on a single live book, so treat it as fragile support.")
    return ok()


RULES: tuple[RuleFn, ...] = (
    check_support_only_featured,
    check_tight_support_featured,
    check_low_support_sample,
    check_low_hit_rate_featured,
    check_single_book_featured,
)


WARNING_ESCALATION_PRIOR_RUNS: dict[str, int] = {
    "TIGHT_SUPPORT_FEATURED": 1,
    "SINGLE_BOOK_FEATURED": 1,
    "PARTIAL_SUPPORT_BOARD": 1,
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
