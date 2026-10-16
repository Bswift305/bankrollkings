# Legal/IP & Data-Licensing Audit — Bankroll Kings (read-only)

**Status: READ-ONLY AUDIT + REMEDIATION PROPOSAL. No assets removed, no product calculations altered,
no legal conclusions.** Prepared for review by a qualified sports/IP attorney, who is the final gate.
Nothing here is legal advice or a determination that any use is or is not infringing.

**Method & ground rules (per directive):**
- Provider terms were read from the current official pages, **retrieved 2026-10-16**, with direct links.
- **A data *fact* is distinct from the *feed/database* used to obtain it** — public facts (a score, a
  stat) do not make a copied feed commercially reusable.
- **GitHub location or public accessibility is NOT proof of licensing.**
- **Factual use of player/team/league *names*** (text identifiers) is treated separately from
  **promotional use of names, likenesses, photographs, uniforms, and logos.**
- Any official logo or player image **without documented permission is classified NOT CLEARED.**
- File:line references are exact so containment can be verified mechanically.

**Classification buckets:** Owned/licensed · Factual reference · Permission required · Unknown.
**Risk ranks:** Critical (likely prohibited terms / unlicensed commercial-gambling use) · High (official
logos, player imagery, or implied affiliation without documented permission) · Medium (missing
attribution, uncertain provenance, unclear retention/redistribution) · Low (neutral factual reference).

---

## A. External data sources — register

Rights columns from the official terms where fetched (✓ permitted / ✗ not / ? unknown-verify). "Our
use" = a **commercial, gambling-adjacent analytics** product.

| # | Provider / host | What we take | Files (examples) | Commercial | Gambling use | Display | Redistribute raw | Cache/Retain | Derived | Attribution | Class | Risk |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | **NBA.com / stats.nba.com / cdn.nba.com / official.nba.com** via `nba_api` + direct | NBA+WNBA stats, schedule, game logs, tracking, injuries, referee assignments | `refresh_tracking_stats.py:9`, `fetch_schedule.py:48`, `download_2025_26_game_logs.py:13`, `refresh_wnba_player_logs.py:7`, `fetch_injuries.py:416,434`, `fetch_basketball_officiating_assignments.py:15` | ✗ (written permission req.) | **✗ — §9(iv) "NBA Statistics may not be used in connection with any gambling activity (including legal gambling activity)"** | personal/non-commercial only | ✗ | ✗ (no comprehensive-stats DB w/o consent §9(vii)) | ✗ | required §9(i) | **Permission required → prohibited as used** | **CRITICAL** |
| 2 | **Open-Meteo** (`api.open-meteo.com`) | weather context (wind/temp) | `fetch_nfl_weather.py:60`, `fetch_cfb_weather.py:107`, `fetch_mlb_weather_context.py:86` | **✗ on free tier (paid plan req. for commercial)** | — | ✓ (paid) | ? | ? | ✓ | CC-BY required (**missing**) | Permission required (wrong tier) | **High** |
| 3 | **Official-logo GitHub mirror** `raw.githubusercontent.com/timaboderin/NBA_Logos` | NBA team logo PNGs (hot-linked) | `app.py:2036-2066` (`TEAM_ABBR_TO_LOGO_URL`) | ✗ | — | ✗ | ✗ | — | — | — | Permission required (unauthorized source) | **High** |
| 4 | **ESPN** (`site.api.espn.com`, `www.espn.com`, headshots) | rosters, **player headshots**, scores, injuries | `fetch_espn_current_roster.py:24,123`, `fetch_nfl_current_roster.py:37`, `fetch_final_scores.py:35`, `fetch_sport_injuries.py:32` | ? | ? | ? | ? | ? | ? | none | Permission required / Unknown | High (headshots) / Med (facts) |
| 5 | **NFL Next Gen Stats** `nextgenstats.nfl.com` (browser-spoofed) | advanced NFL stats | `fetch_ngs_stats.py:30,70` | ? | ? | ? | ? | ? | ? | none | Permission required | High |
| 6 | **MLB Stats API** `statsapi.mlb.com` (MLBAM) | schedule, lineups, game logs | `fetch_mlb_schedule.py:27`, `fetch_mlb_lineups.py:29`, `fetch_mlb_gamelogs.py:57` | ? | ? | ? | ? | ? | ? | none | Permission required / Unknown | Medium |
| 7 | **pybaseball** → Baseball Savant (MLBAM) / FanGraphs / Baseball-Reference | Statcast + profiles | `fetch_mlb_statcast.py:19`, `research/mlb_statcast/fetch_mlb_pbp.py:14` | ? | ? | ? | ? | ? | ? | none | Permission required / Unknown | Medium |
| 8 | **SportsDataIO** `api.sportsdata.io/v3` | season futures | `fetch_season_markets_sportsdataio.py:42` | ? (paid license) | ? | ? | ? | ? | ? | per contract | Unknown — confirm contract | Medium |
| 9 | **refmetrics.com**, **teamrankings.com** (scraped) | MLB umpire zones; NCAAF historical stats | `fetch_mlb_umpire_assignments.py:17`, `import_teamrankings_ncaaf_historical_stats.py:17` | ? | ? | ? | ? | ? | ? | none | Permission required / Unknown | Medium |
| 10 | **nflverse-data** (GitHub release) | NFL weekly stats, PBP, scores | `fetch_nfl_player_week.py:34`, `build_nfl_*`, `grade_nfl_*` | ✓ (CC-BY-4.0) | ✓ | ✓ | ✓ (w/ attrib) | ✓ | ✓ | **CC-BY required (missing)** | Licensed (CC-BY-4.0) | Medium (attrib gap) |
| 11 | **The Odds API** `api.the-odds-api.com` | odds, lines, scores, historical | `fetch_player_props.py`, `fetch_game_lines.py:102`, `refresh_live_scores.py:171` | ✓ (data not the primary resold product) | ✓ (responsible-gambling msg encouraged) | ✓ | ✗ | ✓ (indefinite) | ✓ | not required | **Licensed / permitted** | Low* |
| 12 | **CFBD** `api.collegefootballdata.com` | all CFB data | `fetch_cfbd_*`, `build_cfb_*`, `fetch_ncaaf_slate_cfbd.py` | ✓ | ✓ (betting-analysis contemplated) | ✓ (reasonable portions) | ✗ (bulk/mirror) | ✓ | ✓ | appreciated, not required | **Licensed / permitted** | Low |

\* Odds API: Low **provided** we never resell the raw feed and keep responsible-gambling messaging
(the footer already carries 1-800-GAMBLER). Also a minor **log-hygiene** item: the key is passed in the
URL query string (`fetch_player_props.py:197,207`) — move to a header like SportsDataIO does.

**Terms sources (retrieved 2026-10-16):** [nba.com/terms](https://www.nba.com/terms) ·
[the-odds-api.com/terms-and-conditions.html](https://the-odds-api.com/terms-and-conditions.html) ·
[collegefootballdata.com/terms](https://collegefootballdata.com/terms) ·
[open-meteo.com/en/terms](https://open-meteo.com/en/terms) ·
[github.com/nflverse/nflverse-data (CC-BY-4.0)](https://github.com/nflverse/nflverse-data). ESPN, NGS,
MLBAM, pybaseball's sources, SportsDataIO, refmetrics, teamrankings: terms **not yet obtained** →
Unknown pending counsel/provider confirmation.

**Facts vs feed (critical distinction).** The statistical *values* (a yardage total, a score) are facts;
the **NBA.com / ESPN / MLBAM / NGS feeds** used to obtain them are separate works with their own terms.
Several are **undocumented endpoints accessed with browser-spoofing headers** (`fetch_injuries.py:438`
sends `x-nba-stats-token`/`x-nba-stats-origin`; `fetch_ngs_stats.py:70` spoofs a `Mozilla` UA/Referer),
and two scripts `pip install nba_api` at runtime (`fetch_schedule.py:52`, `floor_play_package/refresh_data.py:64`).

---

## B. Visual / branding assets — register

| # | Asset / surface | Location (file:line) | Class | Risk | Disposition |
|---|---|---|---|---|---|
| 1 | **Official league marks** NBA/NFL/MLB/WNBA/NCAA/CFP (11) | `static/logos/leagues/official/*` via `sport_logo_url()` `app.py:16908` | Permission required (NOT CLEARED) | **High** | replace with text/BK badge; quarantine files |
| 2 | **League/section sport icons** (21) | `static/logos/leagues/*.svg` | Permission required (stylized league marks) | High | replace with BK original icons |
| 3 | **NBA team logos** (120 local) | `static/logos/nba/` + `static/logos/nba_clean/` via `team_logo_url()` `app.py:17054` | Permission required (NOT CLEARED) | **High** | text abbr / BK badge; quarantine |
| 4 | **Football team logos** NFL+NCAA (~285) + `_NCAA_logo.png` | `static/logos/football/*` via `football_logo_url()` `app.py:16888` | Permission required (NOT CLEARED) | **High** | text abbr / BK badge; quarantine |
| 5 | **NBA logo hot-link** (GitHub mirror) | `app.py:2036-2066` | Permission required (unauthorized source) | **High** | **remove the fallback map** |
| 6 | **Nav sport badges** (in-house concept art depicting league/sport identity) | `static/logos/nav/*`, `static/logos/nav/png/*`, `README.txt` "cropped from the master concept sheet" | **Unknown** (ambiguous — depicts league identity) | Medium | counsel review; interim keep |
| 7 | **Player headshots** | **none displayed in UI**; URLs stored only in data: `fetch_espn_current_roster.py:123-126,191`, `build_nfl_player_stats_from_pbp.py:229,243` | Permission required (likeness + ESPN/Getty) | Medium (contained — not surfaced) | keep un-surfaced; flag stored URLs |
| 8 | **Franchise GM avatar** (user-uploaded) | `templates/franchise_hub.html:140`, dir `static/franchise_avatars/` | User content | Low-Med | ensure upload moderation (user-supplied imagery) |
| 9 | **Sportsbook names in copy** (DraftKings/FanDuel/BetMGM/Caesars/Yahoo) — text only, no logos | e.g. `templates/floor_plays.html:15`, `templates/wnba_dashboard.html:184`; editorial line `marketing/generators/weekly_cards.py:216` | Factual / nominative | Low-Med | add ™ attribution line; soften the editorial line |
| 10 | **Team/player/league NAMES** as text labels/boards | throughout templates (factual board labels) | Factual reference | Low | **preserve provisionally** |
| 11 | **Original BK brand art** (32) + PWA icons (6) + tool icons (34) + franchise crests (generated SVG) | `static/brand-*`, `static/icons/`, `static/logos/nav/tools/`, `franchise_kings.py:148` | **Owned** | Low | keep |

---

## C. Wording / endorsement — register
- **Existing disclaimers (not-a-sportsbook / entertainment / 21+ / 1-800-GAMBLER):** `templates/public_base.html:178`,
  `templates/bk_base.html:205,215`, `templates/info.html:77`, `templates/how_we_analyze.html:144,147`,
  `marketing/trial/field_test_flyer.html:129`.
- **Gap — no independence / non-affiliation / trademark disclaimer anywhere.** This is the headline
  wording finding given the heavy league/team marks and sportsbook names.
- **No endorsement/sponsorship/partnership/official-status copy** (the "official" hits are game
  *referees*; "partner" is the in-game *trade-partner* UI) — Low risk.

---

## D. Risk ranking (rolled up)
- **Critical (1):** NBA.com-derived statistics (NBA **and** WNBA) via `nba_api` + direct endpoints,
  used in a gambling-analytics product — NBA ToS §9(iv) gambling prohibition; undocumented/spoofed
  access; no license. (Register A#1.)
- **High (6):** Open-Meteo commercial-on-free-tier (A#2); GitHub NBA-logo hot-link (A#3/B#5); ESPN
  feed+headshots (A#4); NGS scrape (A#5); official league marks (B#1/B#2); team logos NBA+football
  (B#3/B#4). Plus the **missing independence disclaimer** (C).
- **Medium (7):** MLB Stats API (A#6); pybaseball sources (A#7); SportsDataIO unconfirmed (A#8);
  refmetrics/teamrankings (A#9); nflverse CC-BY attribution gap (A#10); nav badge set (B#6); stored
  player-headshot URLs (B#7); sportsbook-name ™ attribution (B#9).
- **Low:** Odds API (A#11), CFBD (A#12), factual names (B#10), owned BK art (B#11).

---

## E. Proposal 1 — Immediate reversible containment (ship before further public promotion)
**Proposed, not implemented — for approval.** All reversible; **no asset is deleted** (quarantine +
feature flag). Rendering is centralized, so the logo swap is one switch:

1. **Replace uncleared logos with plain-text abbreviations / BK badges.** Add a default-OFF flag
   `BK_OFFICIAL_MARKS_ENABLED`. With it OFF, `render_team_mark()` (`app.py:17095`), `team_logo_url()`
   (`app.py:17054`), and `sport_logo_url()` (`app.py:16908`) emit a **text abbreviation chip or an
   original BK badge** instead of an `<img>` to `/static/logos/{nba,nba_clean,football,leagues/official}`.
   Nav/section league icons (B#2) fall back to BK originals. One switch contains B#1–B#4 at the render
   layer; files stay in place.
2. **Remove the third-party logo hot-link** map `TEAM_ABBR_TO_LOGO_URL` (`app.py:2036-2066`) so no
   unauthorized trademarked URL can be emitted even on a missing-file fallback (B#5/A#3).
3. **Quarantine the raw logo assets** by moving `static/logos/{nba,nba_clean,football,leagues/official,leagues}`
   to a gitignored `static/_quarantine/logos/` **after** the render switch lands (so no runtime 404),
   keeping them recoverable. Reversible by moving back + flipping the flag.
4. **Player imagery:** none is displayed, so nothing to pull from the UI; **keep headshot columns
   un-surfaced** and add a guard note so no future template renders them while uncleared (B#7).
5. **Weather:** Open-Meteo free-tier commercial use is likely non-compliant — **gate weather-context
   features behind a flag** pending a paid plan or a licensed source (A#2). (Context only; does not
   change graded calculations.)
6. **Independence disclaimer (additive copy)** in both footers (`templates/public_base.html:178`,
   `templates/bk_base.html:205`):
   > *Bankroll Kings is an independent analytics platform and is not affiliated with, endorsed by, or
   > sponsored by the NBA, WNBA, NFL, MLB, NCAA, CFP, any team, any player, any sportsbook, or any
   > governing body. All team names, logos, and trademarks are the property of their respective owners;
   > their use here is nominative and for identification only.*
   And soften the one editorial sportsbook line (`marketing/generators/weekly_cards.py:216`).
7. **Preserve neutral factual names** (teams/players/leagues as text) — no change (B#10).

**NBA statistics (Critical) is deliberately NOT auto-disabled here** — gating the flagship NBA surfaces
is a product decision, not a unilateral containment, and the directive forbids altering product scope
mid-audit. A ready **reversible flag to gate NBA/WNBA statistical surfaces** is specified for Proposal 2
to flip *if* counsel directs. This is the one item where counsel may call for urgent action.

## F. Proposal 2 — Counsel-decision register (attorney opinion or written provider permission)
1. **NBA/WNBA NBA.com-derived statistics in a gambling product** (ToS §9(iv)). Decision: obtain a
   license (e.g., SportsDataIO/Sportradar), or **remove/replace** NBA+WNBA statistical features.
   Highest priority. (A ready `BK_NBA_STATS_ENABLED` gate can disable these surfaces reversibly on
   counsel's word.)
2. **Official league + team logos** (all leagues) — trademark use; keep text/BK badges unless licensed.
3. **ESPN** unofficial API + **player headshots** (likeness + ESPN/Getty) — license or drop.
4. **NFL Next Gen Stats, MLB Stats API (MLBAM), pybaseball sources, refmetrics, teamrankings** —
   undocumented/scraped; confirm permissibility or replace with licensed feeds.
5. **SportsDataIO** — confirm the commercial display/storage/gambling license is executed before the
   feed is enabled (`docs/season_markets_setup.md:79` already flags this).
6. **Open-Meteo** — move to a paid commercial tier and add CC-BY attribution, or replace.
7. **nflverse (CC-BY-4.0)** — confirm CC-BY permits our use and **add the required attribution**; note
   upstream provenance of the aggregated data for counsel.
8. **Nav badge set** (in-house art depicting league/sport identity) — confirm non-infringing.
9. **Sportsbook names/marks** — confirm nominative fair use and add a trademark-ownership notice.

## G. Verification plan (for the containment patch, when approved)
A new `qc_legal_containment.py` (registered in `run_all_scorecards.py`) asserts mechanically, with the
flag OFF:
- rendering a sample of authed + public pages emits **no** `<img>` whose `src` contains
  `/static/logos/(nba|nba_clean|football|leagues/official|leagues)` and **no**
  `raw.githubusercontent.com/timaboderin` URL;
- `render_team_mark()` / `sport_logo_url()` output the text-abbr / BK-badge form;
- the **independence disclaimer** string renders on both `public_base.html` and `bk_base.html`;
- `TEAM_ABBR_TO_LOGO_URL` is absent;
- no template references a headshot/photo column;
- quarantine is reversible: flipping the flag ON + restoring files returns prior rendering (asserted by
  a before/after render diff on a fixture).

---

## H. What this is / is not
A read-only inventory with evidence (file:line + source links + retrieval dates), a risk-ranked
classification, and a **proposed** reversible containment patch + counsel-decision register. **No assets
were removed and no calculations were changed.** Implementation of Proposal 1 awaits approval;
Proposal 2 awaits a qualified sports/IP attorney, who is the final gate. A disclaimer is **not**
permission, and nothing here is a definitive legal conclusion.
