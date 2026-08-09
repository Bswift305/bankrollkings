"""Focused QC for season-market normalization and model comparisons."""
from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory

import pandas as pd

from refresh_season_markets import normalize
from services.season_markets import build_season_market_context


def main() -> int:
    raw = pd.DataFrame([
        {"league": "NFL", "season": "2026", "type": "team", "name": "Kansas City Chiefs",
         "team": "Kansas City Chiefs", "market": "Regular Season Wins", "point": 11.5,
         "over_odds": -110, "under_odds": -110, "sportsbook": "Book A"},
        {"league": "NFL", "season": "2026", "type": "team", "name": "Kansas City Chiefs",
         "team": "Kansas City Chiefs", "market": "Regular Season Wins", "point": 10.5,
         "over_odds": 105, "under_odds": -125, "sportsbook": "Book B"},
    ])
    normalized = normalize(raw, default_source="QC")
    failures = []
    if len(normalized) != 2:
        failures.append("normalizer did not retain two valid book observations")

    with TemporaryDirectory() as temporary:
        base = Path(temporary)
        target = base / "data" / "season_markets"
        target.mkdir(parents=True)
        normalized.to_csv(target / "Season_Markets.csv", index=False)
        pd.DataFrame([{
            "Sport": "NFL", "Season": "2026", "EntityType": "team",
            "Entity": "Kansas City Chiefs", "Team": "Kansas City Chiefs",
            "Market": "Regular Season Wins", "ProjectedValue": 12.0,
            "ModelLabel": "QC projection", "SampleSize": 17,
            "UpdatedAt": "2026-07-26T00:00:00Z", "Note": "QC only",
        }]).to_csv(target / "Season_Projections.csv", index=False)
        context = build_season_market_context(base, sport="NFL", entity_type="team")

    if context["market_rows"] != 1 or context["comparison_rows"] != 1:
        failures.append("multi-book rows did not collapse to one model comparison")
    row = context["rows"][0] if context["rows"] else {}
    if row.get("consensus_line") != 11.0:
        failures.append(f"expected median consensus 11.0, got {row.get('consensus_line')}")
    if row.get("gap") != 1.0 or row.get("direction") != "Higher":
        failures.append("projection difference was not calculated correctly")
    if row.get("best_over_odds") != "+105" or row.get("best_under_odds") != "-110":
        failures.append("best Over/Under prices were not preserved")

    print("=" * 60)
    print("SEASON MARKETS QC")
    print("=" * 60)
    print(f"Failures: {len(failures)}")
    if failures:
        for failure in failures:
            print(f"[FAIL] {failure}")
        return 1
    print("Normalization, consensus, prices and model comparison passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
