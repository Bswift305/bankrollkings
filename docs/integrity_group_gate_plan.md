# Integrity group — exact diff and gate plan (for owner review)

_Prepared 2026-11-01. Nothing here is merged to `master` or deployed. `master` = `63060a9` (frozen until the
2026-11-02 RC receipt is read). Every production step below needs explicit owner authorization._

## 1. What the group is

Integration branch **`integration/integrity-group` @ `1482d65`** (pushed; never merged to master) =
`63060a9` + four `--no-ff` merges, in this order:

| # | Branch | Commits | Kind | Why it is in this group |
|---|---|---|---|---|
| 1 | `fix/bk-daily-f1-heatmap-qc` | `3564dc7` | QC-only | Heat-map QC drift; rides along (no cycle of its own) |
| 2 | `fix/qc-wnba-nba-self-contained` | `ac55194` | QC-only | Removes the three pre-existing red QCs from the gate with real fixtures, not a waiver |
| 3 | `fix/daily-card-no-fabricated-price` | `4e8b380`, `1496e1b`, `f642091`, `0f76289` | Product integrity | Fabricated `-110` removed; executable-leg contract; bookmaker-fallback removal; honest empty state |
| 4 | `fix/f7-cfbd-no-fabricated-prices` | `e061671`, `bdc06c4`, `999dc01`, `4d7a60f` | Product integrity | CFBD never writes Odds-API files or fabricated prices; context-only + labelled |

Not in this group (by owner direction): NBA QC corrections (F3/F3b/F3c — own governed group), Q-A + F5
(freshness group), F2v2 + F6 + NBA phase (later, after their evidence), CFBD wiring (after the account
contract). The **F7 `--allow-collapse` cutover** (`docs/f7_cutover_runbook.md`) is a separate, receipted
production action — not part of this deploy.

**Diff:** `git diff 63060a9 1482d65` — 50 files, +2,972 / −269. Production code: `app.py` (+551),
`fetch_ncaaf_slate_cfbd.py`, `fetch_cfb_weather.py`, `diag_refresh_incident.py`, `grade_signals.py`;
templates: `_ticket_editor`, `_unpriced_context_lines` (new), `daily_cards`, `kings_tickets`, `menu_board`,
`signal_report`, `wnba_dashboard`, `wnba_matchup`, `cfb_best_spots`, `cfb_matchup`, `cfb_totals`; new
services: `fabricated_price_scan.py`, `qc_no_network.py` (+ `qc_offline_site/sitecustomize.py`), additive
`qc_auth.isolated_user_client`; QCs: new `qc_unpriced_line_legs`, `qc_ncaaf_odds_single_writer`,
`qc_route_qc_harness`, `qc_offline` runner; ~20 QCs changed only by `# synthetic-fixture` line markers.

## 2. The one merge conflict (resolution is part of the review)

`app.py`, `build_football_live_games` row dict — F7 vs the Daily-Card branch. **F7's side still carries the
old `or 'DraftKings'` fallback.** Resolved to F7's CFBD logic with no substituted bookmaker:

```python
'away_ml': None if _is_cfbd else market.get('away_ml'),
'home_ml': None if _is_cfbd else market.get('home_ml'),
'book': (NCAAF_CFBD_CONTEXT_LABEL if _is_cfbd
         else (_clean_book(market.get('book')) or UNRECORDED_SOURCE)),
'book_source': _clean_book(market.get('book')) or None,
'updated_utc': _utc_iso(_feed_stamp_to_utc(market.get('updated'))),
```

`qc_unpriced_line_legs.KNOWN_PENDING` is emptied in the same merge (F7 removes the CFBD `-110` writer). A
wrong resolution fails the gate: the bookmaker-fallback scan flags `or 'DraftKings'`.

## 3. What changes for users once deployed (expected, not a regression)

- **Daily Card / King's Tickets / Menu:** a leg is priced only from a complete, ≤6h-old single-book quote.
  NFL props refresh ~daily on prod, so most of the day there will be **no priced cards** and the page reads
  **"No fresh executable prices available"**, with analysis shown separately as labelled context (source +
  "updated at", no price/payout/slip). This is the owner's cadence decision (1.5s); the cadence/quota audit
  follows the receipt.
- **MLB "to record a hit" legs:** context only (the estimated price table was fabricated).
- **Team lines (CFB/NFL):** context only, "Unavailable — no verified book quote"; CFBD shown as
  "CFBD consensus — no book price".
- **Missing bookmaker anywhere it is shown:** "Unrecorded source" (was "DraftKings").
- **Signal Report:** shows **"Legacy record — ROI withheld"** until `grade_signals` re-grades in the next
  `bk-daily` (the current prod summary priced CFB ATS at an assumed `-110`); hit rates unchanged.
- **CFB boards (F7):** CFBD rows are context-only and never priced; see `docs/f7_cutover_runbook.md`.

## 4. Gate — results so far and what remains

**Local (Windows, offline via `qc_offline.py`) on `1482d65`: PASS.** `py_compile app.py grade_signals.py`
OK; **33 / 33 offline QCs exit 0**; `qc_odds_feed` correctly refused (exit 3, `REQUIRES_NETWORK`, NOT RUN).
QCs run: unpriced_line_legs, route_qc_harness, ncaaf_odds_single_writer, decision_journal,
entity_nba_wnba_market, game_lines_freshness, kings_tickets_drafts, lens_attribution, lookup_change_store,
lookup_change_views, model_observations, nba_gated_market_facts, nba_market_only, nfl_capture_precision,
nfl_heatmap_freshness, nfl_hot_hand_boundary, nfl_props_source_fields, nfl_props_source_time,
odds_recovery_preflight, player_check, season_markets, sgp_workbench, slate_validation,
streak_integrity_hothand, ticket_editor_shared, wnba_readiness, wnba_visual_trust, nfl_inclusion_parity,
nfl_floor_cache, green_light_workspace, nba_visual_trust, entity_schedule_links, nfl_roster_single_writer.

**Remaining before any deploy — combined Linux gate (needs owner approval to run).** Proposed: AWS
CloudShell (Amazon Linux, outside production; reads nothing from the prod box):

```bash
git clone --branch integration/integrity-group https://github.com/Bswift305/bankrollkings.git bk-gate && cd bk-gate
test "$(git rev-parse HEAD)" = 1482d65701f828b70e55e91437d148338d019c82
python3 -m venv .venv && . .venv/bin/activate && pip install -q -r requirements.txt
export SECRET_KEY=qc-gate
python3 -m py_compile app.py grade_signals.py
for q in <the 33 QCs above>; do python3 qc_offline.py "$q" || echo "FAIL $q"; done
python3 qc_offline.py qc_odds_feed.py; test $? -eq 3   # must be refused, not run
```

Pass criteria: every listed QC exits 0 on Linux; `qc_odds_feed` exits 3; no `NetworkBlocked` traceback
outside the network-guard checks. Any red is diagnosed, not waived. (`qc_offline.py` blocks Python socket
networking in the QC process and its Python children only — not non-Python subprocesses.)

## 5. Deploy plan (after the RC receipt + Linux gate + owner approval)

1. **Read-only prod pre-check:** HEAD `63060a9`, clean tree, `bk-daily` inactive, no producer running;
   capture current `Signal_Grades_Summary.json` mtime and `data/cache/` listing (football/NFL/CFB keys).
2. **Fast-forward `master` to `1482d65`** (no force; merges preserved) → `bk-deploy.timer` pulls + restarts
   (`restart`, never `reload` — templates + `app.py` changed).
3. **Cache:** the NFL floor-board disk key is versioned (`q1`) so pre-quote entries are not served; in-process
   caches clear on restart. Board pkl caches for football/CFB builders should be purged once after restart
   (`data/cache/*nfl*`, `*cfb*`, `*ncaaf*` — exact list from step 1) so pre-change rows are not served for the
   12h TTL (CLAUDE.md §4). **This is a prod write — separate authorization.**
4. **Verify (read-only):** HTTP 200 on `/tools/daily-card`, `/tools/kings-tickets`, `/tools/menu`,
   `/tools/signal-report`, `/sports/wnba`, CFB boards; no `-110` and no substituted bookmaker in their HTML;
   empty-state text present when nothing is executable.
5. **Monitor one scheduled `bk-daily` cycle** (this group is one risk group): report the overall result
   separately from step results; confirm `grade_signals` writes `price_basis` (Signal Report leaves Legacy).

## 6. Rollback

`git revert -m 1` of the four merge commits (newest first) on `master`, pushed normally → auto-deploy +
restart; no force-push, no history rewrite. No data migration is involved: the group writes no new
persistent schema; F7's new CFBD artifacts are additive and inert until the separately-authorized cutover.
