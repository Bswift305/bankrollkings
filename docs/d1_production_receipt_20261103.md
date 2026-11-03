# D1 production receipt — 2026-11-03 (weather unavailable, never indoor/calm)

**Verdict: PRODUCTION ACCEPTED (D1 standalone).** No rollback required. Separate from the Linux gate receipt
(`docs/d1_linux_gate_receipt_20261103.md`).

## Push

- Owner approval (2026-11-03): fast-forward `master` `a5de400` → `6bdb73f`. Pushed 23:16:40Z as
  `a5de400..6bdb73f` (fast-forward, no force) of exact `6bdb73fcf3aea9ea003ea981e579854a22af9b04`.
- Sequencing disclosure: the push followed the owner's one-click approval; the detailed pre-push checklist arrived
  mid-turn. Every item was (re)verified and held: `origin/master` was `a5de400` immediately before the push;
  `6152496` is an ancestor of `6bdb73f`; no non-QC file changed after `6152496`; `a5de400..6bdb73f` is exactly the
  ten gated files; the local D1 worktree was clean; capture OFF (below).
- Not merged: D4, the Integrity group, the NBA game-lines branch, ledger commits. No cache purge, no data
  regeneration, no paid request.

## Production (read-only SSM `d26d02a9-6396-44d9-9368-7c9814480cae`, 23:21:34Z)

| Check | Result |
|---|---|
| Prod HEAD | `6bdb73fcf3aea9ea003ea981e579854a22af9b04` |
| `origin/master` (live `ls-remote` and tracking) | `6bdb73f…` both |
| Working tree | 1 entry, `?? venv/` (untracked runtime venv; no tracked change) |
| Auto-deploy | `23:18:02Z deployed 6bdb73f \| service: active \| probe: HTTP 200`; prewarm `ok (disk artifacts warmed for 6bdb73f)` |
| gunicorn | stopped 23:17:51Z, started 23:17:54Z (23.0.0, gthread, 127.0.0.1:8000), 2 workers booted; `active/running`, `NRestarts=0`, `ExecMainStatus=0`; no error/traceback lines since 23:10Z |
| earlyoom | no SIGTERM since 23:10Z |
| Public health | `/` 200 (0.19s), `/healthz` 200 (0.04s); `/sports/nfl`, `/tools/nfl-totals-today` 401 unauthenticated (expected; authed pages) |
| Capture OFF — config | `/opt/bankrollkings/.env`: 0 `BK_RESEARCH_CANDIDATE` matches |
| Capture OFF — unit | `Environment` has no `BK_RESEARCH_CANDIDATE`; no file under `/etc/systemd/system` mentions it |
| Capture OFF — live processes | master 1613022 and workers 1613027/1613028: `<unset>` |
| Weather licence | `BK_WEATHER_SOURCE_LICENSED` not in `.env` → code default **OFF** |
| Weather data | `data/context/NFL_GameWeather.csv` mtime 2026-10-16T13:01:29Z, 14 rows (games of 2026-10-18) |

Observation (not D1, not acted on): an additional gunicorn process, pid 527479, ppid 1, started 2026-09-11, is
outside the current service tree. Logged for a separate read-only look; nothing was killed or changed.

## Signed-in browser verification (bankrollkings.com, owner session, ~23:30Z)

Every page 200, no redirect (final URL = requested), rendered by `6bdb73f`.

| Surface | Missing-weather text | mph / calm / indoor / dome inference | Roof |
|---|---|---|---|
| `/sports/nfl` (NFL command slate + NFL preseason markets) | "Weather unavailable" ×15 (all 15 games, screenshot) | none | — |
| `/sports/ncaaf` (NCAAF slate + preseason markets) | "Weather unavailable" ×63 | none | — |
| `/tools/nfl-totals-today` | "Weather unavailable" ×15 | none (only the static "15+ mph" explainer sentence) | — |
| `/tools/nfl-matchup-center` | "No forecast available" ×15 | none | separate field: "Roof (home stadium) Open-air / Retractable roof (open/closed not sourced) / Dome (fixed roof)" — the only "dome" text on the page |
| `/tools/nfl-board` | "Weather unavailable" ×10 | none | — |
| `/tools/nfl-game-board` | "Weather unavailable" ×10 | none | — |
| `/tools/cfb-board` (CFB weather) | no weather value rendered (licence OFF → `_cfb_weather` withheld) | none | — |

- **Positive case not exercisable on production:** licence OFF and no current forecast file. No data was
  manufactured. The positive (licensed, dated, matching forecast) case is covered only by the gate's 32 "17 mph"
  assertions.
- **Console / resources:** per-page Resource Timing shows **zero** responses ≥ 400 on all six NFL/NCAAF surfaces.
  The only console error in the tab ("401 UNAUTHORIZED") is the `/sports/nfl` load made *before* the owner signed
  in (network log: one 401 followed by 200s).
- **New rendering, no purge:** the pre-D1 strings (`— indoor/calm`, `dome` in totals) are absent and the D1 strings
  are present immediately after the restart; the weather cache version (`wx-unavailable-v1`) is in the cache keys.
  No manual purge.

## State after

- `master` = prod = `6bdb73f`. D4 (`fix/d4-kickoff-gate*`), the Integrity group (`integration/integrity-group-a5de400`)
  and NBA (`fix/nba-game-lines-event-aware` @ `c9bc374`) remain branch-only; none authorized for deployment.
- Release order next step: rebuild Integrity + D4 on the new master `6bdb73f`.
