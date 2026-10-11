# NBA P0 Remediation Specification — 2026-10-11

**Status: SPECIFICATION ONLY. No code changed. Do not implement until reviewed.**
Companion to `docs/nba_season_readiness_review_2026-10-11.md`. This freezes the exact behavioral
consequences and their neutral replacements before any edit — so we don't repeat the PropScore
mistake of changing ranking behavior before defining what replaces it.

**Governance stance (corrected):** the NBA composites below are **Legacy — no governed
authority**. They predate governance; that alone is enough to strip their authority. They are
**not** labeled "Under Review" (that requires opening a formal evaluation) and are **not** claimed
to be negative-EV (not demonstrated for NBA). The factual de-vigged market number may remain as a
clearly-labeled **Fact**, never as "our confidence."

**Untouched (leave alone):** the free/anonymous NBA surface (`/free/nba`), the season string, the
trial infrastructure, and the site-wide containment (ticker, nav gating).

---

## A. Completed surface inventory (read-only, prod, All-Access trial, NBA preseason)

| Surface | State | Finding |
|---|---|---|
| Command Center `/sports/nba` | renders | "Curated Lens / Top Plays — strongest live rows"; injury "**% BOOST**" cards; "Run `REFRESH_DATA`" operator leak; "20 Teams", "Props refreshed Unknown", "Results through 2026-10-10". |
| Props Screener `/sports/nba/props` | renders, 0 rows | Default sort **Confidence**; **Tier** "build-grade/edge"; **LOCKS** filter; "20-Team Field"; "Verify the Odds API key" operator leak; "Unknown" timestamps; "manual or generated board". |
| Free Preview `/free/nba` | honest ✅ | Inherits patched `free_tier.html` (de-vigged caption, no Missed-Opps card). No action. |
| Daily Card `/tools/daily-card` | honest ✅ | "assembled by rule … not a graded pick"; follows the live slate (NFL today). Will build NBA cards from the NBA board once props load — so it inherits whatever the board ranking becomes (ties to C below). |
| Review Center `/candidate-review` | renders | Sport filter = MLB/NCAAF/NFL/WNBA — **NBA absent**. No NBA graded/tracking rows yet; NBA must appear here once results grade (acceptance test, §F). |
| Matchup Lens `/tools/matchup-lens?sport=nba` | renders | NBA lens is described as **"playoff context, series state"** — a postseason orientation that mismatches a regular-season opener (see §E). |
| Game pages | n/a (preseason) | Game-dependent; verify opening week with a real slate. |
| Mobile save/reopen | generic ✅ | Tracker save/reopen verified generically earlier; an NBA-specific saved decision needs live props — verify opening week (§F). |

---

## B. Composite map — what each actually does (ranking / filtering / membership / presentation)

Built in `services/nba_props_engine.py` + `app.py`.

| Composite | Ranking | Filtering | Membership | Presentation | Code |
|---|---|---|---|---|---|
| **Confidence** (calibrated market-confidence, 0–99) | **Default board sort** (desc) | `min_confidence` param drops rows | feeds `is_lock` (≥80) and letter `grade` | "Normalized play strength" 50–99 number + grade badge | `sort_prop_rows(sort_by='confidence')` app.py:19988/19968; `nba_props_engine.py:186,202,205,233` |
| **Tier** (`snapshot_tier`) | secondary quality signal | — | parlay/floor build-quality bucket | "build-grade … blends minutes, role stability, **edge**, trend" | `nba_props_engine.py:270` |
| **Locks** (`is_lock`) | — | **LOCKS board filter** selects these | row is a "lock" when flag set + conf ≥ 80 | lock badge + `lock_reason` | `nba_props_engine.py:235,316`; `build_lock_reason` |
| **Top Plays** | selects "strongest" rows | — | command-center feature set | "the strongest live rows" | command-center board build |
| **Injury % BOOST** | orders role-change cards | — | "Expected Role Changes" list | "{injured} can create a **{boost_pct}% shift**" | `build_role_change_candidates` app.py:19705/19744; rendered app.py:20450 |

---

## C. Frozen neutral replacements (one behavior each — reviewed before implementing)

**C-1 Confidence.**
- **Default sort →** deterministic, authority-free order: **scheduled tip-off time ascending, then
  player name A–Z** (the defined replacement, so removing confidence-sort never leaves order
  undefined). Confidence remains an *optional* user-selected sort only if it is first relabeled
  per the next point.
- **The number →** keep only the de-vigged **market-implied %**, labeled factually as the market's
  number (a Fact). Remove the "normalized play strength / 50–99 score" labeling and the letter
  **grade**. No "confidence" authority wording.
- **`min_confidence` filter →** remove, or relabel as a neutral market-implied-probability
  threshold (not "confidence").

**C-2 Tier.** Remove Tier as a quality/ranking signal and drop the "build-grade / edge / build
quality" language. If any label remains it is purely descriptive (e.g., sample depth / role), with
no "edge," "grade," or "quality" claim, and it does not order or gate the board.

**C-3 Locks.** Remove the **LOCKS** board filter, the lock badge, and `lock_reason` from all
customer surfaces (a literal "lock" is on the do-not-build list). `is_lock` may persist internally
but must not surface. Board filter becomes **All Props / Floor Plays** only (Floor Plays already
covers the high-reliability case honestly).

**C-4 Top Plays.** Replace "Top Plays — the strongest live rows" with a neutral heading
("Tonight's board" / "Live rows"), ordered by the C-1 default. No "top / strongest / signal
strength" language; it is a neutral list, not a best-bets set.

**C-5 Injury % BOOST.** Remove the fabricated `boost_pct` percentage from the customer
presentation. Replace with a **qualitative, factual** note: who is out and the expected role
(e.g., "Gui Santos — projected larger role with Jimmy Butler III out"). Any magnitude shown must
be a defensible, labeled observation (the player's own recent minutes/usage), never a relative %
that balloons off a bench baseline. The `build_role_change_candidates` computation may stay; only
the "% shift" presentation changes.

*(Daily Card and any parlay/floor assembly that consume the board inherit C-1…C-5 automatically;
no separate Daily Card change is specified.)*

---

## D. Governance labels to apply (presentation)

Each surfaced NBA analytical read carries its status so nothing reads as governed by default:
- Confidence/market number, Tier, Top Plays, injury role-changes → **Legacy** (shown as context /
  "the market's number," not a Bankroll Kings edge).
- The de-vigged market-implied probability → **Fact** (labeled as the market's number).
- Nothing is marked Qualified or Baseline; nothing is auto-marked Under Review.

---

## E. Postseason default + 20-team

- **Postseason default:** `postseason_only_enabled()` defaults **true** (app.py:20014). For NBA
  launch, the **regular-season** view must be the default; opening night is not the playoffs.
  Concretely, the **NBA Matchup Lens** is described as "playoff context, series state" — reframe
  the NBA matchup/series framing for regular-season games. (Freeze the exact default-resolution
  mechanism in implementation review; options: flip the NBA default to regular-season, or make the
  focus season-aware.)
- **20-team field:** tested — navigating `postseason=0` did **not** change "20-Team Field," so it
  is **not** driven by the postseason default. Treat it as a **data-completeness** symptom (20 of
  30 teams carrying preseason data), to **reconfirm once a full slate loads** (§F) — not a
  standalone copy edit. Do not "fix" the label until the full-slate count is known.

---

## F. Production refresh acceptance test (definition — run Days 6–7 and Day 10; launch stays blocked until it passes)

Each item has an explicit pass criterion; opening night is GO only when all pass on real data.

1. **Schedule loads** — regular-season NBA games appear with correct Eastern dates; no stale/
   missing days.
2. **Game lines load** — spreads + totals for the slate, ≥1 book.
3. **Props load when markets exist** — non-zero prop rows, `books > 0`, source is a real market
   feed (not "manual or generated board").
4. **Injuries load** — player statuses + role-change inputs populate.
5. **Timestamps + sources display** — real "props/lines refreshed <time>" and book list; no
   "Unknown."
6. **Late / missing feed → safe empty state** — shows the customer message (§ operator-leak
   replacements), never "Run REFRESH_DATA" or "Verify the Odds API key."
7. **Tracking + grading persist** — a saved NBA decision survives reopen; after results it grades;
   **NBA appears in the Review Center sport filter**.

(Per the standing rule, first confirm NBA props/lines/injuries are wired into `run_daily.py` + prod
timers so the chain runs at all.)

---

## G. Operator-leak empty-state replacements (frozen copy)

- Command Center "Run `REFRESH_DATA` to reload player props…" → **"NBA markets open closer to
  tip-off — the board fills when tonight's lines post."**
- Props Screener "Live props feed is unavailable. Verify the Odds API key or subscription…" →
  **"Live NBA lines aren't posted yet — check back near game time."**
- All engine/key/refresh health language stays on owner-gated surfaces only.

---

## H. Explicit non-changes / boundaries
- No new NBA model or research mechanism. No changes to the free NBA surface, season string, trial
  infra, or site-wide containment.
- `is_lock` / `confidence` / `boost_pct` computations may remain internally; only their customer
  presentation, ranking, filtering, and membership roles change per §C.
- No implementation until this spec is reviewed and the default-resolution mechanism (§E) is chosen.

*End of specification. Awaiting review before the Days 3–5 implementation gate opens.*
