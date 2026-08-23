# CFB "Regression Watch" — the Phil-Steele lens, from our own data (2026-08-23)

## What this is
Phil Steele's magazines are copyrighted — we copy **none** of his content. But the
*factors* he's famous for are public data we compute ourselves. The most valuable and
on-brand is his **regression** work: teams whose record outran their underlying quality
(yards-per-play margin) regress, and the two classic luck tells — **turnover margin** and
**one-score-game record** — corroborate it. Built entirely from CFBD + our own files.

## Data (all local / live, verified 2026-08-23)
- **2026 returning production** — CFBD `/player/returning?year=2026` is **LIVE** (136 FBS
  teams, `percentPPA` = share of production returning). Cached to
  `data/historical/NCAAF_CFBD_ReturningProduction_2026.csv`.
- **2025 team quality** — `NCAAF_TeamRankings_2025_TeamStats.csv` already has
  `yards_per_play`, `opponent_yards_per_play`, `turnover_margin_per_game`.
- **2025 one-score records** — computed from `NCAAF_CFBD_Games_2025.csv` (final scores).

## The prototype (`cfb_regression_watch.py`) — verified coherent
`luck = win% percentile − YPP-margin percentile` (how far the record outran the play),
corroborated by turnover margin, one-score record, and 2026 returning production.

**Regression DOWN (won more than they played):** BYU 12-2 (+0.5 YPP, **4-0 one-score**,
+0.6 TO), Navy 11-2 (**5-0 one-score**), Houston 10-3 (**6-1 one-score**), Minnesota 8-5
(−0.9 YPP). **Bounce-back UP (played better than the record):** Arkansas 2-10 (+0.4 YPP,
**0-6 one-score**, −1.2 TO), Auburn 5-7 (**0-6 one-score**), USC 9-4 (**+1.8 YPP**),
Toledo (+1.9 YPP, 0-4 one-score). The luck tells line up with the yards-vs-record gap in
nearly every row — the signal corroborates itself.

## Honesty framing (important)
This is **preseason CONTEXT, not a claimed betting edge.** It says "the math shows last
year was partly luck," which is measurable and true — but it is NOT an out-of-sample ROI
result (2026 hasn't happened, and CFB game-line backtest data is too thin to prove one).
It **complements The Reveal**, which earns the actual in-season CFB edge once teams have
tape. Fits our thesis: we don't guess in August — we surface what's measurable (experience
+ last-year luck), then react once they play.

## BUILT (2026-08-23) — site page `/tools/cfb-regression`
Productized: `build_cfb_regression_export.py` → `data/scenarios/cfb_regression.json` (fixed
export), page `templates/cfb_regression.html` (CFB-gold) with three boards — Due to Fall /
Due to Rise / Returning Production — each honest-framed ("preseason context, not a pick") and
linking to The Reveal. Source CSVs (games, team stats, returning production) are gitignored;
prod serves the JSON. Rerun the export when CFBD finalizes rosters.

## Where it fits the product
A CFB **preseason "Regression Watch"** board (who's due to fall / rise, + how much
production returns), that hands off to The Reveal in ~Week 5. Complements, doesn't
contradict, the "react don't predict" stance. Refresh returning production once CFBD
finalizes rosters; recompute the 2025 regression base is fixed history.
