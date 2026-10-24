"""Strong semantic validation for an Odds feed artifact, run on the TEMP frame BEFORE atomic replacement.

"Required columns + one row" is too weak. This validates the things that actually make a current-market
artifact trustworthy, so a structurally-wrong fetch can never replace last-known-good (incident
2026-10-23). A FeedSpec describes one feed; validate_feed(df, spec, prior_df, path) returns (ok, errors).

Pure: pandas + stdlib only, no app import. The atomic publish calls this; a non-empty error list means
leave the previous bytes unchanged.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class FeedSpec:
    kind: str                                   # "game_lines" | "player_props" | "futures"
    required_cols: tuple = ()                   # must all be present
    numeric_cols: tuple = ()                    # non-null values must parse to FINITE numbers
    timestamp_col: str = ""                     # must parse (UTC-aware or naive) on non-null
    id_cols: tuple = ()                         # a (…id…) key that must not carry CONFLICTING duplicates
    value_cols: tuple = ()                      # the value columns a duplicate key must agree on
    side_col: str = ""                          # e.g. direction / Side
    allowed_sides: tuple = ()                   # permitted side values (case-insensitive)
    identity_cols: tuple = ()                   # event/player identity that must be non-empty on every row
    min_rows: int = 1                           # a current-season/slate slice must not be empty
    path_sport_tokens: tuple = ()               # the output filename must contain one of these (sport match)
    collapse_ratio: float = 0.5                 # len < ratio*len(prior) is an implausible collapse (needs override)
    # --- slate-aware baseline model (opt-in; incident 2026-10-24 NBA current-slate contract) ---
    slate_aware: bool = False                   # when True, validate_feed_slate() picks COMPARABLE_PRIOR vs CURRENT_SLATE
    event_col: str = "Game"                     # distinct-event column used for slate reconciliation
    market_col: str = "MarketKey"               # market-set comparability
    book_col: str = "Book"                      # bookmaker-set comparability
    comparable_prior_max_age_hours: float = 0.0 # a prior OLDER than this is NOT a comparable baseline
    comparable_event_ratio: float = 0.5         # event counts within this ratio of each other are "similar"
    event_coverage_min: float = 1.0             # fraction of eligible (markets-posted) events that must have rows
    rows_per_event_min: float = 0.0             # normalized density floor in CURRENT_SLATE mode


def _finite_series(s):
    v = pd.to_numeric(s, errors="coerce")
    nonnull = s.notna()
    bad = nonnull & (v.isna() | ~np.isfinite(v))
    return int(bad.sum())


def _structural_errors(df, spec: FeedSpec, prior_df, path, sport_tokens) -> list:
    """Every structural check EXCEPT the row-count-collapse comparison. Shared by validate_feed (which
    adds collapse) and validate_feed_slate (which chooses collapse vs a completeness contract). A
    non-empty list means the candidate is structurally unpublishable regardless of baseline mode."""
    errors: list = []
    if df is None:
        return ["frame is None"]
    cols = list(getattr(df, "columns", []))

    tokens = sport_tokens or spec.path_sport_tokens
    if path is not None and tokens:
        name = Path(path).name.lower()
        if not any(str(tok).lower() in name for tok in tokens):
            errors.append(f"output path {Path(path).name!r} does not match expected sport tokens {tuple(tokens)}")

    for c in spec.required_cols:
        if c not in cols:
            errors.append(f"missing required column {c!r}")
    if any(e.startswith("missing required column") for e in errors):
        return errors  # can't validate values without the columns

    if spec.min_rows and len(df) < spec.min_rows:
        errors.append(f"empty/too-small current slice: {len(df)} rows < min {spec.min_rows}")

    for c in spec.identity_cols:
        if c in cols:
            blank = df[c].isna() | (df[c].astype(str).str.strip() == "")
            if int(blank.sum()):
                errors.append(f"{int(blank.sum())} rows have empty identity column {c!r}")

    for c in spec.numeric_cols:
        if c in cols:
            nbad = _finite_series(df[c])
            if nbad:
                errors.append(f"{nbad} non-finite/non-numeric values in {c!r}")

    if spec.timestamp_col and spec.timestamp_col in cols:
        ts = pd.to_datetime(df[spec.timestamp_col], errors="coerce", utc=True, format="mixed")
        nonnull = df[spec.timestamp_col].notna()
        unparsed = int((nonnull & ts.isna()).sum())
        if unparsed:
            errors.append(f"{unparsed} unparseable timestamps in {spec.timestamp_col!r}")
        if prior_df is not None and spec.timestamp_col in getattr(prior_df, "columns", []):
            new_max = ts.max()
            prior_ts = pd.to_datetime(prior_df[spec.timestamp_col], errors="coerce", utc=True, format="mixed")
            prior_max = prior_ts.max()
            if pd.notna(new_max) and pd.notna(prior_max) and new_max < prior_max:
                errors.append(f"timestamp REGRESSION: new max {new_max} < prior max {prior_max}")

    if spec.side_col and spec.side_col in cols and spec.allowed_sides:
        allowed = {s.lower() for s in spec.allowed_sides}
        vals = df[spec.side_col].dropna().astype(str).str.strip().str.lower()
        bad = sorted(set(vals) - allowed)
        if bad:
            errors.append(f"disallowed {spec.side_col!r} values: {bad[:6]}")

    if spec.id_cols and all(c in cols for c in spec.id_cols) and spec.value_cols:
        vcols = [c for c in spec.value_cols if c in cols]
        if vcols:
            key = list(spec.id_cols)
            dup = df[df.duplicated(subset=key, keep=False)]
            conflicts = 0
            for _, g in dup.groupby(key, dropna=False):
                for vc in vcols:
                    if g[vc].astype(str).nunique(dropna=True) > 1:
                        conflicts += 1
                        break
            if conflicts:
                errors.append(f"{conflicts} id-key groups have CONFLICTING {vcols} values (same key, "
                              "different lines/prices)")
    return errors


def validate_feed(df, spec: FeedSpec, prior_df=None, path=None, sport_tokens=None, allow_collapse=False):
    """Return (ok, errors). ok=False means DO NOT publish; leave the prior artifact untouched.
    `sport_tokens` (caller-supplied, e.g. ('NFL',) for an NFL fetch) checks the output filename matches
    the requested sport so an NFL fetch can never overwrite the NBA file. UNCHANGED behavior: structural
    checks + absolute row-count collapse vs the prior."""
    errors = _structural_errors(df, spec, prior_df, path, sport_tokens)
    if any(e.startswith("missing required column") for e in errors):
        return False, errors
    if prior_df is not None and not allow_collapse:
        pn = len(prior_df)
        if pn >= 5 and len(df) < spec.collapse_ratio * pn:
            errors.append(f"implausible row-count collapse: {len(df)} rows < {spec.collapse_ratio:.0%} of "
                          f"prior {pn} (pass an explicit override if intended)")
    return (len(errors) == 0), errors


def _prior_age_hours(path) -> float | None:
    try:
        return (time.time() - Path(path).stat().st_mtime) / 3600.0
    except OSError:
        return None


def _distinct(df, col) -> set:
    if df is None or col not in getattr(df, "columns", []):
        return set()
    return {str(v).strip() for v in df[col].dropna().tolist() if str(v).strip()}


def _assess_comparability(df, spec, prior_df, prior_age):
    """Decide whether the prior artifact is a COMPARABLE baseline for an absolute row-count collapse test.
    Returns (comparable: bool, reason_code: str|None). Comparable requires: a non-empty prior, within the
    declared refresh cadence, with a similar eligible-event count, the SAME market set, and the SAME
    bookmaker set. Any mismatch (especially staleness) -> not comparable -> current-slate contract."""
    if prior_df is None or len(prior_df) == 0:
        return False, "BASELINES_NOT_COMPARABLE"
    if spec.comparable_prior_max_age_hours and prior_age is not None and prior_age > spec.comparable_prior_max_age_hours:
        return False, "PRIOR_BASELINE_STALE"
    ce, pe = len(_distinct(df, spec.event_col)), len(_distinct(prior_df, spec.event_col))
    if ce and pe:
        lo, hi = min(ce, pe), max(ce, pe)
        if hi and (lo / hi) < spec.comparable_event_ratio:
            return False, "BASELINES_NOT_COMPARABLE"
    if _distinct(df, spec.market_col) != _distinct(prior_df, spec.market_col):
        return False, "BASELINES_NOT_COMPARABLE"
    if _distinct(df, spec.book_col) != _distinct(prior_df, spec.book_col):
        return False, "BASELINES_NOT_COMPARABLE"
    return True, None


def validate_feed_slate(df, spec: FeedSpec, prior_df=None, path=None, sport_tokens=None, slate_facts=None):
    """Slate-aware validation (opt-in via spec.slate_aware). Returns (ok, errors, receipt).

    Structural checks always apply. Then:
      - COMPARABLE_PRIOR  (prior fresh + similar slate/markets/books): keep the absolute row-count
        collapse test -- a material unexplained decline vs a comparable baseline still REJECTS.
      - CURRENT_SLATE     (prior stale or not comparable): the collapse-vs-stale comparison is invalid,
        so instead require a COMPLETE current slate -- a linked response-shape receipt, zero provider
        errors, full coverage of the eligible (markets-posted) events, and a sport-specific normalized
        row-density floor. Missing/contradictory/foreign receipt -> fail closed.
    `slate_facts` (from the fetcher's in-process shape receipt) carries:
      events_found, eligible_events (events with >=1 requested market posted), events_with_rows,
      provider_errors, candidate_rows (== len(df) for receipt linkage), requested_markets, markets_present.
    """
    errors = _structural_errors(df, spec, prior_df, path, sport_tokens)
    structural_ok = not errors
    prior_age = _prior_age_hours(path)
    comparable, noncomp_reason = _assess_comparability(df, spec, prior_df, prior_age)
    baseline_mode = "COMPARABLE_PRIOR" if comparable else "CURRENT_SLATE"

    facts = dict(slate_facts or {})
    eligible = int(facts.get("eligible_events") or 0)
    with_rows = int(facts.get("events_with_rows") or 0)
    provider_errors = int(facts.get("provider_errors") or 0)
    candidate_rows = facts.get("candidate_rows")
    event_coverage = round(with_rows / eligible, 4) if eligible else 0.0
    normalized_rpe = round(len(df) / eligible, 2) if eligible else 0.0

    reason_code = None
    decision = "PUBLISH"

    if comparable:
        # keep the absolute collapse test vs a comparable baseline
        pn = len(prior_df)
        if pn >= 5 and len(df) < spec.collapse_ratio * pn:
            errors.append(f"implausible row-count collapse vs COMPARABLE prior: {len(df)} < "
                          f"{spec.collapse_ratio:.0%} of {pn}")
            reason_code = "COMPARABLE_BASELINE_COLLAPSE"
        elif structural_ok:
            reason_code = "CURRENT_SLATE_COMPLETE"  # comparable + no collapse + structurally clean
    else:
        # current-slate completeness contract -- never "trust any nonempty fetch".
        if slate_facts is None or candidate_rows is None:
            errors.append("no response-shape receipt supplied for CURRENT_SLATE validation")
            reason_code = "RESPONSE_RECEIPT_MISSING"
        elif int(candidate_rows) != len(df):
            errors.append(f"response-shape receipt not linked to this candidate "
                          f"(receipt rows {candidate_rows} != frame rows {len(df)})")
            reason_code = "RESPONSE_RECEIPT_MISSING"
        elif provider_errors > 0:
            errors.append(f"{provider_errors} provider error(s) during the current-slate fetch")
            reason_code = "CURRENT_SLATE_INCOMPLETE"
        elif eligible <= 0:
            errors.append("no eligible (markets-posted) events in the current slate")
            reason_code = "CURRENT_SLATE_INCOMPLETE"
        elif event_coverage < spec.event_coverage_min:
            errors.append(f"partial event coverage: {with_rows}/{eligible} eligible events produced rows "
                          f"(< required {spec.event_coverage_min:.0%}) -- markets posted but rows missing")
            reason_code = "CURRENT_SLATE_INCOMPLETE"
        elif normalized_rpe < spec.rows_per_event_min:
            errors.append(f"low row density: {normalized_rpe} rows/event < min {spec.rows_per_event_min}")
            reason_code = "CURRENT_SLATE_INCOMPLETE"
        elif structural_ok:
            reason_code = "CURRENT_SLATE_COMPLETE"
        else:
            reason_code = "CURRENT_SLATE_INCOMPLETE"
        # name the non-comparability cause when the slate is otherwise fine (informational)
        if reason_code == "CURRENT_SLATE_COMPLETE" and noncomp_reason:
            pass  # publish; the receipt still records baseline_mode + why it wasn't comparable

    ok = (len(errors) == 0)
    if not ok and reason_code is None:
        reason_code = "CURRENT_SLATE_INCOMPLETE" if not comparable else "COMPARABLE_BASELINE_COLLAPSE"
    decision = "PUBLISH" if ok else "REJECT"
    receipt = {
        "baseline_mode": baseline_mode,
        "non_comparable_reason": noncomp_reason,
        "prior_age": round(prior_age, 2) if prior_age is not None else None,
        "prior_rows": int(len(prior_df)) if prior_df is not None else 0,
        "prior_eligible_events": len(_distinct(prior_df, spec.event_col)) if prior_df is not None else 0,
        "candidate_rows": int(len(df)),
        "candidate_eligible_events": eligible,
        "event_coverage": event_coverage,
        "requested_markets": list(facts.get("requested_markets") or []),
        "markets_present": list(facts.get("markets_present") or []),
        "provider_errors": provider_errors,
        "normalized_rows_per_event": normalized_rpe,
        "decision": decision,
        "reason_code": reason_code,
    }
    return ok, errors, receipt


# Per-feed specs (the authoritative current-market artifacts the narrow recovery fetches publish).
GAME_LINES_SPEC = FeedSpec(
    kind="game_lines",
    required_cols=("Away", "Home", "LastUpdated"),
    numeric_cols=("Spread", "Total", "SpreadOdds", "OverOdds", "UnderOdds", "AwayML", "HomeML"),
    timestamp_col="LastUpdated",
    id_cols=("GameID", "Book"),
    value_cols=("Spread", "Total", "SpreadOdds"),
    identity_cols=("Away", "Home"),
    min_rows=1,
)

PLAYER_PROPS_SPEC = FeedSpec(
    kind="player_props",
    required_cols=("Player", "Stat", "LastUpdated"),
    numeric_cols=("Line", "OverOdds", "UnderOdds"),
    timestamp_col="LastUpdated",
    # No conflicting-duplicate check: props legitimately carry ALTERNATE lines (same Player/Stat/Book,
    # different Line), and the fetcher already dedups on the full (Player,Stat,MarketKey,Line,Game,Book)
    # key, so a same-key conflict cannot survive. A coarse key here would false-positive on alt lines.
    id_cols=(),
    value_cols=(),
    identity_cols=("Player",),
    min_rows=1,
)

# NBA player props OPT IN to the slate-aware model (incident 2026-10-24): season-opening slates vary in
# game count day to day, so an absolute row-count collapse vs a stale larger prior is an apples-to-oranges
# false positive. Only NBA opts in; other props feeds keep PLAYER_PROPS_SPEC and are unaffected.
NBA_PLAYER_PROPS_SLATE_SPEC = FeedSpec(
    kind="player_props",
    required_cols=("Player", "Stat", "LastUpdated"),
    numeric_cols=("Line", "OverOdds", "UnderOdds"),
    timestamp_col="LastUpdated",
    id_cols=(),
    value_cols=(),
    identity_cols=("Player",),
    min_rows=1,
    slate_aware=True,
    event_col="Game",
    market_col="MarketKey",
    book_col="Book",
    comparable_prior_max_age_hours=30.0,   # = props refresh cadence; older prior is not a comparable baseline
    comparable_event_ratio=0.5,            # slates within 2x game count are "similar"
    event_coverage_min=1.0,                # every markets-posted event must yield rows (partial => INCOMPLETE)
    rows_per_event_min=20.0,               # NBA props run ~65-145 rows/game; <20/game indicates a parse failure
)

FUTURES_SPEC = FeedSpec(
    kind="futures",
    required_cols=("SportKey", "Outcome", "Price", "LastUpdated"),
    numeric_cols=("Price",),
    timestamp_col="LastUpdated",
    # dedup is on (SportKey,EventID,MarketKey,Outcome,Book); a same-key conflict cannot survive -> skip.
    id_cols=(),
    value_cols=(),
    identity_cols=("Outcome",),
    min_rows=1,
)
