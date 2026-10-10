# Field Test Follow-Up P0 Specification — 2026-10-10

**Status: SPEC (read-only). No code changed.** Implement only after approval. This builds on
`docs/field_test_p0_remediation_spec.md` (P0-1/P0-2/P0-3 — shipped c592863) and the P0-4 run,
which proved the shipped fixes work **and** that the advertised **free** journey does not.
These are the follow-up P0s. Per governance ruling: comping accounts is **not** a
public-readiness fix (it masks the broken free journey, leaves inaccurate copy and preview
authority live, and does not test what a QR prospect experiences).

**Governing promise:** market info + factual context + transparent research + decision
tracking so a user can *evaluate wagers for themselves*. Track & Learn is a core layer.

---

## P0-A — Free-preview authority (tester-facing)

**Surfaces:** `templates/free_tier.html` (renders `/free` and `/free/<sport>`), fed by
`build_free_sport_preview_context` / `build_free_sport_prop_rows` (`app.py:21175+`); plus the
Free-plan copy in `app.py:449`.

Goal: remove "top / proof / missed-winner" authority and present the heavy-favorite rows as
**highest market-implied entries**, not best opportunities.

1. **"missed-winner proof" → neutral record.**
   - **Current** (`free_tier.html:489`):
     `<small>Review Center turns resolved hit/miss data into player profiles, confidence calibration, and missed-winner proof.</small>`
   - **Replacement:**
     `<small>Review Center turns resolved hit/miss data into player profiles, confidence calibration, and a record of what did and didn't hit.</small>`

2. **Ranked implied-% preview reads as a best-of list.** The numbered list
   (`free_tier.html:439–447`) shows `{{ loop.index }}` 1/2/3 with a bare `{{ row.implied }}%`
   chip — on today's slate that surfaces three −10000 / 99.0% stolen-bases unders as the
   apparent top plays.
   - Add a caption under the "Parlay Builder Example" head (`free_tier.html:432–435`), exact:
     `<small>Sample rows, ordered by de-vigged market-implied probability — the market's read, not our picks. Heavy favorites (very low payouts) naturally sit at the top.</small>`
   - Label the chip so the number is unambiguous — **current** `free_tier.html:446`
     `<span class="free-builder-chip">{{ row.implied }}%</span>` → **replacement**
     `<span class="free-builder-chip">{{ row.implied }}% implied</span>` (and the same at the
     Market card `:494` / props table `:554` already say "implied" — leave those).
   - **Do not** add any "top", "best", "lock", or ranking authority. The list stays ordered by
     market-implied probability (unchanged computation); only the framing label is added.

3. **Free-plan summary "top plays".**
   - **Current** (`app.py:449`): `'summary': 'Know what is happening tonight across every sport. Slate, environment, top plays, and injuries — no subscription required.',`
   - **Replacement:** `'summary': 'Know what is happening tonight across every sport. Slate, environment, the market's top-implied props, and injuries — no subscription required.',`
   - `app.py:453` ("Top 3 props by de-vigged market-implied probability, with displayed
     historical hit rates") is already market-framed — **leave as-is.**

---

## P0-B — Non-owner navigation exposure

**Surface:** the top-nav builder (`app.py:1529–1544`). `calibration_lab` ("Calibration") and
`missed` ("Missed Winners") are added to the `lab` group with **no owner/plan gate**, so every
signed-in user (including a free tester) sees them; their targets are owner/paid, which also
produces the non-owner console 403s.

**Decision + change:** remove **Missed Winners** and **Calibration** from the nav for users who
are not owner/admin and not `all_access`. Concretely, after the `items.extend([...])` block,
drop those two keys when `not (is_owner_user(user) or normalize_user_plan(user) == 'all_access')`.
("Missed Winners" also carries outcome/proof framing — keeping it out of the free surface is
consistent with P0-A.) Paid users and the owner keep both. No change to the pages themselves in
this spec.

---

## P0-C — Access-promise contradiction (saved-decision entitlement)

**The contradiction:** the product promises free "saved tickets" in three places —
`app.py:455` (`'Free account, saved tickets, and platform access'`), `signup.html:17`
(`Saved tickets`), `login.html:16` (`Saved tickets and history follow you across devices.`) —
but `/tools/tracker` and the parlay builder are paid, and `/free/<sport>` states saving is
"Waiting for full access" (`free_tier.html:461,464,465`).

**One product truth must be chosen. Recommended: enable a minimal free decision log** (Track &
Learn is a core promise; removing it weakens the product more than a small build costs).

**Minimal free decision log — design (the one genuine feature in this spec; build in its own
sub-commit):**
- **Entitlement:** any signed-in user (free included) may save a plain decision record and
  reopen their own list. This is **not** the parlay builder, grading, CorrelationIQ/BankrollIQ,
  or CLV — those stay paid.
- **Store:** reuse the existing per-user mechanism (`services/bet_tracker.py` / `data/user_bets`,
  already gitignored and per-account). No schema migration.
- **Save affordance:** a "Save this read" control on the free `/free/<sport>` sample rows and on
  any free-visible read, writing `{sport, player/market, line, side, note?, saved_at}` for the
  authenticated account.
- **Reopen:** a `GET /my-decisions` (login-gated, free-allowed) listing the account's saved
  records read-only, newest first. No ranking, no EV, no "best" — a plain record.
- **Guardrail:** the free log must introduce **no** predictive authority (no score, rank, grade,
  EV, or "lock"). It is a record of the user's own choices, nothing more.
- **Copy:** once enabled, `app.py:455` / `signup.html:17` / `login.html:16` are accurate and
  stay. If this option is **declined**, those three strings must instead be struck/replaced so
  production stops promising a free capability that does not exist.

---

## P0-D — Temporary field-tester access rules

For the first **moderated** casino/barbershop sessions, use explicitly designated, temporary
**All-Access tester accounts** via `COMP_ALL_ACCESS_EMAILS` (`app.py:536`). Rules:
- A small, fixed, owner-created list; each address clearly a test account.
- Pre-authorized **before** a visit; **removed** after the engagement.
- Owner-gating (`show_ops_strip`) means comped non-owners still never see the Phase 2
  promote/proof strip — verify in Script 2.
- **Never** cite a comped account working as evidence the **free** journey passes. The two are
  different products and are tested separately (below).
- Adding/removing emails edits `app.py:536` + deploy; record the engagement's test addresses in
  the ops log, not in this public repo if they are real personal emails.

---

## Two mobile verification scripts (375px; split P0-4)

**Script 1 — Free journey (ordinary QR visitor, non-comped free account).** All must PASS:
1. Signup + required 21+ attestation; no card.
2. `/free` and `/free/<sport>` render; **no "top/proof/missed-winner" authority**; the −10000
   rows read as "highest market-implied … not our picks"; nav shows **no Missed Winners /
   Calibration**.
3. **Save a decision** via the minimal free log, then reopen it in `/my-decisions`
   (persists across a logout/login).
4. Submit feedback via the footer link → `/feedback?saved=1`, no owner surfaces.
5. Logout and return (re-login) cleanly.

**Script 2 — Field Tester journey (temporary comped All-Access account).** All must PASS:
1. Login; land on the full dashboard.
2. **Phase 2 promote/proof strip is ABSENT** (comped user is non-owner); cross-sport cards read
   "Highest-implied …"; no owner-only surface or `/test-drive` access.
3. Full tools: props / market / matchup / parlay builder render with honest context.
4. Save and reopen a decision in the full tracker.
5. Submit feedback; logout and return.

Collect feedback from the two groups **separately** so a note is attributable to the preview or
the full platform.

---

## P1 (not blocking; unchanged)

- **P1-1** `/test-drive` 404 static asset.
- **P1-2** `/test-drive` internal tester-path notes.
- **P1-3** feedback-CSV concurrent-write durability.
- **P1-4** non-owner console background **403s** — gate the owner-only fetch so a non-owner's
  console is clean. (Kept P1: no visible breakage.)

---

## Non-changes / boundaries

- No model / ranking / threshold / probability change anywhere. PropScore stays
  Failed + Quarantined. Green Light, NFL Totals Context, props screener, Daily Card,
  `how_we_analyze`, matchup — untouched.
- The shipped P0-1/P0-2/P0-3 gating and copy are not altered.
- The minimal free decision log is a **record only** — no predictive authority, no grading.
- Security: the free log is per-authenticated-user, sign-in required, no cross-user read;
  `/my-decisions` is login-gated. `/test-drive` stays owner-only.
- CFB surfaces untouched. Repo is public — no secrets (incl. real tester emails) committed.

## Sequencing & rollback

Implement in sub-steps, each reversible: (A) free-preview copy/labels, (B) nav gate, (C) the
free decision log (its own sub-commit, with Script 1 step 3 as its gate), (D) is an ops action
(comp list), not a code feature. Prefer one commit for A+B, a second for C. `git revert`
restores per sub-commit; A/B/D need no data migration; C adds only per-user rows.

*End of spec. Awaiting approval — note P0-C is a product-truth decision (enable free log vs.
drop the promise) that should be ruled before implementation.*
