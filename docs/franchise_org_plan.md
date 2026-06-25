# Franchise Kings — Organizational Identity, Scouting & Weekly Ops (Design Plan)

> Status: **PLAN / not built.** Review + edit freely. Build order at the bottom.
> Owner: GM (Darrel) + developer. Last revised by the assistant from the live codebase.

## 0. The thesis

A player is not "good" or "bad." A coach is not "85 OVR." A scout is not "accurate."
The franchise should always be asking:

> **Does this person fit the people, scheme, temperament, and development culture we have built?**

Goal: make every personnel decision feel like *"He can succeed — but is this the right building for him?"* And make **scouting the thing that answers it.**

---

## 1. What already exists (integration points — DO NOT rebuild)

This is the most important section: the fit *engine* is largely already in the codebase. New work should extend these, not duplicate them.

**Player makeup (already generated on every player + prospect)** — `franchise_kings.py`
- `_gen_human_profile(rng)` / `ensure_human_profile(p)` → `motivation`, `learning`, `coach_pref`, `confidence`, `work_ethic`
- `personality` (12 types, dev nudge), `style` (per-position archetype), `dev` trait, `true_pot` (hidden ceiling)
- `human_development_fit(save, p)` → `{score, label, notes}` (scheme fit + coach-style match + learning×staff + motivation + work ethic/confidence)

**Coach makeup (already generated on every staff candidate)** — `franchise_kings.py`
- `_gen_staff(rng, role)` → `rating`, `style` (position coaches), `system` (coordinators' scheme / conditioning style), `philosophy` (coordinators), `ped`
- `_coach_pedigree(...)` → `tree`, `mentor`, `experience`, `stops[]`, `pros/playoffs/rings`, `rep`, `label`
- `conditioning_dev(save)` → growth / durability / **ceiling unlock**
- `staff_bonus(save)`, `scheme_effect(save)`, `position_coach_dev(save, pos)`

**Fit / league reads already wired**
- `tactical_fit(save, p)` (scheme fit %), `scheme_identity(save)`
- `league_context(save)` (power rank, window, position-vs-league, scarcity, rival)
- `consultant_advice(save)` (league-aware tips)
- `draft_state(save)` already attaches `fit`, `fit_pct`, `human_fit`, `human_fit_score` to prospects
- `_dev_outlook(save, grade, pot)` (in `app.py`) — "can your staff develop this project?"
- `_advance_year(save)` / `_develop(p, rng, bonus)` — where development + ceiling unlocks happen

**UI surfaces already present**
- Player/prospect profile: "Human development fit" card (`templates/franchise_player.html`)
- Draft board: `Fit` + `Human` columns (`templates/franchise_hub.html`)
- Dashboard: "Player Evolution" feed (`evolution_notes`)
- Staff tab: coach pedigree + "Player Development Engine" (conditioning) panels

**Net:** we already compute scheme fit, human fit, conditioning unlock, and a dev outlook. What's missing is (a) **coach ideology depth**, (b) a **scout verdict** that packages all of it, and (c) the **weekly operating rhythm**.

---

## 2. System A — Coach / Staff Ideology

Coaches currently have `style` + `system` + `philosophy` + `ped`. Add the ideology layer.

### Data model — extend `_gen_staff` output
```jsonc
{
  "ideology": "Hard-nosed",        // Teacher / Hard-nosed / Player's Coach / Technician / Motivator
  "versatility": 42,               // 0-100: Rigid (low) ↔ Adaptive (high)
  "temperament": "Demanding",      // Demanding / Calm / Charismatic / Old-school / Analytical
  "specialties": ["OL", "discipline", "run game"],
  "struggles_with": ["fragile confidence", "spotlight players"],
  "scheme_rigidity": 0.7           // how locked-in to one system (1 = rigid)
}
```
- Correlate with `rating` + `tree` (a prestigious tree → sharper ideology). Reuse the pedigree's `rep`.
- `versatility` is the key new lever: **rigid + elite** = huge bonus for matching players, penalty for misfits; **versatile** = moderate bonus to many players (safer for rebuilds).

### Functions to add (`franchise_kings.py`)
- `coach_roster_fit(save, coach)` → `{score, notes}` — how well a hired/candidate coach fits the **roster you already have** (sum of player↔coach fit across his group, weighted by versatility).
- Fold ideology into `human_development_fit` (coach temperament vs player confidence/personality; specialties vs player position/issues).

### UI
- Staff hire market (`franchise_hub.html` staff tab): show `ideology`, `versatility`, "Best with / Weak with", and a **Roster Fit** score per candidate.
- Hired coach card: ideology line under the pedigree.

### Development impact (`_advance_year`)
- A matched ideology adds to the per-player dev bonus; a clash subtracts. Versatility widens how many players get *some* bonus.

---

## 3. System B — Scout Recommendation Layer  ← **highest leverage, build first**

This is the piece that makes scouting *matter* and is the clearest expression of the thesis. It mostly **packages numbers we already compute**.

### Function to add (`franchise_kings.py`)
```python
def scout_report(save, p):
    """Compare raw (leaguewide) value to fit-here value and return a verdict."""
    # league_grade  = the player's raw grade/OVR (what every team sees)
    # here_grade    = league_grade adjusted by: tactical_fit + human_development_fit
    #                 + dev_outlook (for projects) + coach ideology match
    # rec  ∈ Must Target / Strong Fit / System Bet / Raw Talent Only / Bad Fit Here / Scout Disagreement
    # reason = one line ("OC runs West Coast, QB coach is a Teacher, he learns by structure")
    # risk   = one line ("if the OC changes, his value drops" / "needs role clarity or he stalls")
    # confidence = gated by head_scout rating (a weak scout gives a fuzzier read)
    return {"rec": ..., "reason": ..., "risk": ..., "here_grade": ..., "league_grade": ...,
            "best_env": "Teacher + West Coast + structured role",
            "dev_path": "Yr1 slot role, Yr2 starter competition"}
```
- `here_grade = league_grade + k1*(scheme_fit−neutral) + k2*(human_fit−50) + project_bonus`. Tune `k1,k2` so a 72 raw can read ~84 here (and vice-versa).
- **Scout accuracy gates the read:** strong `head_scout` → tight, confident verdict; weak → "Scout Disagreement" / wider hedging. This is finally where the scout hire pays off.

### UI
- Draft board + Free Agency: add a **Scout** column (the rec label, colored) next to Grade / Scheme / Human.
- Player/prospect profile: a **"Scout's Team Fit Report"** card — `rec`, best environment, our fit vs raw, risk, development path.

Example board:
```
Player         Grade  Scheme  Human  Scout
Marcus Reed     73      91      88    Must Target  (84 fit here)
Trey Cross      81      45      39    Bad Fit Here (raw talent only)
```

---

## 4. System C — Weekly Command Center  (the fantasy-football rhythm; biggest build)

Turn Franchise from "menus between sims" into a **weekly operating rhythm**. This is the daily-engagement hook and should come *after* the scout/ideology layer (it leans on both).

### Ties into what we already built
- The **live clock** (`live_tick`, `pending_decision`, pause-for-approval) is the spine: the season auto-advances, but **pauses at the weekly checklist** the same way it pauses for a trade offer. If the GM skips, the **assistant/coach auto-resolves** based on staff ideology.

### Data model
```jsonc
weekly_ops: {
  week: 4, day: "Wednesday",
  checklist: [ {key:"practice",done:false}, {key:"injuries",done:false},
               {key:"scouting",done:false}, {key:"player_meeting",done:false},
               {key:"game_plan",done:false} ],
  practice: { intensity: "Balanced", focus: "Pass Game" },
  scouting_assignment: "Opponent",
  player_meeting: null,
  medical_policy: "Limited Reps",
  game_plan: "Balanced",
  events: []
}
```

### Core weekly decisions (keep MINIMAL first)
1. **Practice intensity** — Recovery / Balanced / Physical / High-tempo (sharpness ↔ injury risk)
2. **Practice focus** — Scheme install / Red zone / Pass / Run / Pass rush / Coverage / Ball security / Rookie dev
3. **One player touchpoint** — boost confidence / demand accountability / clarify role (→ morale/confidence)
4. **Scout assignment** — Opponent / Draft / FA / Trade market / Internal (→ reveals fit, hidden risk)
5. **Medical policy** — Rest / Limited / Push to play (availability ↔ aggravation)
6. **Game plan** — Aggressive / Conservative / Balanced / Attack weakness / Protect injured unit

### Effects (reuse existing systems)
- focus → `_develop` bonus / scheme-install power; intensity → injury roll; player meeting → morale/confidence/role-friction; medical → availability; game plan → a matchup edge in `_sim_game`.

### UI — a **Command Center** view/tab
Today's checklist · injury report · practice plan · staff recommendations · one player issue · scouting assignment · game plan · **Advance day / Sim week**.

### Multiplayer
Each GM gets the weekly checklist; if a GM is inactive, the assistant auto-handles by staff ideology (no GM gets stuck waiting).

### Later depth (Phase 4+)
Weekly staff meeting (each coordinator brings a concern), player conversations, locker-room pulse, team captains, staff trust in the GM, media/owner pressure, daily event ticker.

---

## 5. How it all feeds development (the payoff loop)

- `scout_report` → smarter **draft/FA decisions** (fit over raw).
- coach ideology + human fit → bigger/smaller **`_advance_year` dev bonus**, **conditioning ceiling unlocks**, **morale**, **role friction**.
- weekly practice/touchpoints → in-season **confidence/morale/sharpness** nudges.
- scout accuracy (`head_scout`) → how much **truth** the GM sees before deciding.

---

## 6. Recommended build order

- **Phase 1 — Scout Recommendation layer** (System B). ✅ SHIPPED. `scout_report()`; Scout column on board + FA + "Scout's Team Fit Report" card. Verdict moves with your staff.
- **Phase 2 — Coach/staff ideology depth** (System A). ✅ SHIPPED. Ideology/versatility/temperament + `coach_roster_fit()` on hire; feeds `human_development_fit` → scout + yearly development.
- **Phase 3 — Weekly Command Center MVP** (System C). ✅ SHIPPED. New Command Center tab + `weekly_ops` standing plan (practice intensity/focus, medical policy, game plan, scout assignment) that REALLY bends the season — power edge, injury rate, return speed, rookie dev, draft scouting accuracy. Next: player-meeting events + live-clock checklist pause (Phase 4).
- **Phase 4 — Weekly depth**: ✅ CORE SHIPPED. Weekly agenda (staff meetings → trust, player conversations → morale/confidence, injury participation → rest/limited/push) + Locker Room pulse (chemistry/morale/staff-trust/volatility) + auto Captains, all in the Command Center. Remaining: media/owner pressure events, daily Mon–Sun cadence.
- **Phase 5 — Multiplayer weekly checklist** + auto-resolve for inactive GMs.

Each phase ships independently and is verifiable on its own.

---

## 7. Open decisions (settle before building)

1. **Final scout label set?** (proposed: Must Target / Strong Fit / System Bet / Raw Talent Only / Bad Fit Here / Scout Disagreement)
2. **Does fit affect on-field performance, or only development?** Recommendation: **development + morale only** at first (raw on-field power already bends via `scheme_effect`; avoid double-counting). Revisit a small game-day edge later.
3. **Solo cadence:** the live clock is currently *weekly*. Command Center can be weekly-only for solo (a real daily tick is a bigger change). Multiplayer can feel "daily" via the checklist.
4. **Rigid-elite vs versatile coach:** how big should the swing be? (suggest rigid match ≈ +2 dev / mismatch ≈ −1; versatile ≈ +1 across the board.)
5. **here_grade weighting:** pick `k1` (scheme) and `k2` (human) so a 72 raw can legitimately read ~84 in a perfect building — and a misfit star drops to the 40s.
6. **Auto-resolve policy:** when a GM skips the weekly checklist, the assistant picks by staff ideology — confirm that's the desired default (vs. a neutral safe default).

---

## 8. Retention & Standout — what the research says (June 2026)

Dug into Football Manager, OOTP, fantasy apps, and game-retention/habit literature. It converges on **one framework: the Hook Model** (trigger → action → variable reward → investment). Map Franchise to it and the gaps are obvious.

| Hook stage | What it is | What we already have | The gap to close |
|---|---|---|---|
| **Trigger** | what pulls them back | live-clock countdown, owner texts | **external alerts** (push/email/in-app) — fantasy apps' #1 retention tool; we have a service worker, so push is feasible |
| **Action** | the ~15-min loop | sim a week, make moves | **Weekly Command Center** checklist ("3 things before you advance") |
| **Variable reward** | the dopamine | hidden gems, breakouts, ceiling unlocks | make them *feel* like a lottery — "did my rookie pop?", draft-day swings, scout finds. Variable (vs fixed) rewards raise session frequency ~50% |
| **Investment** | what makes leaving costly | GM grade, developed players | a **career legacy** you've sunk hours into (see Timeline below) |

**The single standout to build (research-validated + cheap for us): a Dynamic Career Timeline.**
FM's most-loved retention feature is the *Dynamic Manager Timeline* — a scrollable story of your career with 50+ event types you can look back on. We **already generate every event it would need** — titles, owner verdicts, breakouts, ceiling unlocks (the 66→88 project you coached up), holdouts, suspensions, hot-seat survivals, trades, draft steals — we just don't thread them into one memory feed. This turns "spreadsheet franchise" into *your story*, and a story is the thing users won't abandon. **High payoff, low lift** because the data exists.

**Other research-backed pulls, ranked for us:**
1. **External alerts** (push/email/in-app inbox) — the trigger fantasy apps live on. "Your RB is questionable," "scout found a fit," "rival sent a feeler," "owner wants an answer." Transitioning users from external triggers to *internal* ones (boredom/curiosity) is what creates unshakeable retention. We have the service worker; this is the highest-leverage retention add.
2. **Player Buy-In / Dynamics** (FM) — players visibly *believe* (or don't) in your plan; weekly conversations and honored promises move it; broken ones cost you. Human conflict with **tangible fallout** is what reviewers say franchise modes lack. Ties straight into our morale / role-friction / holdout systems.
3. **Owner quest-goals** (OOTP) — staged, story-like owner objectives beyond "make the playoffs" ("develop a homegrown Pro Bowler," "win without a top-10 payroll"). We already have owner mandates + the meeting; make them a multi-season questline.
4. **League Newsroom + social wall** (fantasy leagues + OOTP Perfect Team) — weekly power rankings, team-of-the-week, upset-of-the-week, hot-seat GM, a trade block / press-quote wall. For multiplayer this is the "your absence affects others" social hook — the strongest retention mechanic there is.
5. **Daily/weekly routine + streak** — daily-login rewards are used by ~95% of games for a reason; pair with the Command Center checklist.

**Recommended retention sequence (slots into the Section 6 build order):**
- alongside **Phase 3 (Command Center)**: add the **in-app alert inbox** (triggers) and the **Career Timeline** (investment) — they're what make the weekly loop *stick*.
- **Phase 6**: external push/email alerts.
- **Phase 7**: League Newsroom + social wall (multiplayer stickiness).

**Sources:**
[FM Dynamic Manager Timeline](https://www.footballmanager.com/features/dynamic-manager-timeline) ·
[FM24 squad dynamics / Buy-In](https://community.sports-interactive.com/sigames-manual/football-manager-2024/your-squad-team-report-and-dynamics-r4957/) ·
[OOTP 25 review (owner goals, dynasty narrative)](https://www.operationsports.com/out-of-the-park-baseball-25-review-an-impressively-deep-managerial-experience/) ·
[Game retention mechanics (daily loop, routines, social)](https://www.vgames.vc/post/hooked-on-your-game-how-to-use-retention-mechanics-to-keep-players-coming-back) ·
[Hook Model / variable rewards](https://www.nirandfar.com/want-to-hook-your-users-drive-them-crazy/) ·
[Hook Model overview (Amplitude)](https://amplitude.com/blog/the-hook-model)
