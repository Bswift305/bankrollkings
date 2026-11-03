# F7 cutover runbook: one receipted `--allow-collapse` NCAAF Odds API run

**Status:** PREPARED, NOT EXECUTED. **Owner approval required to execute.**
**Code:** branch `fix/f7-cfbd-no-fabricated-prices` (based on `63060a9`). Design:
`docs/f7_ncaaf_odds_writers_proposal.md` (branch `design/f7-ncaaf-odds-single-writer`).
**Owner decision Q-C:** a single receipted `--allow-collapse` recovery run, not "accept one rejected day".

---

## 0. Why a cutover run is needed at all

After F7 the Odds API (`fetch_game_lines.py` via `fetch_ncaaf_game_lines.py`) is the **only** writer
of `data/odds/NCAAF_Odds.csv`, its mirror `data/schedules/NCAAF_Odds.csv` and the alias
`data/schedules/NCAAF_Schedule.csv`. CFBD now publishes its own unpriced artifacts
(`data/odds/NCAAF_CFBD_Lines.csv`, `data/schedules/NCAAF_CFBD_Schedule.csv`,
`data/tracking/NCAAF_CFBD_publish.json`).

But on prod the legacy files were most recently written by the **old** CFBD writer (one consensus row
per game, `Book="CFBD consensus"`, invented `-110`). The first post-deploy Odds API publish validates
against that file as its prior (`fetch_game_lines.py`: `prior = pd.read_csv(output_path)`), so it can be
rejected by the row-count-collapse check (`services/feed_validation.py`, collapse below 50% of a prior
with ≥5 rows). The cutover run replaces that CFBD-shaped prior once, under a receipt.

Until the cutover lands, the market firewall in `app.py` (`_ncaaf_market_only`, used by
`load_ncaaf_game_market_odds` and `load_ncaaf_schedule`) already hides every legacy CFBD row from
market/play surfaces, so users never see the `-110` rows either way. The cutover is about restoring
**real** Odds API lines to the market surfaces, not about hiding fake ones.

### What `--allow-collapse` does and does NOT bypass

It bypasses **only** the row-count-collapse check (`validate_feed(..., allow_collapse=True)`). It does
**not** bypass the timestamp-regression check, schema, finiteness, duplicate-conflict or sport-token
checks. If §2 predicts a timestamp regression, `--allow-collapse` will not help: **STOP** and take it to
the owner (§7). Never hand-edit or delete the governed files to force a publish.

---

## 1. Preconditions (all must hold; record each in the receipt)

1. **Owner approval** for this specific run, in writing, naming the date/time window.
2. The F7 code is deployed: `git -C /opt/bankrollkings log -1 --format=%H` equals the approved commit,
   and `systemctl restart bankrollkings` (restart, not reload) has happened since
   (`journalctl -u bk-deploy.service -n 20 --no-pager`).
3. **The scheduled RC receipt has been read.** No `git push origin master` of anything F7-related
   happens before the release-candidate receipt for this change is read and accepted. This runbook does
   not authorize a master push.
4. `qc_ncaaf_odds_single_writer.py` passes **on the box** (offline, synthetic):
   `sudo -u ubuntu bash -c 'cd /opt/bankrollkings && venv/bin/python qc_ncaaf_odds_single_writer.py'`
   → last line `Clean: True`.
5. No refresh job is running: `systemctl list-units --state=running 'bk-*'` shows no `bk-daily` run in
   progress (`recover_odds_fetch.py` also refuses to run concurrently with a busy fetch/refresh process).
6. Odds API quota headroom for the run (expected cost 3 credits: 3 markets × 1 region-equivalent for
   ≤10 bookmakers; confirm against the `fetch_game_lines` quota receipt in a recent operator log —
   `grep -h -A3 "ncaaf_game_lines" logs/daily_operator_*.log | grep -i cost | tail -3`).
   Run `report_feed_availability.py` (zero-network) first and confirm NCAAF game lines are expected.
7. The Odds API key is present in `/opt/bankrollkings/.env` (do not print it).

---

## 2. Before-manifest (read-only)

Run as `ubuntu` in `/opt/bankrollkings`. Writes only the manifest into a dated receipt directory
**outside the checkout** (an untracked directory inside `/opt/bankrollkings` could trip the
HOLD-on-dirty auto-deploy guard).

```bash
R=/var/lib/bankrollkings/f7_cutover_$(date -u +%Y%m%dT%H%M%SZ)
sudo install -d -o ubuntu -g ubuntu -m 0750 "$R"
cd /opt/bankrollkings
for f in data/odds/NCAAF_Odds.csv data/schedules/NCAAF_Odds.csv data/schedules/NCAAF_Schedule.csv \
         data/odds/NCAAF_CFBD_Lines.csv data/schedules/NCAAF_CFBD_Schedule.csv \
         data/tracking/NCAAF_CFBD_publish.json \
         data/tracking/NCAAF_LineMovementCurrent.csv data/tracking/NCAAF_LineMovementHistory.csv; do
  if [ -e "$f" ]; then
    printf '%s  %s\n' "$(sha256sum "$f" | cut -d' ' -f1)" "$(stat -c '%n|%s|%i|%y' "$f")"
  else
    printf 'ABSENT  %s\n' "$f"
  fi
done | tee "$R/before.manifest"
# byte copies for rollback (the governed files are gitignored; this is the only copy)
mkdir -p "$R/before"
for f in data/odds/NCAAF_Odds.csv data/schedules/NCAAF_Odds.csv data/schedules/NCAAF_Schedule.csv; do
  [ -e "$f" ] && install -D -m 0644 "$f" "$R/before/$f"
done
( cd "$R/before" && find . -type f -exec sha256sum {} + ) | tee "$R/before.copies.sha256"
```

Contract snapshot + validator prediction (pure read, no network, no write):

```bash
venv/bin/python - <<'PY' | tee "$R/before.contract.txt"
import pandas as pd, collections
p = pd.read_csv("data/odds/NCAAF_Odds.csv")
print("rows", len(p))
print("books", collections.Counter(p.get("Book", pd.Series(dtype=str)).astype(str)).most_common(6))
print("SpreadOdds top", collections.Counter(p.get("SpreadOdds", pd.Series(dtype=str)).astype(str)).most_common(3))
ts = pd.to_datetime(p.get("LastUpdated"), errors="coerce", utc=True, format="mixed")
print("prior max LastUpdated (as the validator parses it, UTC):", ts.max())
print("collapse threshold: a new publish needs >=", int(0.5 * len(p)) if len(p) >= 5 else 0, "rows")
PY
```

Record: is the prior CFBD-shaped (`Book` = `CFBD consensus`)? What is its max `LastUpdated`? A new Odds
API publish's max `LastUpdated` is the newest **bookmaker** update, written as an Eastern wall-clock
string that the validator parses **as UTC** (a known skew, proposal finding 5). If the prior max is later
than "now in Eastern wall-clock, read as UTC", the run will be rejected for timestamp regression →
**STOP, do not run** (§7).

---

## 3. The exact command (only after §1 and §2)

```bash
cd /opt/bankrollkings
sudo -u ubuntu bash -c 'set -a; . /opt/bankrollkings/.env; set +a; cd /opt/bankrollkings && \
  venv/bin/python recover_odds_fetch.py --artifact data/odds/NCAAF_Odds.csv -- \
    venv/bin/python fetch_ncaaf_game_lines.py --days 130 --allow-collapse --expected-cost 3' \
  2>&1 | tee "$R/run.log"
echo "exit=${PIPESTATUS[0]}" | tee -a "$R/run.log"
```

- `--days 130` matches the prod daily step (`refresh_football_line_movement.py`).
- `--expected-cost 3` makes the fetch fail rather than overspend; adjust only to the figure confirmed in
  §1.6, and record the change.
- `recover_odds_fetch.py` records content-free before/after fingerprints and the fetcher's own quota
  receipt, and verifies atomic publish / last-known-good-on-failure.
- Exactly **one** run. If it fails, do not retry in a loop: go to §6/§7.

---

## 4. Validation (read-only)

```bash
venv/bin/python - <<'PY' | tee "$R/after.contract.txt"
import pandas as pd, collections
for f in ("data/odds/NCAAF_Odds.csv", "data/schedules/NCAAF_Odds.csv"):
    p = pd.read_csv(f)
    books = set(p["Book"].astype(str))
    print(f, "rows", len(p), "books", sorted(books))
    print("  CFBD rows:", int(p["Book"].astype(str).str.contains("CFBD", case=False).sum()))
    allp = pd.concat([p[c] for c in ("SpreadOdds", "OverOdds", "UnderOdds") if c in p.columns])
    print("  all prices exactly -110:", bool(len(allp.dropna())) and bool((allp.dropna() == -110).all()))
    print("  GameIDs numeric-only (CFBD-shaped):", int(pd.to_numeric(p["GameID"], errors="coerce").notna().sum()))
s = pd.read_csv("data/schedules/NCAAF_Schedule.csv")
print("alias columns", list(s.columns))
PY
journalctl -u bankrollkings --since -10min --no-pager | tail -5
```

Optional owner spot check (browser, signed in): `/sports/ncaaf/game-lines` shows real book names;
`/tools/cfb-best-spots` shows `CFBD consensus — no book price` only beside lines for games the Odds API
does not cover.

---

## 5. After-manifest

Re-run the §2 manifest loop into `"$R/after.manifest"`, then:

```bash
diff "$R/before.manifest" "$R/after.manifest" | tee "$R/manifest.diff"
```

---

## 6. Acceptance criteria (all must hold)

1. Run exit code 0; `recover_odds_fetch.py` reports an atomic publish and a cost ≤ the expected cost.
2. The three legacy files changed (sha256 differs) and **only** they plus
   `NCAAF_LineMovement*` changed. The CFBD artifacts are byte-identical (sha256/inode/size/mtime) in the
   diff — the Odds API run must not touch them.
3. `after.contract.txt`: `Book` ⊆ {DraftKings, FanDuel, BetMGM, Caesars}; **0** CFBD rows;
   "all prices exactly -110" is **False**; 0 numeric-only (CFBD-shaped) GameIDs; the alias has the
   Odds-API alias columns (`Date,Time,Away,Home,AwayFull,HomeFull,Book,GameID,LastUpdated`).
4. The service is healthy afterwards (no restart needed: data files are re-read by mtime).
5. The next scheduled daily run's "Football line movement" step PASSes **without** `--allow-collapse`
   (its prior is now an Odds API file), and the "CFB data refresh" step writes only `NCAAF_CFBD_*`.
   Then continue the ≥3-day acceptance evidence in the proposal (§6.10).

Hand the receipt directory path (`$R`) to the owner. Do not delete it.

---

## 7. Rollback / stop conditions

**Data rollback (restore from manifest).** Only if the run published something that fails §6.3, or the
owner asks:

```bash
cd /opt/bankrollkings
for f in data/odds/NCAAF_Odds.csv data/schedules/NCAAF_Odds.csv data/schedules/NCAAF_Schedule.csv; do
  [ -e "$R/before/$f" ] && install -m 0644 "$R/before/$f" "$f.f7restore.tmp" && mv -f "$f.f7restore.tmp" "$f"
done
for f in data/odds/NCAAF_Odds.csv data/schedules/NCAAF_Odds.csv data/schedules/NCAAF_Schedule.csv; do
  sha256sum "$f"; done | tee "$R/rollback.sha256"
```

Each restored sha256 must equal the corresponding line in `before.manifest`. (`mv` within one
filesystem is atomic, so readers never see a partial file.) The restored files are the old
CFBD-shaped content; the F7 market firewall keeps their `-110` rows off market surfaces.

**Code rollback.** `git revert` the F7 commit(s) on a branch, go through the normal RC receipt, then push
(the bk-deploy timer restarts the service). After a code rollback the old CFBD writer would again
overwrite the legacy files on the next CFB refresh; the `NCAAF_CFBD_*` files become harmless orphans.

**Stop and escalate (do not improvise) when:** §2 predicts a timestamp regression; the run exits
non-zero; cost exceeds the expected cost; any CFBD artifact changed during the run; or anything in §6
fails. Record what happened in `$R/notes.txt`.

### What must NOT happen

- No `git push origin master` of F7 before the scheduled RC receipt is read and accepted.
- No execution of this runbook without explicit owner approval for this run.
- No second or looping `--allow-collapse` run; it is a one-time cutover tool, never a scheduled flag.
  `--allow-collapse` must never be added to `refresh_football_line_movement.py` or any timer.
- No manual edit, truncation or deletion of the governed files to "make validation pass".
- No CFBD request induced to test the 429 path on prod (the QC covers it offline).
- No printing of `.env` contents or API keys into the receipt.

---

## 8. Reader binding after F7 (code at this branch)

| Reader | Surface type | Binds to | Notes |
|---|---|---|---|
| `load_ncaaf_game_market_odds` | loader (market) | Odds API files only | `_ncaaf_market_only` drops any CFBD row (legacy residue) |
| `load_ncaaf_schedule` | loader (market) | Odds API alias + mirror | same firewall on both frames |
| `load_ncaaf_cfbd_schedule` / `load_ncaaf_cfbd_lines` | loader (context) | CFBD artifacts | price/Book columns stripped on read even if present |
| `load_ncaaf_context_slate` | **the one composer** (context) | CFBD universe + Odds API lines, else labeled CFBD consensus | per-row `Source`; CFBD rows: `Book` = `CFBD consensus — no book price`, every price None; consensus = CFBD `consensus` provider or lower median of posted values (never an average); CFBD retrieval > 48h old is not used; falls back to Odds-API-only when no CFBD schedule |
| `build_cfb_best_spots_context` (Best Spots) | context | composer | card shows the label |
| `build_cfb_big_favorites_context` (in Best Spots) | context | composer | line cell shows the label |
| `build_cfb_totals_context` (totals pace, `/tools/cfb-totals`) | context | composer | Posted cell shows the label |
| `build_cfb_matchup_context` (matchup card; streaks + weather joins) | context | composer | week list shows the label; CFBD school names make the streak/weather joins match |
| `fetch_cfb_weather.py` | context producer | CFBD schedule, fallback Odds API file | names in `cfb_weather.json` now follow CFBD |
| `build_cfb_totals_board_context` (totals on Live Board & Lines) | **market** | Odds API only | team-profile join now resolves Odds API names to CFBD school keys |
| `build_football_live_games` callers on `/sports/ncaaf`, method pages, home slate, preseason markets, cross-league schedule, sport-hub tables, `_game_date_map` | market | Odds API only (unchanged calls) | no CFBD row can reach them |
| `build_football_live_prop_board` (NCAAF props board), props screener, `archive_daily_candidates.archive_football` | market/play | Odds API only (unchanged) | props `Game` joins on Odds API names — now consistent all day |
| `_cfb_form_legs` (Daily Card / Menu CFB line legs) | play | Odds API only (unchanged) | **open:** still emits `'price': -110` (see below) |
| `_football_total_move_map` | market | `NCAAF_LineMovementCurrent.csv` (Odds API only) | unchanged |
| `buy-low/sell-high slate`, period profiles | context, name-agnostic | Odds API only (not migrated) | resolve names via `cfb_current_form._resolve`; work on Odds-API-only data |
| `diag_refresh_incident.py` | ops | Odds API row + new CFBD row | split into two rows |

### Not migrated (still read the Odds API files; verified to work on Odds-API-only data)

- `qc_odds_feed.py` — "NCAAF game lines" is now Odds-API-only by construction (CFBD no longer writes
  that file, so a CFBD write can no longer mark it FRESH). A separate "NCAAF CFBD" family reading the
  CFBD manifest is **not yet added**.
- `report_feed_availability.py` (paid props gate) — reads the Odds API alias, which is now Odds-API-only
  (the correct binding per the proposal). The CFBD universe count alongside is **not yet added**.
- `services/injury_feed_qc.py` — reads the alias (Odds API universe only now); explicit CFBD-first list
  **not yet added**.
- `refresh_live_scores.py` — reads Odds API files (`HH:MM` Time now always parses).
- `research/cfb_gameline/cfb_gameline_capture.py` — research only; already assumes the Odds API shape.
- Odds API writer provenance columns (`Source`, `SourceUpdatedAtUTC`, …) and moving the validator's
  regression check to a true-UTC column (proposal §6.3 / finding 5) — **not done** in this branch.
- Adjacent finding Q-A (`_format_game_market_odds` drops `LastUpdated`, so the 6h fail-closed gates are
  inert) — untouched, still its own item.

### Known open, outside the CFBD-row contract (needs an owner call)

`_cfb_form_legs` and `_nfl_line_legs` in `app.py` still attach `'price': -110` to every CFB/NFL
spread leg, which feeds `market_pct` and the card's combined odds. After F7 those legs are built only
from real Odds API lines, but the **price** is still invented. The real side price cannot be recovered
from the Odds API CSV as written (`SpreadOdds` holds whichever outcome the provider listed first), so
the honest options are (a) drop CFB/NFL line legs from priced cards, or (b) extend the Odds API writer
to store both sides' spread prices. `qc_ncaaf_odds_single_writer.py` prints these sites as
"KNOWN OPEN" without counting them.
