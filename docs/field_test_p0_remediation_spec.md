# Field Test P0 Remediation Specification — 2026-10-10

**Status: SPEC (read-only). No code changed yet.** Implement only after approval, as ONE
rollback-safe commit. Scope is strictly the four P0s in
`docs/public_test_drive_readiness_review_2026-10-10.md` (Rev 2). Anything not named here is an
explicit non-change (§7).

**Governing promise:** market info + factual context + transparent research + decision
tracking, so a user can *evaluate wagers for themselves* — not "come see our winning model."

**Hard boundary (governance):** P0-1 may **hide/relabel** tester-facing surfaces but must
**not delete** research data or underlying computations. All builders, CSVs, and caches stay
intact; only display and copy change.

---

## 1. Affected surfaces (exact)

| ID | File | Lines | Kind of change |
|---|---|---|---|
| S1 | `templates/dashboard_overview.html` | 241 (block guard) | add owner/admin gate |
| S2 | `app.py` | 20997–20999 | relabel lane strings |
| S3 | `templates/dashboard_overview.html` | 219–221 | reframe cross-sport intro copy |
| S4 | `app.py` | new route `GET /feedback` | additive tester feedback route |
| S5 | `templates/feedback_form.html` | new file | tester-only feedback form |
| S6 | `app.py` | 36087–36108 (`save_feedback`) | branch redirect by owner vs tester |
| S7 | `templates/bk_base.html` | footer | add "Leave feedback" link for signed-in users |
| S8 | `templates/pricing.html` | 11, 124 | copy replacement |
| S9 | `app.py` | 467–468 | copy replacement (plan definition) |

Gating primitive already in the codebase: **`show_ops_strip`** — a template global set at
`app.py:29042` (`current_user and (is_owner_user(current_user) or is_admin)`) and returned by
`inject_globals` at `app.py:29156`. True only for owner/admin. Used here for S1.

---

## 2. P0-1 — hide best-bet / promotion / hindsight-proof authority

### S1 — Phase 2 "command strip" (hide from non-owner)
This block renders CLV, Missed Winners, Promotion Signals, Hot Streaks, Scorecards, Parlay EV,
and the **Promotion Queue / Missed Winner Proof / EV Build Preview** panels — the
`PROMOTE HARD` and "becomes proof" authority.

- **Exact current wording** (`dashboard_overview.html:241`):
  `{% if phase2 and not public_tour %}`
- **Exact replacement:**
  `{% if phase2 and not public_tour and show_ops_strip %}`
- Effect: the entire `<section class="bk-content bk-phase2-shell"> … </section>` (lines
  242–344) renders for **owner/admin only**. Non-owner testers never see it. No data touched —
  `build_phase2_dashboard_context()` still runs; its output is simply not rendered for testers.
- The closing `{% endif %}` at line 345 is unchanged.

### S2 — cross-sport lane labels (relabel, do not hide)
The Cross-Sport Top Props section is an **advertised free feature** ("Top 3 props by de-vigged
market-implied probability") so it stays visible; only the authority label "BEST" is removed.
It is rendered as `{{ prop.sport }} · {{ prop.lane }}` → "MLB · BEST UNDER".

- **Exact current wording** (`app.py:20997–20999`):
  ```
  ('Best Under', sport.get('best_under')),
  ('Best Over', sport.get('best_over')),
  ('Best Board Read', sport.get('best_prop')),
  ```
- **Exact replacement:**
  ```
  ('Highest-implied Under', sport.get('best_under')),
  ('Highest-implied Over', sport.get('best_over')),
  ('Highest market-implied', sport.get('best_prop')),
  ```
  Renders as "MLB · Highest-implied Under" — factually what the row is (the highest
  market-implied-probability under), with no selection/edge claim. The underlying
  `best_under`/`best_over`/`best_prop` computation is unchanged.

### S3 — cross-sport section intro (honest framing)
- **Exact current wording** (`dashboard_overview.html:219–221`):
  ```
  <div class="bk-dashboard-kicker">Cross-Sport Home</div>
  <h2>Top props across every live board</h2>
  <p>The Home page stays sport-neutral: NBA, WNBA, MLB, and season-prep sports can all surface here when their boards are active.</p>
  ```
- **Exact replacement:**
  ```
  <div class="bk-dashboard-kicker">Cross-Sport Home</div>
  <h2>Highest market-implied props across every live board</h2>
  <p>Ordered by de-vigged market-implied probability — the market's own read, not our edge. Heavy favorites naturally sit at the top. One per lane, per sport.</p>
  ```

---

## 3. P0-2 — tester-facing feedback form (no owner exposure)

### S4 — new route `GET /feedback`
- **Access rule:** signed-in users only (login required). If `get_current_user()` is falsy,
  redirect to `login` with `next=/feedback`. **No owner gate** — any signed-in tester reaches
  it. (Login-gating keeps anonymous/public spam out; the field-test flow signs the tester in
  first anyway.)
- **Renders `feedback_form.html` and nothing else.** It must **not** call
  `load_feedback_log()`, `summarize_feedback_log()`, or pass any other tester's feedback,
  statistics, or owner controls. Pass only: the page option list, a `saved` flag from
  `request.args.get('saved') == '1'`, and `csrf_token()` (via the standard template context).
- `/test-drive` stays exactly as-is (owner-only). Not modified.

### S5 — new template `templates/feedback_form.html`
- Extends `bk_base.html`. Contains a hero ("Leave Feedback" / short instruction) and the SAME
  form fields as the existing `test_drive.html` form (tester name optional, page select,
  category select, severity select, textarea `feedback` required), posting
  `method="post" action="/feedback/save"` with `{{ csrf_token() }}`.
- A `{% if saved %}` confirmation panel ("Thanks — your note was saved.").
- **Must not** include: the feedback summary stat cards, the "Recent Feedback" table, the
  "Suggested Tester Path", or any owner/reviewer language.

### S6 — `save_feedback` redirect branch (`app.py:36087–36108`)
`POST /feedback/save` already accepts input with CSRF and length caps
(name `[:80]`, feedback `[:2000]`, etc.) — keep all of that. Only the redirect target changes
so a non-owner is not bounced to the owner-only `/test-drive`.

- **Exact current wording** (empty-feedback branch, line 36096):
  `return redirect(url_for('test_drive', postseason=1 if postseason_only_enabled() else 0))`
- **Exact current wording** (success branch, line 36108):
  `return redirect(url_for('test_drive', postseason=1 if postseason_only_enabled() else 0, saved=1))`
- **Replacement (both branches):** branch on viewer role:
  ```
  _owner = is_owner_user(get_current_user())
  _dest = 'test_drive' if _owner else 'feedback'
  # empty-feedback branch:
  return redirect(url_for(_dest, postseason=1 if postseason_only_enabled() else 0))
  # success branch:
  return redirect(url_for(_dest, postseason=1 if postseason_only_enabled() else 0, saved=1))
  ```
  Owner keeps today's behavior (lands on `/test-drive`); tester lands back on `/feedback?saved=1`.

### S7 — discoverability (`templates/bk_base.html` footer)
Add, in the footer, a link visible to any signed-in user:
`{% if current_user %}<a href="{{ url_for('feedback') }}">Leave feedback</a>{% endif %}`
so the QR flow's "submit feedback" step is reachable without hunting. No floating widget, no
new JS. (Exact placement to match the footer's existing link markup.)

---

## 4. P0-3 — positioning copy (exact replacements)

### S8 — `templates/pricing.html`
- **Line 11 current:**
  `<p>No tiers, no levels, no upsells. Every sport, every board, every lab — the same full arsenal for everyone. We're not here to gouge you like the institutions do; we're here to help you bust the casino's ass.</p>`
- **Line 11 replacement:**
  `<p>No tiers, no levels, no upsells. Every sport, every board, every lab — the same full arsenal for everyone. We bring the market, the context, and transparent research into one place so you can evaluate every wager for yourself.</p>`
- **Line 124 current:** `<strong>Built to beat the book</strong>`
- **Line 124 replacement:** `<strong>Built for your decisions</strong>`

### S9 — `app.py` All-Access plan definition
- **Line 467 current:**
  `'summary': 'One membership, the whole platform. Every sport, every board, every lab — no tiers, no upsells. Built to help you beat the book, not to gouge you.',`
- **Line 467 replacement:**
  `'summary': 'One membership, the whole platform. Every sport, every board, every lab — no tiers, no upsells. The market, the context, and transparent research in one place so you can decide for yourself.',`
- **Line 468 current:** `'best_for': 'Anyone serious about beating the book',`
- **Line 468 replacement:** `'best_for': 'Anyone who wants to evaluate wagers for themselves',`

---

## 5. Security boundaries

- `/test-drive` remains owner-only (`is_owner_user` → 403). Unchanged.
- Owner statistics, the feedback log/table, and the Phase 2 promotion/proof/ops strips remain
  owner/admin-only (`show_ops_strip`). The new tester route never reads or renders the
  feedback log or any aggregate.
- `GET /feedback` requires a signed-in user; it exposes a blank form only.
- `POST /feedback/save` keeps CSRF protection and all input length caps; it writes a single
  feedback row via the existing `save_feedback_entry`. No change to what it stores.
- No change to authentication, plan/paywall gating, Stripe/checkout, owner/admin checks, or
  any data-refresh pipeline.
- Repo is public: no secrets in any changed file. Verify `git status --short` before adding.

---

## 6. Explicit non-changes

- **No model, scoring, ranking, threshold, or probability change.** PropScore stays Failed +
  Quarantined exactly as containment left it.
- **No deletion or disabling of computations or data:** `build_phase2_dashboard_context`,
  `build_cross_sport_top_props`, `best_under/best_over/best_prop`, the missed-winners /
  promotion-signal builders, and all feedback rows are **preserved**. P0-1 is display-only.
- Green Light, NFL Totals Context, props screener, Daily Card, `how_we_analyze`, matchup page —
  **untouched** (already conformant).
- No schema changes, no new data files, no new dependency.
- No auth-gating changes beyond adding the single login-gated `/feedback` route.
- `franchise_hub.html` "gouge on tickets" (in-game GM flavor) — **left as-is.**
- CFB surfaces — **untouched.**
- The `/test-drive` 404 asset (P1-1) and internal tester-path notes (P1-2) are **not** in this
  P0 commit.

---

## 7. Non-owner / mobile verification script (P0-4)

Run on a **phone-width** browser with a **brand-new free (non-owner) account**. Record
PASS/FAIL per step; any FAIL blocks the field test.

1. **Logged-out landing** — visit `bankrollkings.com` signed out at 375px. PASS = page renders;
   no "BEST / PROMOTE HARD / proof" authority anywhere; "Create Free Account" visible; footer
   disclosures present.
2. **Signup + 21+** — create a throwaway free account. PASS = the "I am 21 or older and have
   reviewed Responsible Gambling" checkbox is required; no card requested.
3. **First login landing** — PASS = lands on a useful slate/context view; the **Phase 2
   command strip is absent**; cross-sport cards read "Highest-implied …", never "BEST".
4. **Navigate to a core tool** — open a matchup or market/props page. PASS = current lines +
   factual context render; research status reads honestly (no locks / guaranteed / proven edge).
5. **Save + reopen a tracked decision** — save a bet/ticket in the tracker; log out; log back
   in; reopen. PASS = the decision persisted and is readable.
6. **Submit feedback** — follow the footer "Leave feedback" link to `/feedback`, submit a note.
   PASS = confirmation shows; the tester is **never** shown `/test-drive`, owner stats, or any
   other tester's feedback.
7. **Logout and return** — PASS = session ends cleanly; re-login works.
8. **Throughout** — no 500s; pages readable and operable at 375px; note any console errors.

---

## 8. Rollback procedure

- Ship as **one commit**. `git revert <sha>` restores everything: the S1 template guard, the S2
  lane strings, the S3/S8 copy, the S9 plan copy, the S4 route, the S5 template, the S6 redirect
  branch, and the S7 footer link. No data migration, so revert is clean and total.
- Prod picks it up via `git push origin master` → `bk-deploy` auto-pull + **restart** (template
  + `app.py` changes need a restart under `preload_app`; the auto-deploy does this).
- No service-worker or CSS version bump required (no static asset changed). The new
  `feedback_form.html` is a template, served fresh after the restart.
- Post-deploy, re-run the §7 script in a non-owner session.

*End of spec. Awaiting approval to implement P0-1/P0-2/P0-3; P0-4 runs after they deploy.*
