# Season Markets: Our Findings vs Vegas

## Purpose

`/tools/season-markets` is the cross-sport comparison surface for true season-long
team and player markets:

- team regular-season wins;
- player passing, rushing, receiving, scoring and touchdown totals;
- NBA/WNBA player season totals;
- MLB team wins and player season milestones;
- college-football and college-basketball season markets when a licensed feed offers them.

Championship outrights, single-game totals and historical O/U tendencies are different
products and must not be substituted for season-long O/U lines.

## Data-source requirement

The existing Odds API integration does not provide comprehensive season-win and
season-player totals. Configure a licensed feed using:

```text
SEASON_MARKETS_FEED_URL=
SEASON_MARKETS_FEED_TOKEN=
```

The feed may return normalized CSV or JSON. A sportsbook/provider export can also be
loaded directly:

```powershell
python refresh_season_markets.py --input C:\path\season_markets.csv --source "Provider name"
```

## Normalized market schema

`data/season_markets/Season_Markets.csv`:

| Column | Meaning |
|---|---|
| SnapshotAt | UTC capture timestamp |
| Sport | NFL, NCAAF, NBA, WNBA, MLB, NCAAMB or NCAAWB |
| Season | Season label, such as 2026 or 2026-27 |
| EntityType | `team` or `player` |
| Entity | Team or player name |
| Team | Player's team; same as Entity for team markets |
| Market | Normalized label, such as `Regular Season Wins` |
| Line | Sportsbook O/U point |
| OverOdds / UnderOdds | American prices |
| Book | Sportsbook |
| Source | Licensed provider/export |
| SourceUpdatedAt | Provider timestamp |

Common aliases (`sport`, `league`, `player`, `point`, `sportsbook`, etc.) are
normalized automatically by `refresh_season_markets.py`.

## Model projection schema

`data/season_markets/Season_Projections.csv` attaches Bankroll Kings findings:

| Column | Meaning |
|---|---|
| Sport / Season / EntityType / Entity / Team / Market | Join identity |
| ProjectedValue | Our season projection in the market's unit |
| ModelLabel | Formula/version name |
| SampleSize | Evidence volume |
| UpdatedAt | Projection timestamp |
| Note | Honest limitation/context |

The page computes the consensus as the median line across books, preserves best Over
and Under prices, and shows `ProjectedValue - ConsensusLine`. A difference is context,
not a proven edge, until validated out of sample.

## Refresh and history

Each refresh atomically replaces `Season_Markets.csv` and appends deduplicated snapshots
to `Season_Market_History.csv`. Run the refresh independently of live-game odds jobs so
a futures-provider issue cannot block daily boards.

## Provider direction

A suitable provider must contractually permit display/storage and cover team and player
season futures across the required leagues. Sportradar documents a competition-futures
API, and SportsDataIO advertises aggregated futures/player-season-total markets; coverage
and licensing must be confirmed before credentials are connected.
