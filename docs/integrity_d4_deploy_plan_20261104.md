# Integrity + D4 — final cache audit and deployment plan (for owner approval)

> **Status 2026-11-04 13:28Z: final candidate `4afcab9` — LINUX GATE PASS (45/45, receipt
> `docs/integrity_d4_linux_gate_receipt_20261104.md`). Awaiting the owner's deploy go-ahead.** Owner direction: "If
> green, the already-approved deployment plan may proceed with no cache purge." The candidate is **`4afcab9`**, not
> `e1e33dc` or `86b6aae`. It adds the Matchup Center cache isolation (closes R1), atomic whole-ticket submission (closes
> R2), quote-change atomicity, exact `/parlay/save` and the frozen 2–8 leg contract. Cache audit delta since `e1e33dc`:
> the only new cache is `nfl_matchup_center::src2` (new key; the old pkl is never read and is not deleted); no static
> file changed (`git diff --name-only 6bdb73f 4afcab9 -- static` = 0); floor key `q1k2` still at `app.py:31532`; the
> image route is still `max_age=0` (now `:35129`). Verdict unchanged: **no purge required.**
>
> Superseded hold note (for the record):
> **Owner decision 2026-11-04: deployment of `e1e33dc` is HELD.** The rest of this plan is approved (restart
> invalidation, `q1k2` floor cache, server-side kickoff checks, scoped rollback, signed-in acceptance matrix, no cache
> purge). Two residuals must be closed first in a successor commit, then the complete offline gate and all Linux QCs
> re-run on the exact final SHA:
> 1. **Atomic user-submitted tickets** — any started / missing-or-unparseable-kickoff / stale / unpriced /
>    unrecorded-source / malformed leg rejects the *entire* submitted ticket, image or handoff (409 sanitized when it
>    became non-executable after build; 422 for malformed input), with safe per-leg reason codes and display identity;
>    no payout, no partial image, nothing persisted. Server-generated cards may still be rebuilt with a visible notice;
>    a user-submitted ticket is only altered by explicit user action. Adversarial QC for both image routes and every
>    handoff route.
> 2. **Version-isolate the Matchup Center disk cache** so new code never reads `data/cache/nfl_matchup_center.pkl`
>    (no deletion, no broad purge); QC proves a planted pre-fix entry with a false DraftKings attribution is ignored
>    and the rebuilt entry uses honest source wording.

Candidate: exact **`4afcab9178f189341140223eecb7f5f96ce67f6e`** — LINUX GATE PASS / FINAL DEPLOYMENT CANDIDATE (supersedes `e1e33dc`, `86b6aae`)
(`docs/integrity_d4_linux_gate_receipt_20261104.md`). **Not deployed.** Production and `origin/master` = `6bdb73f`.

## 1. Cache audit (read-only; static code analysis at `e1e33dc` vs `6bdb73f` + production inventory)

**Verdict: no pre-fix executable ticket object can survive deploy + restart. No purge is required.**

Why, in one paragraph: every ticket surface decides executability **per request after any cache**, on one server
clock (`_now_utc()` `app.py:33329`), through `_leg_quote_failures` (`:33389`) → `_leg_kickoff_failure` (`:33374`) →
`_kickoff_gate_failure` (`:33362`) (rejects STARTED / MISSING_KICKOFF, no quote, non-book source incl.
consensus/estimate, |odds| < 100, price/line not from the quote, missing event/market/selection, STALE_QUOTE);
`_card_price` (`:33591`) refuses a payout unless every leg passes; team-line/MLB legs are rebuilt each request through
`_unpriced_line_fields` (`:33268`) → `price=None, executable=False, kickoff_utc=None`, so a cached input can never
re-introduce `-110` or a substituted DraftKings book. The ticket builders themselves are **uncached**
(`build_daily_cards`, `build_menu_board`, `build_nfl_featured_parlay`, `build_green_light(_workspace)`,
`build_sgp_workbench_context`, `_nfl_sgp_leg_menu`, `build_nfl_hub_context`).

| Surface(s) | Cache | Mem / disk | Key at `e1e33dc` (vs `6bdb73f`) | Restart clears | mtime/hash inputs | Can retain old price / invented book / missing kickoff / started leg? |
|---|---|---|---|---|---|---|
| Daily Card, King's Tickets, GL ticket, Menu, image GET+POST, Featured, Hub, floor page | `_NFL_FLOOR_BOARD_CACHE` (`:31434`) | memory | `sig=(props_mtime, _nfl_player_log_signature())`, `pkey=(limit,min_hit,min_games)` (unchanged) | **yes** | `NFL_Props.csv` mtime; player-log manifest | **No** — process memory |
| same | floor-board disk pkl | `data/cache/nfl_floor_board_q1k2_<l>_<h>_<g>.pkl` | `nfl_floor_board::q1k2::…` (`:31532`) — **was** `nfl_floor_board::…` (`6bdb73f:31290`) | n/a (disk) | sig above + `APP_CACHE_VERSION` | **No** — key changed, new code never opens the old files; `q1k2` was never deployed, so no `q1k2` file exists on prod (prod inventory: only `nfl_floor_board_24_78_8.pkl`, `nfl_floor_board_90_52_8.pkl`). Even if read, old rows lack `quote`/`kickoff_utc` → `price=None, executable=False`, gate fails them |
| old orphan floor pkls | — | `data/cache/nfl_floor_board_[0-9]*_[0-9]*_[0-9]*.pkl` | unreachable | — | — | **No** (dead files; removal optional, not required) |
| all builders | `DATAFRAME_CACHE` (`:187`) | memory | `(path, transform.__name__)`, mtime-checked | **yes** | each CSV mtime | **No** |
| NFL line legs | `_NFL_GAME_BOARD_CACHE` (`:48544`) | memory | mtimes of scores/odds/weather + weather signature | **yes** | those files | **No**; legs forced unpriced outside cache |
| MLB legs | `_MLB_HIT_CACHE` (`:33513`) | memory | `MLB_GameLogs.csv` mtime | **yes** | — | **No**; hit rates only |
| SGP | `_NFL_ROSTER_MAP`, props via `DATAFRAME_CACHE` | memory | roster/props mtime | **yes** | — | **No**; menu rebuilt per request, every leg gated (`:48268`), `_sgp_ticket_gate` (`:48014`) re-checks selections, unresolved ids fail closed |
| Featured page / GL classic lenses | `_NFL_USAGE_CACHE`, `_WISDOM_LENS_CACHE` | memory | season/len; file+mtime | **yes** | — | **No** prices; not tickets |
| GL workspace lenses | `nfl_hot_hand*`, `nfl_wave_context`, `nfl_milestone_streaks*`, `nfl_matchup_center` pkls | disk | unchanged | no | source signatures | **No executable content** (labels/reasons only, `:45839-45865`) — see residual R1 |
| all templates | Jinja `FileSystemBytecodeCache` (`data/cache/jinja/`) | disk | bucket key + **template-source checksum** | in-process cache yes | template source | **No** — changed templates fail the checksum and recompile |
| runtime snapshots `data/cache/<key>.json` | — | disk | — | — | — | **Not in any ticket path** |
| post-deploy prewarm (`bk-auto-deploy.sh` → `refresh_runtime_snapshots.py --prewarm-only`) | — | disk | runs **after** restart under new code | — | — | **No** — writes `q1k2` artifacts with new code |

Browser / edge:
- `static/service-worker.js` (`bankroll-kings-shell-v11`) only intercepts GETs under `/static/css/`, `/static/logos/`,
  `/static/icons/` and brand assets — **no navigations, no `/tools/*`, no `.png` routes**.
- Image route: `send_file(..., max_age=0)` (`:34752`) → `Cache-Control: no-cache, max-age=0`, no ETag/Last-Modified;
  POST never cached. nginx has no `proxy_cache` (only `/static/` 7d).
- `/tools/*` HTML has no `Cache-Control`; a back/forward-cache restore of a pre-deploy tab can redisplay old HTML until
  reload, but any action from it (image POST, SGP export/handoff) is re-gated server-side. (Optional hardening: `no-store`
  on ticket routes — not required for authority.)
- No `static/` file changed in this release → **no `BK_CACHE` / `?v=` / `APP_CACHE_VERSION` bump required**.

Saved user state (must not be purged; re-gated where relevant):
- `data/user_prefs/<uid>.json` — knobs only (sizes, risk, legs, timeframe; validated `:34048-34060`); no legs/prices.
- King's Tickets draft store (`services/kings_tickets_drafts.py`) — dark, not imported by `app.py`; no stored drafts.
- Decision Journal — user-recorded bets behind `DECISION_JOURNAL_ENABLED`; history, never read back into a ticket.
- Browser storage: ticket editor / Menu / SGP use no localStorage; editors anchor to server `server_now_utc`. The only
  ticket-like key is `bk_ticket_legs` (`bk_base.html`, player/sport/stat/direction/line only — no price/book) feeding
  `/parlay` (outside this release). SGP state is URL `sel` ids, re-resolved and re-gated every request.

Residuals (non-executable; no purge proposed):
- **R1** `data/cache/nfl_matchup_center.pkl` key is unchanged; until `NFL_Odds`/`NFL_Injuries` mtime changes, the ET
  date rolls or 24h TTL, it may still carry a `market.book` produced by the old `or 'DraftKings'` fallback — shown only
  on `/tools/nfl-matchup-center`, no price/ticket fields, Green Light adapters do not expose `book`. Low risk (prod
  `NFL_Odds.csv` has a filled `Book` column). If the owner wants it gone, the **only** narrowly scoped removal is that
  one file: `/opt/bankrollkings/data/cache/nfl_matchup_center.pkl` (optional; not part of this plan unless approved).
- **R2** image POST silently drops non-started legs that are no longer executable (e.g. stale quote) and renders if ≥ 3
  legs remain; only started legs return a visible 409. Behavioural note for the acceptance matrix, not a cache issue.

Coordinator spot-checks: floor disk key `q1k2` at `e1e33dc:app.py:31532` vs `6bdb73f:app.py:31290` (no `q1k2`);
image `max_age=0` at `:34752`; `git diff --name-only 6bdb73f e1e33dc -- static` = 0 files; production inventory
(SSM `M`, 2026-11-04 ~02:10Z) shows only the two pre-fix floor pkls and no running `bk-*` unit.

## 2. Deployment plan (execute only on explicit owner approval)

Preconditions (re-check immediately before the push; abort if any fails):
1. `git ls-remote origin refs/heads/master` = `6bdb73fcf3aea9ea003ea981e579854a22af9b04`.
2. Production HEAD = `6bdb73f`, tracked tree clean (only `?? venv/`), via read-only SSM.
3. No producer job running: `systemctl list-units 'bk-*.service' --state=activating,active` empty, and the push is
   timed away from timers — not within 13:00–13:35Z (`bk-daily`), not at :00 of 00/04/08/12/16/20Z (`bk-linemove`),
   not 18:30/00:30Z (`bk-nfl-games`), not Tue/Wed 11/14/17/20/23Z (`bk-nfl-postweek`), not 01:00Z (`bk-injuries`).
4. `git diff --name-only 6bdb73f 4afcab9 | wc -l` = 62; `git merge-base --is-ancestor 6bdb73f 4afcab9`.
5. Capture OFF: no `BK_RESEARCH_CANDIDATE*` in `.env`, unit `Environment`, or the `bankrollkings` MainPID + children
   (use `systemctl show bankrollkings -p MainPID` + `pgrep -P`, not `pgrep -f gunicorn`).
6. Local D1/integ worktree clean.

Push (no force): `git push origin 4afcab9178f189341140223eecb7f5f96ce67f6e:refs/heads/master` (fast-forward).
No paid calls, no regeneration, no cache purge, no flag change.

Post-deploy (read-only SSM + public checks):
1. `bk-deploy` journal shows `deployed 4afcab9 | service: active | probe: HTTP 200`; prewarm OK.
2. Production HEAD = `origin/master` = exact `4afcab9`; tracked tree clean.
3. `bankrollkings` active/running, `NRestarts=0`, workers booted, no Traceback/ERROR since the push; no earlyoom SIGTERM.
4. `/` and `/healthz` 200.
5. Capture OFF in `.env`, unit and live MainPID + workers.
6. `ls data/cache/nfl_floor_board_q1k2_*` and `data/cache/nfl_matchup_center_src2.pkl` appear only after
   prewarm/first request (proves the new key paths); the old `nfl_matchup_center.pkl` is left in place, unread.

Rollback (only if verification fails): no manual production patch; preserve evidence; `git revert` of the release as
a normal commit on `master` (for the merge commits, `git revert -m 1` in reverse order, or a single revert of the range
via a new commit restoring `6bdb73f`'s tree), pushed without force; auto-deploy restarts. Never `reset` or force-push.

## 3. Signed-in acceptance matrix (current production data, after deploy)

| # | Check | Where |
|---|---|---|
| A1 | No already-started or unknown-kickoff leg in any proposed ticket | Daily Card, King's Tickets, Green Light ticket, Menu, Featured Parlay, NFL hub, SGP |
| A2 | Stale-held ticket / SGP legs rejected on server submission (image POST 409 for started legs; SGP export/handoff `rejected`) | `/tools/daily-card.png` POST, SGP |
| A3 | Context-only legs say why they are non-executable (`Kickoff unavailable — context only`) | all ticket surfaces + SGP game lines |
| A4 | No invented `-110` anywhere | all ticket surfaces, CFB best spots/matchup/totals |
| A5 | No substituted DraftKings attribution | same + matchup center (note R1) |
| A6 | No payout / implied probability from incomplete or stale provenance | Daily Card, King's Tickets, image |
| A7 | Fresh executable legs show their actual book and update time | same |
| A8 | Honest empty state when no executable card exists | Daily Card, King's Tickets, Featured |
| A9 | CFBD consensus remains unpriced context | CFB best spots / matchup / totals |
| A10 | D1 weather behaviour intact ("Weather unavailable" / "No forecast available", no 0 mph/calm/indoor/dome) | the 7 D1 pages |
| A11 | No console errors, failed resources (Resource Timing ≥ 400) or unexpected redirects | every page above |
| A12 | Quote change rejects the whole ticket: a moved price (worse **or** better), line or book, or a stale/missing quote → sanitized 409 with `PRICE_CHANGED` / `LINE_CHANGED` / `BOOK_CHANGED` / `QUOTE_STALE` / `QUOTE_UNAVAILABLE` and the current safe terms; no image, payout or partial save; "Confirm current terms" then resubmit succeeds | editor (Daily Card / King's Tickets), Green Light ticket, Menu slip, SGP |
| A13 | `/parlay/save`: 1–20 picks stored exactly as submitted; 0 or 21+ → 422, an invalid pick → 422 with indexed reasons, nothing saved, nothing trimmed or dropped | NBA Parlay Builder |
| A14 | Executable range 2–8: 1 leg → clear minimum message; 9+ → rejected, never truncated | image POST, SGP export/handoff |
