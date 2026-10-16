# NFL Games-Source Refresh — Install & Operate (SSM runbook)

Feeds the Active ATS Wave (`build_nfl_ats_wave`, `docs/ats_wave_contract.md`). Until this service is
installed and the production reporter returns `synchronized: True`, the NFL ATS wave **correctly fails
closed** — do not work around it. Reversible: stop/disable the timer and the board returns to the
fail-closed state. Does **not** touch SU or O/U.

## What it does
`fetch_nfl_games.py` downloads the documented nflverse release, validates it, and publishes it as one
atomic **generation**; the wrapper then runs the ATS verifier in the same entrypoint and propagates
failure (a good download is not a synchronized board).

- **Source (CC BY 4.0, nflverse-data release — the asset `nflreadpy.load_schedules` consumes):**
  `https://github.com/nflverse/nflverse-data/releases/download/schedules/games.parquet`
  (license: `github.com/nflverse/nflverse-data/blob/main/LICENSE.md`). We do **not** use the mutable
  `nfldata/master` raw path.
- **Generation store (gitignored, on the box):** `data/historical/nflverse_games/`
  - `gen_<utc>_<sha8>/games.parquet` + `gen_.../meta.json` — a generation is the parquet **and** its
    immutable sidecar (content fetch time UTC, content SHA-256 of the stored parquet, upstream URL +
    ETag/Last-Modified, license + attribution, current-season row/completed/team counts, schema version).
  - `current.json` — the atomic pointer: active generation, verified SHA-256, and `checked_at_utc`
    (last time upstream was confirmed current). **Publishing swaps this pointer — one atomic moment.**
- **Freshness** is read from `checked_at_utc` (a 304 refreshes it after re-validating the live file),
  **never filesystem mtime**. `content_fetched_at_utc` (in the sidecar) is kept separate.
- The consumer verifies the selected parquet's SHA-256 against the sidecar/pointer; **missing, corrupt
  or mismatched metadata fails closed.** A legacy flat copy `nflverse_games.parquet` is mirrored for
  non-ATS readers but is **not** part of the integrity contract.

## Validation (all must pass, else the live file is left untouched)
required schema · unique/nonblank `game_id` · explicit current season present · 32–36 team universe ·
full future schedule retained (max week ≥ 18) · completed rows have scores · spread numeric or
explicitly missing · completed-game count cannot regress without `--allow-completed-regression`.

## Modes
- `--run` — fetch, then always run the ATS verifier, propagating failure (what the systemd wrapper calls).
- `--gate` — self-gate to the NFL season window (Aug–Feb); off-season no-ops (exit 0). The timer uses this.
- `--check-only` — no download: exit **0** present+fresh, **2** missing/stale, **3** unreadable/corrupt/
  checksum-mismatch (operability failure, named — never reported as “no current games”).
- `--bootstrap` — seed the generation store from the existing flat `nflverse_games.parquet` without a
  download (validates it first; sets content/checked time to the file's mtime so a stale bootstrap stays
  honestly stale). Run once on first install if a flat file already exists on the box.
- `--allow-completed-regression` — operator override for a legitimate upstream drop. Not used by the timer.

## Install (SSM, us-east-1 → Session Manager → Start session; `ssm-user` has passwordless sudo)
```bash
cd /opt/bankrollkings
sudo install -m 755 ops/bk-nfl-games-refresh.sh /usr/local/bin/bk-nfl-games-refresh.sh
sudo cp ops/bk-nfl-games.service /etc/systemd/system/bk-nfl-games.service
sudo cp ops/bk-nfl-games.timer   /etc/systemd/system/bk-nfl-games.timer
sudo systemctl daemon-reload
sudo systemctl enable --now bk-nfl-games.timer

# First run now + verify (runs as the app service user):
sudo systemctl start bk-nfl-games.service
journalctl -u bk-nfl-games.service -n 40 --no-pager
sudo -u ubuntu /opt/bankrollkings/venv/bin/python /opt/bankrollkings/report_nfl_ats_wave_sync.py
```
A one-shot refresh as the owner, without the units:
```bash
sudo -u ubuntu /opt/bankrollkings/venv/bin/python /opt/bankrollkings/fetch_nfl_games.py
```
If a flat `nflverse_games.parquet` already exists on the box and you want a legitimate generation
immediately (no wait for a download), bootstrap once first:
```bash
sudo -u ubuntu /opt/bankrollkings/venv/bin/python /opt/bankrollkings/fetch_nfl_games.py --bootstrap
```

## Cadence
Every ~6h (UTC), self-gated off-season, `flock`-guarded against overlap. Captures Thu/Sun/Mon finals
within ~6h; a 304 from upstream is cheap and just refreshes the sidecar fetch time.

## Operate / troubleshoot
- `sudo -u ubuntu /opt/bankrollkings/venv/bin/python fetch_nfl_games.py --check-only` → is the source present & fresh?
- Board still unavailable after a successful fetch? Run `report_nfl_ats_wave_sync.py` — the reason is
  shown (e.g. `overdue ungraded game(s)` means upstream hasn’t graded a past-kickoff game yet; it will
  sync on a later tick). This is the designed fail-closed behavior, not a bug.
- Exit 3 from any mode = **operability** (permission/IO). Run as `ubuntu`, not `ssm-user` directly.

## Done / green when
`report_nfl_ats_wave_sync.py` prints `synchronized: True` with a sensible graded-through week and member
list. Only then is the NFL ATS wave operational.
