# D1 scoped Linux gate receipt — 2026-11-03 (weather unavailable, never indoor/calm)

**Verdict: PASS.** Gate only. Nothing deployed, master untouched (`origin/master` = `a5de400`), no data, flags,
caches or paid APIs touched. Deployment requires separate owner approval.

## Gated commit

- **Exact SHA gated: `6bdb73fcf3aea9ea003ea981e579854a22af9b04`** on branch `fix/d1-weather-unavailable`
  (anonymous public clone; `IDENTITY_OK`).
- This is **not** `6152496`: making the four neighbouring QCs self-contained added four **QC-only** commits on top
  of it. `git diff --name-only 6152496 6bdb73f` touches only `qc_*.py` files (gate printed `NONE` for product
  files). `app.py`, `fetch_nfl_weather.py`, `run_all_scorecards.py` and the three templates are byte-identical to
  `6152496`.
- Base: `a5de4003e6d6462e448bd1bcef8a965288ff2c05` is an ancestor (`BASE_ANCESTOR_OK`); `6152496` is an ancestor
  (`D1_ANCESTOR_OK`). `origin/master` (`a5de400`) fast-forwards to `6bdb73f`.

Commits `a5de400..6bdb73f`:

| SHA | Kind | Subject |
|---|---|---|
| `14dac90` | product | missing NFL weather is unknown, never 0/calm; (date, home) joins; licence gate on read |
| `6e0b69b` | product | templates render "Weather unavailable", never indoor/calm/dome, when weather is missing |
| `b8cf4c0` | product | fetch_nfl_weather: Eastern 'today' and Updated stamp via services.timeutils |
| `6152496` | QC | qc_nfl_weather_venue_integrity — D1 contract, registered in the scorecard run |
| `5e5700f` | QC | qc_nfl_board self-contained (synthetic floor workbook, in-memory owner, current markers, D1 slate weather) |
| `8872055` | QC | qc_cfb_board self-contained (synthetic current-season inputs, in-memory owner, D1 slate weather) |
| `b83bad5` | QC | qc_nfl_visual_trust portable auth via `services.qc_auth.isolated_owner_client` |
| `6bdb73f` | QC | D1 QC: one line per assertion + count; full surface + contract coverage |

Scoped file list `a5de400..6bdb73f` (10 files, +1185/−174): `app.py`, `fetch_nfl_weather.py`, `qc_cfb_board.py`,
`qc_nfl_board.py`, `qc_nfl_visual_trust.py`, `qc_nfl_weather_venue_integrity.py`, `run_all_scorecards.py`,
`templates/nfl_dashboard.html`, `templates/nfl_matchup_center.html`, `templates/nfl_totals_today.html`.

## Environment

- AWS CloudShell us-east-1, kernel `6.1.188-233.393.amzn2023.x86_64`, Python 3.13.16, fresh venv,
  `pip install -r requirements.txt` rc=0 (with network, before the QC phase). Started 2026-11-03T23:10Z, finished
  23:13:14Z. Gate script sha256 `260d4d2c…1835552` (identical to the local copy); work dir `/tmp/d1gate`.
- **First attempt invalid, not a result:** the same script with its work dir in the 1 GB CloudShell home volume
  hit `No space left on device` during `pip install` (rc=120) and ran no QC. That directory was deleted and the run
  repeated unchanged except the work dir (`/tmp`, 8.7 GB free).

## No-network proof

Compile and every QC ran inside `sudo unshare --net` (a fresh network namespace, as the normal user):
`NO_NETWORK_CONFIRMED: gaierror [Errno -2] Name or service not known`; only interface `lo: DOWN`. This blocks
every process (not only Python sockets). No QC failed for lack of network.

## Results

| Check | Result |
|---|---|
| Tree before (`git status --porcelain --untracked-files=all`) | 0 entries |
| Tree after install | 0 entries |
| `py_compile app.py fetch_nfl_weather.py qc_nfl_weather_venue_integrity.py qc_nfl_board.py qc_cfb_board.py qc_nfl_visual_trust.py run_all_scorecards.py` | rc=0 |
| `qc_nfl_weather_venue_integrity.py` | rc=0 · **275 assertions, 275 passed, 0 failed** (log sha256 `98bcc432…36cbf1`) |
| `qc_nfl_board.py` | rc=0 · No blocking NFL QC issues detected |
| `qc_cfb_board.py` | rc=0 · No blocking CFB QC issues detected |
| `qc_football_board.py` | rc=0 · No blocking football QC issues detected |
| `qc_nfl_visual_trust.py` | rc=0 · trust markers verified |
| `qc_nfl_inclusion_parity.py` | rc=0 |
| `qc_player_check.py` | rc=0 |
| `qc_sgp_workbench.py` | rc=0 |
| `qc_green_light_workspace.py` | rc=0 |
| `qc_game_lines_freshness.py` | rc=0 |
| `qc_nfl_matchup_center.py` | rc=0 |
| `qc_smoke_markers_season_robust.py` | rc=0 |
| `qc_cfb_matchup_total.py` | rc=0 |
| `qc_legal_containment.py` | rc=0 |
| Tree after | 0 entries; HEAD still `6bdb73f` |

## Neighbouring QCs — none waived, none excluded

All four were made self-contained (QC-file changes only); none was excluded, because each renders `/sports/nfl` or
`/sports/ncaaf`, which call the D1-changed `build_football_home_slate`.

- `qc_nfl_board` — previously needed an untracked floor workbook, wrote a QC user into the local user store, and
  asserted markers removed in `6e32a16`/`90dcbe7`. Now a synthetic workbook goes through the real
  `load_nfl_floor_board`, auth is in-memory, markers match today's routes. One assertion changed: matchup routes must
  return 200 for the workbook game / 404 for an unknown one (the template no longer renders workbook plays). Adds D1
  checks on `/sports/nfl` (missing → "Weather unavailable" with licence off and on; licensed match → "17 mph").
- `qc_cfb_board` — previously needed untracked CFB roster/stats/portal/coverage files; now synthetic CSVs through the
  real builders, in-memory auth; adds "Weather unavailable" on `/sports/ncaaf`.
- `qc_football_board` — unchanged; it only runs the two above.
- `qc_nfl_visual_trust` — previously 401 on every route (hard-coded personal email lookup); only the login changed.
  Not weather-sensitive.
- Revert evidence (local): restoring the pre-D1 `nfl_dashboard.html` makes `qc_nfl_board` and `qc_cfb_board` exit 1
  on "indoor/calm".

## D1 requirements → evidence (PASS-line counts from the D1 QC log)

| Requirement | Evidence |
|---|---|
| Missing weather renders only "Weather unavailable" / "No forecast available" | 52 "unavailable" assertions across all surfaces |
| Missing wind never 0 mph / calm | 22 "0 mph", 23 "calm", 143 wind assertions (row dicts carry `None`; no WIND tier/flag/tag) |
| Missing weather never implies indoor/dome | 23 "indoor", 107 "dome" assertions |
| Roof separate from weather | 64 "roof" assertions (known roof stays its own field) |
| Known valid outdoor weather still renders | 32 "17 mph" assertions (licensed, dated, matching forecast on every NFL surface; never leaks onto CFB) |
| Date + home matching | 23 "date" assertions: past-date same home, next-game same home, other home same date, away stadium — none attach |
| Licence OFF withholds stored forecast | gate-OFF assertions on `/sports/nfl`, `/tools/nfl-totals-today`, `/tools/nfl-matchup-center`, `/tools/nfl-board`, `/tools/nfl-game-board`, `_cfb_weather`; gate-ON returns the licensed value |
| Every D1 surface covered | rendered: `/sports/nfl` (20), `/sports/ncaaf` (9), `/tools/nfl-totals-today` (20), Matchup Center (40 "matchup"), `/tools/nfl-board` (20), `/tools/nfl-game-board` (20); builders: home slate, totals, Matchup Center, both boards, preseason markets (11), CFB weather/Top board (7) |
| Mutations are caught | 6: pre-D1 dashboard `— indoor/calm` text; pre-D1 totals `dome` text; home-only join; ignored licence gate (+2 setup checks) |

## Next (requires owner approval)

D1 standalone deploy = fast-forward `master` `a5de400` → `6bdb73f` (`git push origin master`; auto-deploy pulls in
≤ 2 min, restarts). Cache: D1 adds `NFL_WEATHER_CACHE_VERSION = 'wx-unavailable-v1'` and folds
`(version, licence state, _build_file_token(weather file))` into the weather-bearing cache signatures, so pre-D1
cached rows cannot be served after the restart without a manual purge. Then signed-in browser verification of the
six surfaces on bankrollkings.com. Not yet authorized.
