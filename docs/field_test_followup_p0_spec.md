# Field Test Follow-Up P0 Specification — 2026-10-10

**Rev 2 — APPROVED NARROWER RELEASE PATH.** Rev 1 (the `/my-decisions` free-log proposal) was
rejected. This revision reflects the governance ruling. **Status: SPEC + implementation of the
approved Commits A & B.** Rev 1 preserved in git history (commit 931179c).

**Three corrections accepted:**
1. **The free decision log was NOT a minimal reuse.** The tracker records American odds, stake,
   selection, settlement state, optional closing odds; a saved "read" (sport/player/line/side/
   note/timestamp) is a different record — mapping it in would need fake odds/stake and
   contaminate ROI/CLV/learning. "No schema migration" was wrong. **Do not build `/my-decisions`
   in this release.** Instead, **remove the free "saved tickets" promise.** A genuine My
   Decisions feature gets its own later product contract + storage design.
2. **Free-preview authority fix was incomplete.** Softening `free_tier.html:489` left the same
   hindsight/promotion claim at `:519` ("Missed Winners show strong model reads that hit … then
   feed tomorrow's promotion logic"). **Hide the whole "Missed Opps" preview card from non-owner
   users** — not cosmetic softening. Missed Winners = owner/admin only (paying ≠ governance
   authority). Calibration = All Access only (hidden from free nav).
3. **Do not hardcode personal tester emails** in public source. Provision field-test access
   through private operational config; remove after the visit.

---

## Commit A — Free preview and navigation

### A1 · Neutral implied-probability framing (`templates/free_tier.html`, `app.py:449`)
- **`free_tier.html:489` current:**
  `<small>Review Center turns resolved hit/miss data into player profiles, confidence calibration, and missed-winner proof.</small>`
  **→** `<small>Review Center turns resolved hit/miss data into player profiles, confidence calibration, and a record of what did and didn't hit.</small>`
- **Caption on the implied-% sample list** — insert under the "Parlay Builder Example" head
  (after `free_tier.html:433`), exact:
  `<small>Sample rows, ordered by de-vigged market-implied probability — the market's read, not our picks. Heavy favorites (very low payouts) sit at the top.</small>`
- **Chip label** — `free_tier.html:446` current `<span class="free-builder-chip">{{ row.implied }}%</span>`
  **→** `<span class="free-builder-chip">{{ row.implied }}% implied</span>`
- **Free-plan summary** — `app.py:449` current
  `'summary': 'Know what is happening tonight across every sport. Slate, environment, top plays, and injuries — no subscription required.',`
  **→** `'summary': 'Know what is happening tonight across every sport. Slate, environment, the market's top-implied props, and injuries — no subscription required.',`
  (`app.py:453` is already market-framed — leave.)

### A2 · Hide the "Missed Opps" preview card from non-owner (`free_tier.html:516–521`)
Wrap the entire `<div class="free-command-card">` for "Missed Opps" in
`{% if show_ops_strip %} … {% endif %}` (owner/admin-only global). Non-owner users never see the
"feed tomorrow's promotion logic" claim. The Calibration card (`:510–515`) stays — its framing
("checks whether the model's 60/70/80% bands actually behave that way") is transparent
evaluation, not predictive authority.

### A3 · Navigation gating (`app.py` `build_sport_workflow_nav`, def 1445; items 1529–1544)
The nav builder has one caller, `inject_globals` (`app.py:29092`, request scope), which already
resolves `current_user` and `show_ops_strip`. Pass two flags in:
- Signature → `def build_sport_workflow_nav(active_sport='', active_page='', can_see_missed=False, can_see_calibration=False):`
- After `items.extend([...])` (before the group-assignment loop), drop the gated keys:
  ```
  if not can_see_missed:
      items = [it for it in items if it['key'] != 'missed']
  if not can_see_calibration:
      items = [it for it in items if it['key'] != 'calibration_lab']
  ```
- Caller (`app.py:29092`):
  ```
  nav_paid = bool(current_user and (is_owner_user(current_user) or normalize_user_plan(current_user) == 'all_access'))
  top_nav_items = build_sport_workflow_nav(nav_sport, active_page_key, can_see_missed=show_ops_strip, can_see_calibration=nav_paid)
  ```
  → **Missed Winners** shows only for owner/admin (`show_ops_strip`); **Calibration** shows only
  for owner/all_access. This also removes the non-owner click-through 403s. Defaults are
  restrictive (`False`) so any future caller is safe.
- Follow-up check (not code here): confirm the `/calibration-lab` page framing is transparent
  evaluation, not predictive authority, before relying on paid visibility.

---

## Commit B — Honest free-plan copy (remove saved-ticket promise)

No free-reachable surface may promise saved tickets (an All-Access feature). All Access pricing
keeps its saved-tickets line (accurate, untouched).

- **`app.py:455`** current `'Free account, saved tickets, and platform access',`
  **→** `'Free account with honest sport previews and feedback access',`
- **`signup.html:14`** current
  `<p>Save tickets, keep review history, and unlock the whole platform with one membership — All Access, {{ all_access_tier.monthly_label }}. No tiers, no upsells.</p>`
  **→** `<p>Create a free account to explore honest previews across every sport and send feedback. All Access, {{ all_access_tier.monthly_label }}, unlocks the full boards, tracking, and labs — no tiers, no upsells.</p>`
- **`signup.html:17–18`** current `<strong>Saved tickets</strong>` / `<span>Track what you liked and why.</span>`
  **→** `<strong>Honest previews</strong>` / `<span>See each sport's real board shape and context before you subscribe.</span>`
- **`login.html:12`** current
  `<p>Load your saved tickets, bet-review history, and personal parlay records anywhere you open the site.</p>`
  **→** `<p>Pick up your previews and feedback anywhere you open the site. All Access loads your full tracking and review history.</p>`
- **`login.html:16`** current `<span>Saved tickets and history follow you across devices.</span>`
  **→** `<span>Your account and feedback follow you across devices.</span>`
- **Do not build `/my-decisions`.**

---

## Operations — temporary field-tester access (no code in this release)

- Use dedicated, owner-created **temporary All-Access test accounts** for moderated casino/
  barbershop sessions.
- Provision via **private operational config** (e.g., the prod `.env` / an untracked ops list),
  **never** by committing real personal emails to this public repo. (`COMP_ALL_ACCESS_EMAILS`
  may back it, but its membership for real testers must come from private config, not source.)
- Remove access after the visit.
- Owner-gating (`show_ops_strip`) means comped non-owners still never see the Phase 2
  promote/proof strip — confirm in Script 2.
- **Never** cite a comped account working as proof the **free** journey passes.

---

## Two mobile verification scripts (375px)

**Script 1 — Free journey (ordinary QR visitor; non-comped free account).** All PASS:
1. Signup + required 21+ attestation; no card.
2. `/free` and `/free/<sport>` render; **no missed-winner/promotion authority** (Missed Opps
   card absent); the −10000 rows read as "market-implied … not our picks"; nav shows **no Missed
   Winners and no Calibration**.
3. Inspect honest previews (slate/props/market/matchup context; locked depth clearly labeled).
4. Submit feedback via the footer link → `/feedback?saved=1`; no owner surfaces.
5. Logout and return (re-login) cleanly.
*(No "save a decision" step — free accounts do not save in this release.)*

**Script 2 — Field Tester journey (temporary comped All-Access account).** All PASS:
1. Login; full dashboard. **Phase 2 promote/proof strip ABSENT** (non-owner); cross-sport cards
   "Highest-implied …"; no `/test-drive` access; Missed Winners **not** in nav (comp is not
   owner); Calibration **is** in nav (paid).
2. Full tools: props / market / matchup / parlay builder with honest context.
3. Save and reopen a decision in the full tracker.
4. Submit feedback; logout and return.

Collect the two groups' feedback **separately**.

---

## P1 (not blocking)

- **P1-1** `/test-drive` 404 static asset. **P1-2** `/test-drive` internal tester-path notes.
- **P1-3** feedback-CSV concurrent-write durability.
- **P1-4** any residual non-owner console background 403 (A3 should remove the nav-driven ones).

## Non-changes / boundaries

- No model / ranking / threshold / probability change. PropScore stays Failed + Quarantined.
  Green Light, NFL Totals Context, props screener, Daily Card, `how_we_analyze`, matchup —
  untouched. Shipped P0-1/P0-2/P0-3 unchanged.
- **No new tracking system** and no `/my-decisions` in this release.
- Calibration page content not rewritten here (nav gate only + framing review flagged).
- Security: `/test-drive` stays owner-only; no cross-user data. Repo public — **no tester
  emails or secrets committed.**
- CFB untouched.

## Rollback

Commit A and Commit B are separate, each `git revert`-able; copy/visibility only, no data
migration. Prod picks up via push → `bk-deploy` auto-pull + restart (`preload_app`).

*Commits A & B implemented + deployed + verified (03b9837 / 79bb2b0).*

---

## Rev 3 — readiness patch + corrected field-test access (2026-10-10)

Two new P0s from review, plus a pre-launch verification. Shipped as a tiny patch.

### R3-1 · Field-test access = trial invite codes, NOT comp emails
The repo hardcoded four real-looking comp addresses in `app.py` (public repo = privacy +
control problem). The project already has the right mechanism: the **trial invite system**
(`/trial/<code>`, `data/tracking/Invite_Codes.csv`, columns
`Code,Label,TrialDays,MaxRedemptions,TimesRedeemed,Active`): trial duration, redemption cap,
auto-expiry via per-user `TrialExpiresAt`, **no credit card, no deploy per tester**.
- **Field testers are issued a trial code, never added to `COMP_ALL_ACCESS_EMAILS`.**
- One dedicated code per visit/location, short `TrialDays`, finite `MaxRedemptions`; set
  `Active=0` to deactivate after the engagement. Record whether a feedback note came from the
  free journey or the trial journey.
- Code creation is an **ops action** (append a row to prod's gitignored
  `data/tracking/Invite_Codes.csv` via SSM); codes are normalized UPPERCASE; `MaxRedemptions=0`
  means unlimited. Example row: `CASINO01,Casino visit,14,50,0,1` → tester opens
  `https://bankrollkings.com/trial/CASINO01` → free signup grants a 14-day All-Access trial.

### R3-2 · Comp-email list moved out of public source (code change)
`app.py` `COMP_ALL_ACCESS_EMAILS` now loads from a **private env var**
(`_load_comp_all_access_emails()`; comma/semicolon/space separated, lowercased, empty default).
No addresses remain in source.
- **Privacy incident (minor):** the four addresses are already in Git history; removing the
  lines does not un-expose them. Treat as a logged minor incident; **add no more**.
- **Operational:** to preserve the existing comps with **zero gap**, set
  `COMP_ALL_ACCESS_EMAILS` in prod `/opt/bankrollkings/.env` (values retrievable from Git
  history, privately) and restart. Until set, those four accounts see the paywall (acceptable
  per the incident ruling). Field testers do **not** go here — they get a trial code (R3-1).

### R3-3 · Login feedback-persistence copy corrected
Submitted feedback is stored for the owner; a tester cannot reopen it, so it does not "follow"
them. `login.html:12` → "Sign in to continue exploring previews across every sport. All Access
loads your full tracking and review history." `login.html:16` → "Your account access follows
you across devices."

### R3-4 · Pre-launch verification — free-preview link integrity
The free page keeps a Calibration preview card though Calibration is out of free nav. Before
launch, confirm **every** `/free` and `/free/<sport>` preview link resolves to an accessible
preview **or** a clear upgrade screen — **no raw 403.** (Checked this round; see session notes.)

### Launch sequence (per ruling)
1. Complete the ordinary free journey. 2. Create a limited trial invite code. 3. Complete the
All-Access field-tester journey **using that code** (not a comp). 4. Verify every free-preview
link. 5. Generate QR materials (the trial code becomes the official field-marketing access
path). *Public field-test readiness: not yet — pending steps 1–4.*
