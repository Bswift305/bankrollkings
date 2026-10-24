# NBA / WNBA injury-feed gap — read-only legal & operational diagnosis (2026-10-24)

The 2026-10-24 scorecards flagged NBA injuries ~193h stale and WNBA ~67h stale (NFL/MLB fresh). This is
**not** an operational freshness failure to repair — it is the **data-rights gate working as intended**.
No fetch was run, no provider restriction was bypassed, no threshold was changed, the gate was not lifted.

## Receipt

- **Exact source + legal classification**
  - **NBA injuries** — `fetch_injuries.py`: official.nba.com injury report + `cdn.nba.com/static/json/liveData/injuries/injuries.json` + ESPN fallback. Legal register `docs/nba_licensing_decision_table.md` **row 7**: restricted = *NBA.com injury report IP* ("spoof removed"); recommendation **"Substitute with a licensed injury feed; do not re-enable the NBA.com scrape."**
  - **WNBA injuries** — `fetch_sport_injuries.py` / `fetch_wnba_injuries.py`: ESPN. Decision table **row 15**: *"gated with the family for consistency."*
  - Both governed by `BK_NBA_STATS_ENABLED` (default **OFF**); `services/nba_source_gate.nba_stats_enabled()`.

- **Should ingestion run while gated?** **No.** The decision table header is explicit: "no new ingestion … no change to `BK_NBA_STATS_ENABLED` (stays off) … Nothing here lifts the gate." The code already enforces it: `fetch_injuries.py:401-403` returns empty and prints `[gated] NBA.com-derived ingestion disabled … skipping NBA injury report` **before** any network call (so the official/cdn/ESPN paths all skip); `fetch_sport_injuries.py:282` gates WNBA the same way. The former stats.nba.com header-spoof (`x-nba-stats-token`) was **removed outright** (`fetch_injuries.py:436-439`), not replaced with another evasion.

- **Last successful timestamp**: the on-disk artifacts are the last pre-gate writes — NBA `data/injuries/NBA_Injuries.csv` ≈193h, WNBA `WNBA_Injuries.csv` ≈67h (per the 2026-10-24 scorecard). They are preserved, not refreshed.

- **Precise failure status**: **none** — there is no provider error while gated, because no request is made (the fetch returns at the gate). It is intentional non-ingestion, not a 403/malfunction.

- **Does any artifact or customer surface consume stale values?** **No.** `app.py:31394` builds the injury-status lookup as `{}` when `gated`, and the NBA board renders the containment notice ("The NBA board is temporarily unavailable"). The stale CSV is retained on disk but **not exposed**.

- **Corrected outcome classification**: **`SKIP — DATA_RIGHTS_GATE`** for NBA/WNBA injuries while the gate is off — *not* fresh, *not* a readiness failure, *not* `PROVIDER_ERROR`. Implemented in `services/injury_feed_qc.py`: NBA/WNBA short-circuit to `outcome=SKIP_DATA_RIGHTS_GATE`, `failure_count=0`, with a visible WATCH note. The season-aware logic (schedule manifest) still applies to NFL/MLB/CFB, and to NBA/WNBA only if the gate is ever turned on.

- **Tests in both flag states**: `qc_injury_feed_season_aware.py` — gate OFF (with games present) → `SKIP_DATA_RIGHTS_GATE`/clean; gate ON + in-season stale → FAIL (season-aware path), off-season → `NO_ACTIVE_EVENTS`, missing schedule → strict default FAIL, fresh → `UPDATED`.

- **Confirmation NBA/WNBA injury data remains unexposed**: containment unchanged; `BK_NBA_STATS_ENABLED` stays `0`; injury lookup empty when gated (`app.py:31394`); no scrape re-enabled; no headers spoofed.

## Which permitted corrective outcome applied
**Outcome #1 — the data-rights gate applies.** NBA/WNBA injury ingestion stays disabled while gated;
monitoring now reports `SKIP — DATA_RIGHTS_GATE` instead of an operational freshness failure. The only
path to fresh NBA/WNBA injuries is a **licensed substitute feed** (decision-table rows 7/15, owner/counsel
decision), which would require the full engineering gate before any flip — out of scope here.
