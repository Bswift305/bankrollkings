"""
Hot Hand Audit #1 -- read-only Source -> Render evidence report for build_nfl_hot_hand
(/tools/nfl-heatmap). NO change to membership, ordering, templates, or data sources. Cache writes are
neutralized and every touched artifact is fingerprinted before/after (exit 4 on mutation).

Chain audited: Source -> Canonical events -> Identity resolution -> Eligibility -> Calculation ->
Membership -> Ordering -> Render.

SEMANTICS (stated explicitly, because these are NOT interchangeable):
  * The Hot Hand streak is CURRENT CONSECUTIVE PLAYER APPEARANCES above THIS WEEK's prop line -- for each
    prop on the current NFL_Props.csv board, the player's game-log rows (appearances) are walked newest-
    first and counted while actual value > the current median line; the run breaks at the first miss.
  * It is a MARKET-LINE streak (current line applied to past appearances), NOT a fixed milestone.
  * It is NOT consecutive team games, NOT consecutive weeks, NOT a recent-window hit rate: the walk is
    over appearances (log rows), so a bye / missed game is a NON-row the run BRIDGES silently.

Shaped for later Evidence-Ledger migration; no receipts/constitutional infra implemented here.

Run on the box (prod/owner), venv python, no paid call / no provider refresh:
    /opt/bankrollkings/venv/bin/python3 /opt/bankrollkings/diag_nfl_hot_hand_audit.py
"""
from __future__ import annotations

import glob
import hashlib
import json
import os
from datetime import datetime, timezone

import pandas as pd

import app

app.append_qc_run_log = lambda *a, **k: None
# Read-only: neutralize the disk-cache WRITE and force a fresh recompute (no cached early-return), so we
# observe the true computed board without persisting anything.
app._nfl_disk_cache_store = lambda *a, **k: None
app._nfl_disk_cache_load = lambda *a, **k: None
try:
    app._NFL_HOTHAND_CACHE.clear()
except Exception:
    pass


def _artifacts():
    files = set()
    for base in (app.DATA_DIR / "props", app.DATA_DIR / "injuries", app.DATA_DIR / "cache",
                 app.DATA_DIR / "tracking", app.DATA_DIR / "gamelogs"):
        for pat in ("*NFL_Props*", "*NFL_Injuries*", "*nfl_hot_hand*", "*nflverse_stats*", "*NFL_GameLogs*"):
            files.update(glob.glob(str(base / pat)))
    return sorted(files)


def _fp(paths):
    fp = {}
    for p in paths:
        try:
            st = os.stat(p)
            with open(p, "rb") as fh:
                fp[p] = (hashlib.sha256(fh.read()).hexdigest()[:16], st.st_mtime_ns, st.st_size)
        except OSError:
            fp[p] = None
    return fp


def _hash_rows(rows, keys):
    basis = json.dumps([[r.get(k) for k in keys] for r in rows], default=str, sort_keys=True)
    return hashlib.sha256(basis.encode()).hexdigest()[:16]


def main() -> int:
    print("=" * 92)
    print("HOT HAND AUDIT #1 -- read-only Source->Render evidence (build_nfl_hot_hand)")
    print("=" * 92)
    arts = _artifacts()
    fp0 = _fp(arts)

    # [Source] -----------------------------------------------------------------------------------
    print("[SOURCE] nflverse player-week logs")
    try:
        srcs = app._nfl_player_log_sources()
        for s in srcs:
            p = s.get("path")
            mt = ""
            try:
                mt = datetime.fromtimestamp(os.path.getmtime(p), tz=timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M %Z")
            except OSError:
                mt = "(absent)"
            print(f"  season={s.get('season')}  path={os.path.relpath(p, app.BASE_DIR) if p else '?'}  mtime={mt}")
    except Exception as exc:
        print(f"  [WARN] _nfl_player_log_sources: {exc}")
    try:
        print(f"  log signature: {app._nfl_player_log_signature()}")
    except Exception as exc:
        print(f"  [WARN] signature: {exc}")

    log = app._nfl_player_week_data()
    if log is None or log.empty:
        print("[SOURCE] player-week log EMPTY -> board fails closed (available=False).")
        return 2
    log_seasons = pd.to_numeric(log["season"], errors="coerce").dropna().astype(int)
    cur_log = int(log_seasons.max())
    exp_week, exp_season = app._nfl_expected_completed_week()
    print(f"  log seasons: {sorted(set(log_seasons))[-4:]}  rows={len(log)}")
    print(f"  cur = max(log season) = {cur_log}   resolver current season = {exp_season}   resolver completed week = {exp_week}")

    # [Identity] ---------------------------------------------------------------------------------
    print("-" * 92); print("[IDENTITY] COMPOSITE_NAME_LOWERCASE (log '_full' lowercased; no PlayerId/EventId)")
    idx = app._nfl_player_index()
    # _full collisions: one lowercased full-name key mapping to >1 raw display name in the log
    collisions = 0
    if "_full" in log.columns:
        namecol = "player_display_name" if "player_display_name" in log.columns else "_full"
        for k, sub in log.groupby(log["_full"].astype(str).str.strip().str.lower()):
            if sub[namecol].astype(str).str.strip().nunique() > 1:
                collisions += 1
    print(f"  index keys={len(idx)}  _full lowercase collisions (one key -> many raw names): {collisions}")

    # [Eligibility/universe] ---------------------------------------------------------------------
    props_path = app.DATA_DIR / "props" / "NFL_Props.csv"
    props = app._load_cached_csv(props_path, default=pd.DataFrame()) if props_path.exists() else pd.DataFrame()
    print("-" * 92); print(f"[ELIGIBILITY] current props board: {props_path}")
    if props.empty or "Player" not in props.columns:
        print("  props empty -> board fails closed (available=False).")
    else:
        groups = props.groupby(["Player", "Stat"]).ngroups
        mapped = unmapped_stat = id_dropped = 0
        dropped_samples = []
        for (player, statlbl), g in props.groupby(["Player", "Stat"]):
            stat_key = app._NFL_PROP_STAT_MAP.get(str(statlbl))
            if not (stat_key and app._NFL_FLOOR_STATS.get(stat_key)):
                unmapped_stat += 1
                continue
            mapped += 1
            if idx.get(str(player).strip().lower()) is None:
                id_dropped += 1
                if len(dropped_samples) < 8:
                    dropped_samples.append(str(player))
        print(f"  distinct (player,stat) groups={groups}  mapped-to-floor-stat={mapped}  "
              f"unmapped-stat(skipped)={unmapped_stat}")
        print(f"  mapped players NOT resolved in log index (identity drop): {id_dropped}")
        if dropped_samples:
            print(f"    e.g. {dropped_samples}")

    # [Calculation/Membership/Ordering/Render] via the real builder (writes neutralized) -----------
    print("-" * 92); print("[CALCULATION -> MEMBERSHIP -> ORDERING -> RENDER]")
    FULL = app.build_nfl_hot_hand(limit=10 ** 7, min_streak=2)   # cache store no-op'd above
    rows = FULL.get("streaks") or []
    print(f"  through_week={FULL.get('through_week')}  expected_week={FULL.get('expected_week')}  "
          f"pending_latest={FULL.get('pending_latest')}")
    print(f"  through_label={FULL.get('through_label')!r}")
    print(f"  data_updated={FULL.get('data_updated')!r}  season={FULL.get('season')}  available={FULL.get('available')}")
    print(f"  min_streak=2 (threshold)  membership size (full, pre-limit)={len(rows)}  active={FULL.get('active_count')}")
    # prior-season leak: every member's last_season must be the resolver season
    leaked = [r for r in rows if exp_season and r.get("last_season") not in (exp_season,)]
    # (membership uses cur=max(log season); if that != resolver season, ALL members are prior-season leak)
    print(f"  members whose last_season != resolver season ({exp_season}): {len(leaked)}")
    # ordering + render-limit suppression
    RENDER_LIMIT = 50
    mem_hash = _hash_rows(rows, ["player", "stat_key", "streak"])
    render_hash = _hash_rows(rows[:RENDER_LIMIT], ["player", "stat_key", "streak", "active"])
    print(f"  membership_hash(full, player/stat/streak)={mem_hash}")
    print(f"  render_hash(top {RENDER_LIMIT}, +active)={render_hash}")
    print(f"  display-limit suppression: {max(0, len(rows) - RENDER_LIMIT)} qualifying streaks beyond the "
          f"heat-map's {RENDER_LIMIT}-row limit are not rendered")
    order_ok = all((rows[i].get("active"), -rows[i].get("streak", 0), -rows[i].get("avg_clear", 0)) <=
                   (rows[i + 1].get("active"), -rows[i + 1].get("streak", 0), -rows[i + 1].get("avg_clear", 0))
                   for i in range(len(rows) - 1)) if len(rows) > 1 else True
    # (active True sorts first via 0/1 key in the builder; this is a sanity read, not an assertion)

    # [Continuity semantics] gap-bridged runs (weeks_label min-max can mask a skipped week) ----------
    bridged = []
    for r in rows:
        wk = sorted(int(w) for w in (r.get("streak_weeks") or []))
        if len(wk) >= 2 and (wk[-1] - wk[0] + 1) != len(wk):
            bridged.append((r.get("player"), r.get("stat_key"), r.get("weeks_label"), wk))
    print("-" * 92); print("[CONTINUITY] appearances vs weeks")
    print(f"  streak = consecutive APPEARANCES above the current line (bye/missed game = non-row, BRIDGED)")
    print(f"  runs whose current-season streak weeks are NON-CONTIGUOUS (weeks_label min-max masks a gap): {len(bridged)}")
    for pl, sk, lbl, wk in bridged[:6]:
        print(f"    {pl}/{sk}: label={lbl!r} actual weeks={wk}")

    # [Fixtures] qualifying + a non-qualifying explanation ------------------------------------------
    print("-" * 92); print("[FIXTURES]")
    for r in rows[:6]:
        print(f"  QUALIFY {r.get('player')}/{r.get('stat_key')} streak={r.get('streak')} "
              f"line={r.get('line')} weeks={r.get('streak_weeks')} active={r.get('active')} "
              f"status={r.get('status_label')!r}")
    print("  (expected-but-absent reasons available above: unmapped stat, identity drop, streak<2, "
          "most-recent loaded game not current season.)")

    # ---- findings + read-only proof --------------------------------------------------------------
    fp1 = _fp(arts)
    changed = sorted(p for p in arts if fp0.get(p) != fp1.get(p))
    print("=" * 92); print("[FINDINGS -- for review, no change made]")
    print(f"  F1 PRIOR-SEASON GATE: membership season = max(log season)={cur_log}, NOT the resolver "
          f"current season ({exp_season}). " + ("MATCH (no leak now)." if cur_log == exp_season else
          "MISMATCH -> prior-season runs would render as current (weaker than build_nfl_prop_streaks, "
          "which fails closed to the resolver season)."))
    print(f"  F2 CONTINUITY LABEL: weeks_label uses min-max; {len(bridged)} runs bridge a skipped week, so "
          "the label can imply consecutive weeks for what are consecutive APPEARANCES.")
    print(f"  F3 IDENTITY: name-based (COMPOSITE_NAME_LOWERCASE); identity drops reported above; no id.")
    print(f"  F4 AVAILABILITY: does NOT gate membership (unavailable/historical streaks remain members, "
          "sunk in ordering + labeled); only is_active/sort/label change.")
    print("-" * 92)
    print(f"READ-ONLY PROOF: {len(arts)} artifact(s); {'ALL UNCHANGED' if not changed else 'CHANGED: ' + ', '.join(changed)}")
    return 4 if changed else 0


if __name__ == "__main__":
    raise SystemExit(main())
