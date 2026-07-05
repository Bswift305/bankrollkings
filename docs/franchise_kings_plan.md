# Franchise Kings — GM Career Mode (build plan)

> A turn-based, browser-based **GM career simulator** on Bankroll Kings. The user
> is NOT a team — they are a **General Manager building a career**. Win and bigger
> teams poach you; lose and you get fired and rebuild your reputation elsewhere.
> Football (NFL-style). Fictional league (see §2).

> **SCOPE LOCKED (2026-06-22):** full feature build, not an MVP. **32 teams**
> (2 conferences x 4 divisions x 4), **solo career mode** (1 human GM + 31 AI;
> true human-vs-human multiplayer is a deferred architecture option — the
> requirement is only that one person can play). All systems below are committed:
> scouting, draft, trades, staff/coaching, stadium/business, player
> development/injuries, and the analytics ("Value Intelligence") layer. The user
> will not playtest until the whole set is in, so phases ship incrementally
> (free/gated, never touching the betting product) and get played as a finished
> product. Build order in S10.

---

## 1. The hook (what makes this different)

The GM is the main character, with a **career that persists across teams**. The
emotional loop is *"Are you building the team, or building your career?"* — you
might leave a team before it collapses, or take a rebuild to boost your legacy.
That career arc (hired / extended / **fired** / **poached**) is the retention
engine. Everything else (roster, staff, stadium) serves it.

## 2. Two hard constraints that shape everything

1. **Fictional league — no real names/logos/players.** Real NFL teams and player
   likenesses are licensed (why only EA/2K have them). We generate fictional
   cities, team names, and players procedurally. This is freeing: full creative
   control, zero legal exposure. Theme it as the **"BRK League."** (Real player
   *stats* for the betting product stay separate and are unaffected.)
2. **Turn-based, server-rendered — not a 3D game.** Menus, cards, dashboards, and
   a simulated season. This fits the existing Flask stack exactly and reuses the
   **Fantasy module's architecture** (login-gated tabbed hub, per-user save,
   simulation engine). No game engine.

## 3. Reuses existing infrastructure

- **Auth + gating:** same `PUBLIC_ENDPOINTS` / login-required pattern as Fantasy.
- **Per-user save:** mirrors `data/tracking/Fantasy_Lineups.csv`, but state is
  nested, so use **JSON per user**: `data/franchise/<user_id>.json`.
- **Tabbed hub UI:** like `fantasy_league.html` (Overview / Roster / Front Office
  / Career / League), blanking the betting `workflow_toolbar` like Fantasy does.
- **Sim mindset:** the same Monte-Carlo / rating-driven thinking already in
  `simulate_active_sport_props.py` and the fantasy projection sim.
- **Brand:** dark + cyan shell, the new BRK icons.

## 4. MVP — v0.1 (the thinnest loop that's still fun)

> Create GM → take a struggling team → view roster → make a few moves → **Sim
> Season** → owner evaluation → **extended / fired / poached** → career screen.

Scope cuts for v0.1:
- **16-team** fictional league (expandable later), single conference/division
  structure, round-robin-ish schedule (~14 games) + a small playoff.
- Rosters simplified to **key positions** (QB, RB, WR×2, TE, OL, DL, LB, CB×2, S,
  K) — ~22 starters + a few backups, NOT a full 53 with special-teams depth.
- Moves in v0.1: **sign 2 free agents**, set the **depth chart**, that's it.
  (Draft, trades, staff, stadium are later phases.)
- Season sim produces a W-L record + standings + a champion.
- Owner sets a one-line expectation; result vs expectation moves **owner trust**;
  trust + record decide **fired / extended / job offers**.
- One signature analytics metric in v0.1: **Team Power Rating** (so it feels BRK).

## 5. Data model (v0.1)

```
GM            { name, background, ratings{drafting,trading,free_agency,cap,
                staff,development,media}, owner_trust, fan_support, reputation,
                career[ {season, team, record, result, outcome} ] }

Background    archetype -> rating tilt (see §6)

Team          { id, city, name, market_size, owner{type,expectation},
                cap_total, cap_used, roster[player_id...], record{w,l},
                power_rating }

Player        { id, name, pos, age, overall, potential, dev_trait,
                contract{years, aav, guaranteed}, morale, injury_risk, traits[] }

LeagueSave    { season, user_gm, current_team_id, teams[], free_agents[],
                schedule[], standings[], history[] }   // the per-user JSON file
```

## 6. GM backgrounds (v0.1 — pick 1 at creation)

| Background      | Strength                 | Weakness                  |
|-----------------|--------------------------|---------------------------|
| Scout           | better draft grades      | weaker contracts          |
| Analytics nerd  | better projections       | players warm slower       |
| Former player   | locker-room respect      | weaker cap management      |
| Cap expert      | better payroll control   | weaker scouting           |
| Coach-turned-GM | better staff hiring      | owner questions biz moves |

(Draft/staff effects matter more in later phases; in v0.1 the tilt mainly nudges
the sim + free-agency outcomes.)

## 7. Season simulation (v0.1 approach)

1. **Team strength** = position-weighted average of starter `overall` (football =
   QB-heavy weighting), nudged by GM ratings (e.g., `development` slightly raises
   young players over the year). This is the **Power Rating**.
2. **Each game:** `P(win) = logistic(k * (powerA − powerB) + home_edge)`, then a
   seeded random draw → result (W/L; a simple score is cosmetic). Seeded RNG so a
   replayed season is stable.
3. **Standings → playoffs → champion.**
4. **Owner evaluation:** compare W-L (and trajectory) to the owner's preseason
   expectation. Over/underperform → `owner_trust` delta.
5. **Career outcome:** `owner_trust` below a floor → **fired**; strong
   overperformance → **extension** + possible **poach offers** from better teams;
   middling → continue. Append to `GM.career`.

Engine lives in `services/franchise_sim.py`, sport-agnostic where practical so a
basketball league can plug in later.

## 8. Screens (v0.1)

- **Dashboard:** GM reputation, owner trust, fan support, record, the owner's
  current expectation, "Sim Season" button.
- **Roster:** player cards (name/pos/age/OVR/potential/contract/morale), depth
  chart ordering, Power Rating.
- **Front Office:** free-agent list, sign (cap-checked).
- **Career:** résumé — seasons, teams, records, championships, firings, offers.
- **League:** standings, champion, league leaders.

## 9. The Bankroll Kings twist (analytics layer — phased in)

These are the differentiators vs a generic sim and reuse our analytical DNA:
- **Contract Value grade** (AAV vs projected production)
- **Player ROI** (production per cap dollar)
- **Team Power Rating** (v0.1) and **per-game Win Probability / playoff odds**
- **Draft Value chart** (pick value), **trade fairness score**
v0.1 ships Power Rating; the rest layer in with their systems.

## 10. Phase roadmap

- **v0.1 — Core career loop** (this doc's MVP): create GM, sign FAs, set depth,
  sim season, owner eval, fired/extended/poached, career screen. Fictional
  16-team league. JSON save.
- **v0.2 — Rookie draft + scouting:** generated draft classes, scouting accuracy
  (GM/scout-driven), draft-day UI.
- **v0.3 — Trades + deeper free agency:** trade engine + fairness score, bidding.
- **v0.4 — Staff:** hire HC/coordinators/scouts/medical/analytics; staff ratings
  feed the sim (development, injury prevention, projection accuracy).
- **v0.5 — Business + stadium:** revenue, ticket/merch/sponsorship, facility &
  stadium upgrades, debt, fan happiness, budget set by owner.
- **v0.6 — Player life:** aging curves, dev traits, injuries, morale events,
  holdouts, retirements.
- **v1.0 — Career depth + analytics:** the "GM tree," owner personalities,
  expansion mode, full Value Intelligence dashboard; polish + balancing.

## 11. Tech notes

- **Routes:** `/franchise` hub (login-gated, add to the same gating set as
  Fantasy), with tab sub-routes; POST endpoints CSRF-protected like fantasy
  lineup saves.
- **Storage:** `data/franchise/<user_id>.json` (one save per user for v0.1; multi-
  save/league slots later).
- **Generation:** fictional name pools (first/last), city + mascot pools, player
  generator (position-appropriate OVR/potential/age distributions).
- **Determinism:** seed RNG from the save so sims are reproducible (don't use the
  blocked `Math.random`/`Date.now` patterns server-side; seed explicitly).
- **Templates:** `franchise_*.html` extending `bk_base.html`, blanking
  `workflow_toolbar` (disconnected from the betting shell, like Fantasy).

## 12. Open decisions (need your call before/within the build)

1. **Access gating:** free hook to drive signups, or All Access only, or a free
   demo season then paywalled? (Affects funnel.)
2. **League size for v0.1:** 16 (recommended, faster sim/UI) vs full 32.
3. **Tone/naming:** "BRK League" with fully invented teams, or generic
   city+mascot only? Any cities you want included.
4. **Save model:** single save per user for v0.1 (recommended) vs multiple slots.

---

**Status:** plan only — no code yet. Next step on approval: scaffold the v0.1
loop (create GM → sim season → owner outcome → career), 16-team fictional football
league, JSON save, reusing the Fantasy hub patterns.

---

## FOF9-inspired roadmap (user request 2026-07-04, from the Reddit/FOF9 study)

Much of FOF9's list already exists in Franchise Kings (cap/contracts/extensions/
holdouts, agent personalities + counters, scouting noise + hidden ceilings,
combine + pro days, pick trading + trading block + deadline, practice squad,
chemistry/mentors/personalities, aging curves, stadium/ticket/attendance economy,
owner archetypes + firings, GM career + poaching, records book, All-League team,
HOF, box scores, multiplayer leagues). SHIPPED from this pass: **League Almanac
tab** (season ledger w/ champion/runner-up/MVP + user result, records book,
all-time leaders, Hall of Fame in one dense book).

Remaining gaps, in rough priority order:
1. **Depth charts & situational packages** (nickel/dime/red-zone/3rd-down starters,
   role weighting in the sim) — biggest football-feel gap.
2. **Contract restructures** (convert salary to signing bonus, dead-money
   acceleration on cuts) — biggest cap-feel gap.
3. **Day-by-day free agency** (agents lower asks as FA days pass; loyalty
   re-signs like the Seahawks-safety story).
4. **Weather** (city climates, game-day weather affecting sim + box scores).
5. **Concessions/parking pricing + relocation & public stadium votes.**
6. **Play calling / interactive game day** (drive-by-drive choices) — the
   biggest lift; consider a "key moments" mode (4th downs, 2-min drill choices).
7. **Franchise evaluation report card** (team/financial/roster/franchise-value
   four-grade year-end review).
8. **Interface density pass** — FOF-style compact tables as a user-selectable
   "Data mode" across franchise screens.
