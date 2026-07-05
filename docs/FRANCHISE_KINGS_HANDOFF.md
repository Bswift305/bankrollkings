# Franchise Kings — Developer Handoff

_Last updated 2026-07-05. Grounded in the live codebase (verified against `git`, function
greps, and production health), not just prior notes. This is scoped to **Franchise Kings**;
the platform-level betting handoff lives in `docs/DEVELOPER_HANDOFF.md`._

---

## 0. Snapshot (verified)

| | |
|---|---|
| Branch | `master` |
| HEAD | `9f39278` Add franchise portrait automation |
| Production | `https://bankrollkings.com` — home `200`, `/healthz` `200`, `/assets/...` `200` |
| Deploy | `git push origin master` → ssh `ubuntu@32.195.123.245` → `cd /opt/bankrollkings && git pull && sudo systemctl restart bankrollkings` (**restart, not reload** — gunicorn `preload_app`) |
| Engine | `franchise_kings.py` ~7,100 lines · `franchise_offseason.py` ~390 lines |
| Web | routes + view assembly in `app.py` (`/franchise*`); templates `franchise_hub.html`, `franchise_offseason.html`, `franchise_player.html` |
| Save model | one JSON per user at `data/franchise/<user_id>.json` (gitignored). Pure functions over a `save` dict; **all migrations are idempotent backfills run in `fk.load_save`** |
| Hub tabs | dashboard · command · gridiron · roster · front-office · trades · staff · business · analytics · career · almanac · league · draft |

**Design principle in force:** every system feeds another through the `save` dict and the
sim's `power_rating` composition. Nothing is cosmetic — staff, scheme, playbook, packages,
weather, key-moments, facilities, and home-field all resolve into the number that decides games.

---

## 1. What is built & live — mapped to the Level 1–9 framework

Legend: ✅ built & deployed · 🟡 partial (exists, shallow vs. the full vision) · ⬜ not yet.

### Level 1 — The World
- ✅ **League rules as live, votable values** — salary cap (`cap_total(save)`) and playoff
  field (`playoff_seeds(save)`) are per-save and threaded through every negotiation, trade
  check, and postseason seeding. Owners vote to change them (`propose_league_vote`,
  `resolve_league_vote`): raise cap, expand playoffs, revenue sharing. 31 rival owners lean
  by archetype; a respected GM sways fence-sitters; 17 carries it. `vote_history` recorded.
- ✅ **League politics / owners' meeting** — annual proposal on the offseason recap; FOR/AGAINST/abstain.
- ✅ **Historical Almanac** — Almanac tab: season ledger (champion/runner-up/MVP + your result),
  single-season + career records book, all-time leaders (8 cats), Hall of Fame. `fk.almanac(save)`.
- ✅ **Cities (economic core)** — market multipliers, attendance/atmosphere, ticket pricing,
  concessions/parking pricing, `relocation_pressure`, public-funding stadium politics.
- ✅ **Owners (archetypes + directives)** — 6 archetypes, unique names, trust arcs, mood,
  season-end meetings, and **yearly directives** (`OWNER_DIRECTIVES`, `_issue_owner_directive`,
  `_evaluate_owner_directive`): Cheap wants profit, Impatient wants playoffs now, Meddling
  orders an early pick at your weakest spot or a splash signing, Legacy protects the franchise
  icon, Billionaire wants headlines. ±trust verdict at season end.
- ✅ **Expansion + relocation** — `activate_expansion` / `_expansion_team` (34-team activation,
  dynamic conferences), `relocation_pressure`.
- 🟡 **International games** — present, shallow.
- 🟡 **Sponsorships / TV / licensing** — `sponsorship_revenue`, `_sponsor_offer`, `sign_sponsor`,
  `sponsorship_view`. TV & streaming contract *cycles* (expiry, renegotiation) ⬜.
- ⬜ **Deep city model** (population growth, income, crime, tourism, corporate presence, tax,
  land, construction cost, college/HS football strength, youth participation as distinct vars).
- ⬜ **Deep owner model** (net worth, industry, age, political influence, public approval) and
  a constitution/rulebook as an editable object.

### Level 2 — The Franchise (organization)
- ✅ **Facilities split** — `facility_level`, `upgrade_facility`, and distinct effect functions:
  `facility_development_bonus`, `facility_medical_bonus`, `facility_scouting_bonus`,
  `facility_revenue_multiplier`, `facility_cost`; `facilities_view`.
- ✅ **Finance core** — revenue/expenses, cash balance that GATES spending, stadium/facility
  costs, cap sheet, dead money, restructures.
- 🟡 **Org chart** — GM + Head Coach = you; coordinators, head scout, medical, conditioning are
  hireable. President / Assistant GM / Legal / Finance / Marketing / HR / IT / Security as
  **distinct hireable people** ⬜.
- ⬜ **Deep finance** (credit rating, loans, debt schedule, merchandise/marketing/community/
  charity/youth-camp/international-brand as sub-systems).

### Level 3 — Football Operations
- ✅ **Coaching staff** — HC (you) + OC + DC with philosophy, scheme, **playbook packages**
  (`PLAYBOOK_PACKAGES`, `playbook_edge`), pedigree/coaching-tree, ideology, age; position/
  conditioning/scout/medical staff. Staff lifecycle (age, sharpen, fade, retire, get poached).
- ✅ **Scouting** — head-scout accuracy, `scout_report`, combine + pro days (`run_pro_day`,
  imperfect grades, medical reads).
- ✅ **Analytics-flavored outputs** — `franchise_report_card`, `gm_grade`, `contract_grade`,
  scheme-fit (`tactical_fit`), value/ROI reports.
- ✅ **Medical / sports science** — head-medical + `facility_medical_bonus`, injury risk,
  conditioning-coach development.
- ⬜ **Full staff trees as separate roles** (8 position coaches, 8 scout types, sports
  psychology, nutrition, load-management, sleep science as individually hireable people).

### Level 4 — Players
- ✅ **Identity engine** — legal / preferred (football) / nickname / jersey / middle names,
  rarity-tiered pools, **regional pools by hometown** (South/Midwest/West/Islands/Africa),
  **era pools** that drift every 8 seasons, **bloodlines** (retired greats' sons declare Jr./III),
  league-wide uniqueness + same-team disambiguation. `_gen_identity`, `ensure_player_identities`,
  `disambiguate_rosters`, `_inject_bloodlines`.
- ✅ **Personality** — 12 personalities into morale, chemistry, development, off-field incidents,
  trade fallout.
- ✅ **Development** — dev traits, peak/decline curves, hidden `true_pot` ceilings, camp/preseason
  reveals, starter-reps growth for the young.
- ✅ **Contract** — salary, signing bonus, guarantees, cap hit, **dead money**, **restructures**,
  extensions, holdouts, franchise tag.
- ✅ **Style archetypes** — per-position styles (QB Pocket/Dual/Game-Manager/RPO; RB Power/Scat/
  Every-Down; etc.) driving scheme fit and playbook installs; combine measurables + trait chips.
- ⬜ **Deep per-position ratings** (20–40 specialized attributes per position). Today a player is
  `overall` + `potential` + `style` + `combine` + traits, not a per-skill tree.
- ⬜ **Deep identity vars** (birth date, parents/family, dominant hand/foot, languages) and
  **advanced contract clauses** (no-trade, escalators, options, performance bonuses).

### Level 5 — Football (scheme & prep)
- ✅ **Playbooks / schemes / situational packages** — coordinator schemes + signature packages;
  `package_depth` / `package_power` / `package_edge` (nickel, dime, red-zone, 3rd-down, goal-line)
  feed game-week power; depth-chart package controls in the roster UI.
- ✅ **Weather** — `game_weather`, `weather_power_adjust` (city climate + game-day conditions
  shift weekly sims; shown in game logs).
- ✅ **Game plan / key moments** — Command Center calls (`key_moment_edge`, `key_moment_summary`):
  Balanced / Trust the Math / Field Position / Red Zone Punch / Two-Minute Heat, logged per game.
- ⬜ Formations/audibles as objects, explicit film-study, travel fatigue, rest-day management.

### Level 6 — Game Engine
- 🟡 **Power-resolution sim** — `power_rating` + staff + scheme + playbook + packages + weather +
  key-moments + home-field + `ai_coach_edge` → `_sim_game`; weekly injuries, off-field incidents;
  turn-based week-by-week solo season + box scores.
- ⬜ **Snap-level engine** (coverage/blocking/pressure/officiating/clock/timeouts/challenges).
  Biggest single lift; likely optional for a front-office sim — recommend extending the Key
  Moments layer before ever attempting a full play engine.

### Level 7 — League Ecosystem
- ✅ Draft, combine, pro days, **day-by-day free agency**, trades (players + **picks** + trading
  block), waivers (leagues), retirements, Hall of Fame, awards (MVP / All-League), expansion,
  relocation pressure, **rule changes via owner votes**.
- 🟡 Media / world feed (`world_report`, GridIron news).
- ⬜ College/feeder pipeline (Senior Bowl, college season, recruiting, transfer portal,
  international academies), collective bargaining.

### Level 8 — Career Mode (the signature)
- ✅ Résumé, reputation, relationships (`relationship_report`), awards, championships, failures,
  **GM report card / grade** (`gm_grade`), career timeline, poaching, firing, negotiation wins.
- ⬜ **GM progression ladder**: promoted → President of Football Ops → Commissioner → own a team;
  GM retirement + **Executive wing of the Hall of Fame**.

### Level 9 — The Living World
- ✅ **Coaching carousel** (`run_coaching_carousel`) — every rival club has a real HC/OC/DC; they
  age, retire, get fired into a league pool, get promoted (coordinator → HC, the tree grows);
  your poached/fired coaches resurface across the league. Rival coaching affects the sim
  (`ai_coach_edge`).
- ✅ **Player → coach pipeline** (retired players enter the coaching market; bloodline sons enter
  the draft). Dynasties rise/fall (Almanac), records break, expansion/relocation, rule changes.
- 🟡 **Culture / relationships / world** — `culture_report`, `relationship_report`, `world_report`.
- ⬜ Owners age/die/sell → **heirs inherit**; scouts→coaches→GMs→president full pipeline;
  economies crash; TV-contract cycles; fan generational turnover.

### People Ecosystem (cross-cutting)
- ✅ Coaching carousel + coaching trees; retired-player-to-coach; bloodline draft entrants.
- ⬜ The full pipeline: HS → college recruit → draft/UDFA → practice squad / dev league → retire
  → coach **or** scout **or** broadcaster **or** agent **or** exec; scout → personnel director →
  assistant GM → GM → President → (rare) Commissioner. **Biggest remaining differentiator** —
  build as ONE unified "person career-state machine," not per-role one-offs.

---

## 2. Portrait automation (foundation shipped `9f39278`; art library still needed)

**In place & verified:** `portrait_assets.py`; the `assets/` tree; `assets/scripts/slice_sheets.py`
+ `assign_portraits.py`; app serves `/assets/...` (prod `200`); players/prospects carry
`portrait_id`; new + backfilled saves auto-assign when metadata exists; profile pages + roster
rows show portraits with the initials-avatar fallback. Selection is tag-aware (age range, body
type, position bias, category, current-save avoidance).

**Remaining — only the art itself:**
1. Generate/import portrait sheets or 512×512 PNGs.
2. `python assets/scripts/slice_sheets.py --input <sheet.png> --cols 10 --rows 10 --start 1
   --output assets/portraits/players/active --age-range young --body-type athletic
   --position-bias "WR|CB|RB"`
3. Fill tags in `assets/metadata/portraits.csv` / `.json`.
4. `python assets/scripts/assign_portraits.py data/franchise/<save_id>.json` (`--dry-run` to preview).
5. Extend assignment to coaches/owners/GMs/scouts/agents/media.

---

## 3. Recommended build order (highest immersion-per-effort first)

1. **Unified People career-state machine** — one `person` model + lifecycle every human (player,
   coach, scout, exec, owner, agent, media) flows through. Collapses many ⬜ Level-9 items into
   one system and unlocks the "HOF QB becomes the coach who wins elsewhere" payoff. Highest leverage.
2. **GM progression ladder + Executive Hall** — promote to President/Commissioner/owner, GM
   retirement, exec HOF wing in the Almanac. Completes the signature Level-8 loop; small effort.
3. **Owner mortality & succession** — owners age, sell, or pass teams to heirs. Mortal world;
   medium effort, big flavor.
4. **Deep per-position ratings (opt-in)** — expand `overall+style` into per-position skill trees
   feeding sim + scouting. Large; gate behind a "sim depth" flag to protect balance.
5. **Feeder pipeline** — college/Senior Bowl/UDFA/dev-league so the draft has a visible source.
6. **Finance depth + TV-contract cycles + org chart as hireable people.**
7. **Interactive game day** — extend Key Moments into a drive-level "key situations" mode before
   attempting a full snap engine.

Keep the running roadmap in `docs/franchise_kings_plan.md` (source of truth between sessions).

---

## 4. Architecture & conventions (read before touching the engine)

- **Save-dict discipline.** Everything hangs off `save`. New per-save systems get a key; new
  fields on players/teams get **idempotent backfills** in `fk.load_save` (see
  `ensure_staff_profiles`, `ensure_team_histories`, `ensure_player_identities`, `ensure_ai_staffs`)
  so existing saves upgrade on load without data loss or renames.
- **Constants → save values when votable.** Cap and seeds moved from module constants to
  `cap_total(save)` / `playoff_seeds(save)`; follow that for anything the league can change.
- **The sim reads one number.** Anything meant to affect games folds into `power_rating` / the
  `powers[...]` composition in `sim_week` + `_finalize_season` (staff, scheme, playbook, packages,
  weather, key-moments, home-field, `ai_coach_edge`). User team uses the rich `staff_bonus` path;
  AI teams use `ai_coach_edge` — keep that split.
- **Offseason is a stage machine.** `franchise_offseason.py` `STAGES`: recap → staff → workouts →
  resign → free_agency → draft → camp → preseason → cuts → kickoff. New surfaces attach as a stage
  or a card within one; staff/trade actions are offseason-aware in their routes.
- **StrictUndefined templates.** Jinja runs strict — guard optional context (`x is defined and x`)
  or a missing key 500s the page. Use item access (`d['get']`) for keys named like dict methods.
- **Windows / OneDrive gotchas.** Repo lives in OneDrive; git may throw transient loose-object
  lock warnings mid-commit (verify with `git cat-file -t <sha>`). LF↔CRLF warnings on template
  writes are cosmetic.
- **Verification pattern (every change).** Compile (`python -m py_compile`), then a headless
  `app.test_client()` script that seeds a temp all-access user in `data/tracking/NBA_Users.csv`,
  drives the new engine + route + template, asserts behavior, and **cleans up the temp user +
  save in a `finally`**. Then deploy + `curl /healthz`.

---

## 5. Deploy runbook

```bash
git push origin master
ssh -i ~/.ssh/bankroll-key.pem ubuntu@32.195.123.245
cd /opt/bankrollkings && git pull origin master
sudo systemctl restart bankrollkings          # RESTART — reload won't reload preloaded code/templates
systemctl is-active bankrollkings              # -> active
curl -s -o /dev/null -w '%{http_code}\n' https://bankrollkings.com/healthz   # -> 200
```

_Production infra (EC2 `32.195.123.245`, SSH via `bankroll-key.pem`, security-group port-22 pinned
to the operator's current IP) is documented in `docs/PROJECT_MAP.md`._
