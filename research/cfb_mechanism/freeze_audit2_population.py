"""
Freeze the Audit #2 eligible-game population (read-only; no model, no result).

The game-line history is a ROLLING CFBD fetch -- re-pulls can rewrite even past-season
rows -- so "freeze the file" is not stable. Instead we freeze a FINGERPRINT of the exact
eligible-game set: completed seasons 2021-2025, the identical Audit #1 gates, canonicalized
and hashed. Audit #2 recomputes this fingerprint at run time and ABORTS if it differs, which
is how "population mismatch should fail execution" is enforced.

This defines the population ONCE. Audit #2 will import `eligible_games` from here so the
benchmark (Audit #1 cumulative SRS) and the candidate (recency-weighted SRS) are evaluated
on the identical, paired game universe.

Reuses Audit #1's loader and SRS verbatim. Writes the manifest; computes nothing about the
test's outcome (the recency model does not exist here).
"""
from __future__ import annotations
import hashlib
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import audit_opponent_adjusted_strength as a1   # Audit #1: _load, _srs, MIN_WEEK, MIN_PRIOR_GAMES

MANIFEST = HERE / "audit2_frozen_population.json"
EVAL_SEASONS = [2021, 2022, 2023, 2024, 2025]   # completed, immutable; 2026 excluded


def eligible_games():
    """Yield the exact Audit #1 eligible games as canonical dict rows, point-in-time gated.
    Identical gate to Audit #1: season in EVAL_SEASONS, week>=MIN_WEEK, >=20 prior games in
    the week's solve, both teams rated (>=MIN_PRIOR_GAMES prior), scores+spread present,
    pushes excluded."""
    df = a1._load()
    df = df[df["Season"].isin(EVAL_SEASONS)]
    for season, sdf in df.groupby("Season"):
        for week in sorted(sdf["Week"].unique()):
            if week < a1.MIN_WEEK:
                continue
            prior = sdf[sdf["Week"] < week]
            if len(prior) < 20:
                continue
            _, _, rated = a1._srs(prior)
            wk = sdf[sdf["Week"] == week]
            for _, g in wk.iterrows():
                if g["Home"] not in rated or g["Away"] not in rated:
                    continue
                if g["ats_home"] == 0:        # push -- no action
                    continue
                yield {
                    "season": int(g["Season"]), "week": int(g["Week"]),
                    "away": str(g["Away"]), "home": str(g["Home"]),
                    "hspread": round(float(g["HSpread"]), 1),
                    "margin": int(g["margin"]),
                }


def fingerprint(rows: list[dict]) -> str:
    canon = sorted(f"{r['season']}|{r['week']}|{r['away']}|{r['home']}|{r['hspread']}|{r['margin']}"
                   for r in rows)
    return hashlib.sha256("\n".join(canon).encode("utf-8")).hexdigest()


def main() -> int:
    rows = list(eligible_games())
    fp = fingerprint(rows)
    per_season = {}
    for r in rows:
        per_season[r["season"]] = per_season.get(r["season"], 0) + 1
    manifest = {
        "description": "Frozen eligible-game population for CFB Mechanism Audit #2 (paired with Audit #1).",
        "eval_seasons": EVAL_SEASONS,
        "gates": {"min_week": a1.MIN_WEEK, "min_prior_games": a1.MIN_PRIOR_GAMES,
                  "min_prior_for_solve": 20, "push_excluded": True, "unit": "game"},
        "n_eligible": len(rows),
        "per_season": {str(k): per_season[k] for k in sorted(per_season)},
        "sha256": fp,
    }
    MANIFEST.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"frozen eligible games n={len(rows)} | per-season={manifest['per_season']}")
    print(f"sha256={fp}")
    print(f"written: {MANIFEST.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
