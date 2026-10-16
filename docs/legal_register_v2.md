# Legal/IP & Data-Licensing Register v2 — dataset-level launch-readiness (read-only)

**Status: READ-ONLY REGISTER. No legal conclusions. Qualified sports/IP counsel is the final gate.**
Amends `docs/legal_ip_audit.md` (the first pass) per the review: operate at the **dataset level**, not
the provider level (one provider can supply several datasets under different terms), add a **fifth
classification**, and add the missing launch-readiness categories. Provider terms were read from the
current official pages, **retrieved 2026-10-16**, with links in `docs/legal_ip_audit.md`.

Ground rules carried forward: a data **fact** ≠ the **feed/database** used to obtain it; GitHub/public
accessibility is **not** proof of licensing; factual **names** are separate from **likeness/logos**.

### Classifications (five)
| Classification | Treatment |
|---|---|
| **Owned / Licensed** | Documentation supports the intended use |
| **Factual Reference** | Neutral identification or factual use |
| **Permission Required** | Rights-holder or contract approval needed |
| **Unknown** | Provenance or terms unresolved |
| **Prohibited Until Cleared** | A known restriction conflicts with current use (contain now) |

Risk ranks unchanged: Critical · High · Medium · Low.

---

## 1. Data register — by **dataset** (provider → dataset → rights)
One provider may appear in several rows because its datasets carry different rights. "Our use" =
commercial, gambling-adjacent analytics. (✓ permitted / ✗ not / ? verify, from the terms where fetched.)

| Provider | Dataset | Comm | Gambling | Display | Redistrib | Cache/Retain | Class | Risk | Current containment |
|---|---|---|---|---|---|---|---|---|---|
| The Odds API | **Odds/lines/props (display)** | ✓ | ✓ | ✓ | ✗ | ✓ | Owned/Licensed | Low | live (market-only board relies on this) |
| The Odds API | **Historical odds** | ✓ | ✓ | ✓ | ✗ | ✓ | Owned/Licensed | Low | — |
| The Odds API | **Event metadata** (teams/commence) | ✓ | ✓ | ✓ | ✗ | ✓ | Owned/Licensed | Low | used for market-only matchup |
| CFBD | CFB stats/lines/rosters/returning-prod | ✓ | ✓ | ✓ (reasonable) | ✗ (bulk) | ✓ | Owned/Licensed | Low | — |
| nflverse | NFL weekly stats / PBP / scores | ✓ | ✓ | ✓ | ✓ (w/ attrib) | ✓ | Owned/Licensed (CC-BY-4.0) | Medium | **attribution added** (footer) |
| nflverse-data | **NFL schedules/games** (release parquet) | ✓ | ✓ | ✓ | ✓ (w/ attrib) | ✓ | Owned/Licensed (CC-BY-4.0) | Medium | **live — feeds the NFL ATS wave via `fetch_nfl_games.py` (sidecar records license+attribution)** |
| **NBA.com** | **Game logs** (stats.nba.com) | ✗ | **✗ §9(iv)** | personal only | ✗ | ✗ | **Prohibited Until Cleared** | **Critical** | **gated (load_gamelogs)** |
| **NBA.com** | **Player tracking / advanced** | ✗ | **✗** | ✗ | ✗ | ✗ | **Prohibited Until Cleared** | **Critical** | **gated (tracking/advanced/snapshot)** |
| **NBA.com** | **Schedule** (scoreboardv2) | ✗ | ✗ | ✗ | ✗ | ✗ | Prohibited Until Cleared | High | ingestion gated; start-time omitted from market-only |
| **NBA.com** | **Injuries** (cdn/stats/official) | ✗ | ✗ | ✗ | ✗ | ✗ | Prohibited Until Cleared | High | ingestion gated (fetch_nba_injury_report) |
| **NBA.com** | **Referee assignments** (official) | ✗ | ✗ | ✗ | ✗ | ✗ | Prohibited Until Cleared | Medium | ingestion gated |
| **NBA.com/WNBA** | **WNBA game logs** (stats.nba.com) | ✗ | ✗ | ✗ | ✗ | ✗ | Prohibited Until Cleared | Critical | **gated (load_wnba_gamelogs)** |
| **NBA.com** | **Team/league logos** (marks) | ✗ | — | ✗ | ✗ | — | Prohibited Until Cleared | High | **quarantined + text/badge** |
| ESPN | Scores/scoreboard | ? | ? | ? | ? | ? | Unknown | Medium | not gated (facts; verify) |
| ESPN | Rosters | ? | ? | ? | ? | ? | Permission Required | Medium | not displayed |
| ESPN | **Player headshots** (ESPN/Getty) | ? | ? | ✗ | ✗ | ? | Permission Required | High | **not displayed** (URLs stored only) |
| NFL (NGS) | Next Gen Stats | ? | ? | ? | ? | ? | Permission Required | High | in-season NFL; verify/replace |
| MLBAM | MLB Stats API (schedule/lineups/logs) | ? | ? | ? | ? | ? | Permission Required | Medium | verify |
| MLBAM / FanGraphs / BBRef | pybaseball (Statcast/profiles) | ? | ? | ? | ? | ? | Permission Required | Medium | verify each source |
| SportsDataIO | Season futures | ? (paid) | ? | ? | ? | ? | Unknown (confirm contract) | Medium | not enabled until confirmed |
| Open-Meteo | Weather | ✗ free tier | — | ✓ paid | ? | ? | Prohibited Until Cleared (free-tier commercial) | High | **gated (fetchers + display)** |
| refmetrics / teamrankings | Umpire zones / NCAAF stats (scraped) | ? | ? | ? | ? | ? | Permission Required | Medium | verify/replace |

**nflverse-data NFL schedules/games (exact provenance):**
- **Dataset:** nflverse `schedules` (a.k.a. games) — schedule, scores/results, and recorded spread/total
  lines. The columns consumed are `game_id, season, week, gameday, gametime, home_team, away_team,
  home_score, away_score, result, spread_line` (`spread_line` is a **recorded spread**, not documented
  as a closing line).
- **URL (documented release asset):**
  `https://github.com/nflverse/nflverse-data/releases/download/schedules/games.parquet` — the same
  release `nflreadpy.load_schedules` consumes.
- **License:** CC BY 4.0, declared at `https://github.com/nflverse/nflverse-data/blob/main/LICENSE.md`.
  (We fetch from the `nflverse-data` **release**, which carries this license — we do **not** rely on the
  mutable `nfldata/master` raw path or assert it is independently licensed.)
- **Attribution:** "nflverse (https://github.com/nflverse/nflverse-data), CC BY 4.0" — recorded in each
  generation's `meta.json` sidecar and shown in the site footer alongside the other nflverse attribution.
- **Consumer files:** `fetch_nfl_games.py` (fetch/validate/publish + sidecar), `app.py`
  (`build_nfl_ats_wave` / `_nfl_ats_decisions_from_games` → `/tools/riding-the-wave`),
  `report_nfl_ats_wave_sync.py`. Stored under `data/historical/nflverse_games/` (gitignored, on-box).

**Odds rights vs league-statistics rights (explicit):** Odds API odds are licensed for commercial
display; that permission does **not** extend to league statistics. NBA.com statistics are a **separate
dataset** and are Prohibited Until Cleared — the market-only board depends only on the odds dataset.

---

## 2. Visual marks & sportsbook marks / implied affiliation
- **League/team marks** → Prohibited Until Cleared; **contained** (quarantined, text/badge, hot-link
  removed). High.
- **Sportsbook names** (DraftKings/FanDuel/BetMGM/Caesars/Yahoo) in copy → **Factual Reference /
  nominative**; add a trademark-ownership line; soften the one editorial comparison
  (`marketing/generators/weekly_cards.py:216`). Low-Med.
- **Implied affiliation** → none found in copy; the **independence/non-affiliation disclaimer is live**
  (public + authed footers). Low after disclaimer.

## 3. Generated marketing assets (cards, exports, flyers, social graphics)
- `marketing/` card/video generators + flyers + the 60 stills / 57 videos read live data and embed brand
  copy. **Permission Required / Unknown** per-asset: any that render team/league **logos** or **player
  likeness** inherit §2/publicity restrictions; any built on **NBA.com-derived stats** inherit the
  Critical dataset status. **Disposition:** audit each generated template for (a) logos, (b) player
  images, (c) NBA.com-derived stats, (d) odds attribution; regenerate cleared versions only. Social
  **preview images / OG tags** (`public_base.html` OG/Twitter = owned brand art) → Owned. Favicons/PWA
  icons → Owned.

## 4. Email, landing-page & trial-funnel claims
- Trial flyer + signup/pricing copy already carry "analytics platform, not a sportsbook / 21+ /
  1-800-GAMBLER." **Disposition:** review any email/landing/trial copy for (a) performance/"edge"
  claims that imply guaranteed results, (b) league/team/book endorsement implications, (c) the new
  independence disclaimer presence. **Factual Reference** where claims are honest + disclaimed;
  **Permission Required** for any endorsement-style framing. Counsel to review final launch copy.

## 5. Affiliate disclosures
- If any sportsbook links are or become affiliate links, an **FTC-style material-connection disclosure**
  is required at the point of the link. Current state: sportsbook names are attribution, not affiliate
  links (verify). **Disposition:** add a standing affiliate-disclosure policy before any monetized
  outbound sportsbook link ships. Unknown → resolve before launch.

## 6. Player publicity / likeness rights (promotional contexts)
- **Factual** player **names** in boards/tools are neutral identification (Factual Reference, Low).
- **Promotional** use of a player's **name, image, likeness, uniform** (ads, social, landing heroes) is
  **Permission Required** (right of publicity, state-law dependent). No player imagery is displayed
  today; stored ESPN headshot URLs are not surfaced. **Disposition:** keep player imagery out of
  promotional surfaces absent clearance; names-as-facts remain.

## 7. Privacy, cookies, analytics, session recording
- **Disposition / open items for counsel:** a published **privacy policy + cookie disclosure**; a
  lawful basis for any analytics; **no session recording** of authenticated betting activity without
  notice/consent; the Decision Journal's per-user data (below) covered by the policy. Current state:
  `legal_page.html` renders a server-supplied Terms/Privacy body flagged "should receive attorney
  review before public launch." Unknown → resolve before launch.

## 8. State gambling-adjacent compliance
- The product takes no wagers and custodies no funds (not a sportsbook), but it is **gambling-adjacent**
  (odds, props, parlay tools). **Disposition for counsel:** state-by-state review of (a) advertising/
  marketing rules, (b) 21+/age-gating sufficiency, (c) responsible-gambling messaging adequacy (1-800-
  GAMBLER present), (d) any state treating paid analytics/"picks-adjacent" tools specially. Prohibited
  Until Cleared in any state where paid gambling-analytics distribution is restricted.

## 9. User-data rights — Decision Journal & future saved research
- The Decision Journal (built, dark) stores **user-owned** records: tickets, legs, theses, settlements.
  **Disposition for counsel + the privacy policy:** data ownership (the user's), retention, export, and
  **deletion** rights; lawful basis; no sale/sharing of user betting records; security of the store
  (the design's private path + perms). Future "saved research" inherits the same contract. Resolve
  before the Decision Journal leaves dark.

---

## 10. What changed vs v1 (the amendment)
1. Register is **dataset-level** (provider × dataset) — one provider can hold several datasets under
   different terms (Odds API display vs historical; NBA.com schedule vs stats vs logos vs injuries).
2. Added the **Prohibited Until Cleared** classification and applied it to the NBA.com datasets +
   Open-Meteo free-tier commercial use + league/team marks.
3. **Odds rights separated from league-statistics rights** explicitly (the market-only board rests on
   the odds dataset only).
4. Added categories: **generated marketing assets** (§3), **email/landing/trial claims** (§4),
   **affiliate disclosures** (§5), **player publicity rights** (§6), **privacy/cookies/analytics/
   session recording** (§7), **state gambling-adjacent compliance** (§8), **user-data rights** (§9).

## 11. This is not
A legal conclusion. It is a dataset-level, counsel-ready register with risk classifications and
containment status. Implemented containment is tracked in `docs/legal_ip_audit.md` §G2; the remaining
§3–§9 items are launch-readiness questions for a qualified sports/IP attorney. Only documented
permission or counsel approval may reopen any **Prohibited Until Cleared** material.
