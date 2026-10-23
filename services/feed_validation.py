"""Strong semantic validation for an Odds feed artifact, run on the TEMP frame BEFORE atomic replacement.

"Required columns + one row" is too weak. This validates the things that actually make a current-market
artifact trustworthy, so a structurally-wrong fetch can never replace last-known-good (incident
2026-10-23). A FeedSpec describes one feed; validate_feed(df, spec, prior_df, path) returns (ok, errors).

Pure: pandas + stdlib only, no app import. The atomic publish calls this; a non-empty error list means
leave the previous bytes unchanged.
"""
from __future__ import annotations

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


def _finite_series(s):
    v = pd.to_numeric(s, errors="coerce")
    nonnull = s.notna()
    bad = nonnull & (v.isna() | ~np.isfinite(v))
    return int(bad.sum())


def validate_feed(df, spec: FeedSpec, prior_df=None, path=None, sport_tokens=None, allow_collapse=False):
    """Return (ok, errors). ok=False means DO NOT publish; leave the prior artifact untouched.
    `sport_tokens` (caller-supplied, e.g. ('NFL',) for an NFL fetch) checks the output filename matches
    the requested sport so an NFL fetch can never overwrite the NBA file."""
    errors = []
    if df is None:
        return False, ["frame is None"]
    cols = list(getattr(df, "columns", []))

    # output path must correspond to the requested sport
    tokens = sport_tokens or spec.path_sport_tokens
    if path is not None and tokens:
        name = Path(path).name.lower()
        if not any(str(tok).lower() in name for tok in tokens):
            errors.append(f"output path {Path(path).name!r} does not match expected sport tokens {tuple(tokens)}")

    for c in spec.required_cols:
        if c not in cols:
            errors.append(f"missing required column {c!r}")
    if any(e.startswith("missing required column") for e in errors):
        return False, errors  # can't validate values without the columns

    if spec.min_rows and len(df) < spec.min_rows:
        errors.append(f"empty/too-small current slice: {len(df)} rows < min {spec.min_rows}")

    # identity present on every row
    for c in spec.identity_cols:
        if c in cols:
            blank = df[c].isna() | (df[c].astype(str).str.strip() == "")
            if int(blank.sum()):
                errors.append(f"{int(blank.sum())} rows have empty identity column {c!r}")

    # finite numerics
    for c in spec.numeric_cols:
        if c in cols:
            nbad = _finite_series(df[c])
            if nbad:
                errors.append(f"{nbad} non-finite/non-numeric values in {c!r}")

    # timestamps parseable + no regression vs prior
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

    # allowed side/direction values
    if spec.side_col and spec.side_col in cols and spec.allowed_sides:
        allowed = {s.lower() for s in spec.allowed_sides}
        vals = df[spec.side_col].dropna().astype(str).str.strip().str.lower()
        bad = sorted(set(vals) - allowed)
        if bad:
            errors.append(f"disallowed {spec.side_col!r} values: {bad[:6]}")

    # conflicting duplicates: same id key, different value columns
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

    # implausible row-count collapse vs last valid artifact
    if prior_df is not None and not allow_collapse:
        pn = len(prior_df)
        if pn >= 5 and len(df) < spec.collapse_ratio * pn:
            errors.append(f"implausible row-count collapse: {len(df)} rows < {spec.collapse_ratio:.0%} of "
                          f"prior {pn} (pass an explicit override if intended)")

    return (len(errors) == 0), errors


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
    id_cols=("Player", "Stat", "Book"),
    value_cols=("Line",),
    identity_cols=("Player",),
    min_rows=1,
)
