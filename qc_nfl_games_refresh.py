"""QC: NFL games-source refresh pipeline (fetch_nfl_games.py).

No network. Exercises the refresh core against controlled local frames + injected downloads in a
throwaway temp dir, proving: atomic replacement, malformed-schema rejection, duplicate-ID rejection,
missing-current-season rejection, completed-count regression guard (+ override), permission/read
failure as an OPERABILITY error (never 'no games'), unchanged-upstream (304) handling, sidecar
freshness, and recovery after a failed pull. Exits 0 on success, 1 otherwise.
"""
from __future__ import annotations

import hashlib
import os
import tempfile
from datetime import date, datetime, timezone
from pathlib import Path

import pandas as pd

import fetch_nfl_games as fg

SEASON = fg.current_nfl_season()


def _valid_rows(season=SEASON, completed=40, teams=32, max_week=18):
    """A plausible full-schedule frame: `teams` distinct teams, weeks up to max_week, `completed`
    graded games with scores + result, the rest future (no result)."""
    tm = [f"T{i:02d}" for i in range(teams)]
    rows, gi = [], 0
    # pair teams across weeks so the universe = `teams`; 16 games/week for 32 teams
    for wk in range(1, max_week + 1):
        for j in range(0, teams, 2):
            home, away = tm[j], tm[(j + 1) % teams]
            done = gi < completed
            hs, as_ = (24, 17) if done else (None, None)
            rows.append({"game_id": f"{season}_{wk:02d}_{away}_{home}", "season": season, "week": wk,
                         "gameday": f"{season}-09-{(wk % 28) + 1:02d}", "gametime": "13:00",
                         "home_team": home, "away_team": away, "home_score": hs, "away_score": as_,
                         "result": (hs - as_) if done else None, "spread_line": 2.5})
            gi += 1
    return pd.DataFrame(rows)


def _write_source(df, d, name="src.parquet"):
    p = os.path.join(d, name)
    df.to_parquet(p, index=False)
    return p


def _seed_live(df, live):
    """Install a known-good live parquet + sidecar (prev completed count) to test untouched-on-fail."""
    df.to_parquet(live, index=False)
    fg.write_sidecar({"schema_version": fg.SCHEMA_VERSION, "fetch_time_utc": "2026-01-01T00:00:00Z",
                      "completed_games": int(pd.to_numeric(df["result"], errors="coerce").notna().sum()),
                      "content_sha256": "seed"}, fg.sidecar_path(live))


def _checksum(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def qc_atomic_replacement_and_recovery():
    issues = []
    with tempfile.TemporaryDirectory() as d:
        live = Path(d) / "nflverse_games.parquet"
        _seed_live(_valid_rows(completed=10), live)
        before = _checksum(live)
        # a FAILED pull (malformed source) must leave the live file byte-identical (recovery)
        bad = _write_source(_valid_rows().drop(columns=["spread_line"]), d, "bad.parquet")
        code, msg, _ = fg.refresh(source=bad, live_path=live)
        if code != 4:
            issues.append(f"malformed source not rejected (code {code}: {msg})")
        if _checksum(live) != before:
            issues.append("live file changed after a failed pull (not atomic / not recovered)")
        # a GOOD pull then atomically replaces + advances completed count
        good = _write_source(_valid_rows(completed=40), d, "good.parquet")
        code, msg, meta = fg.refresh(source=good, live_path=live)
        if code != 0 or meta is None:
            issues.append(f"valid source not applied (code {code}: {msg})")
        elif meta["completed_games"] != 40:
            issues.append(f"completed count not recorded: {meta['completed_games']}")
        if _checksum(live) == before:
            issues.append("live file not replaced after a valid pull")
    return issues


def qc_malformed_schema():
    issues = []
    ok, errs, _ = fg.validate_frame(_valid_rows().drop(columns=["game_id"]), SEASON)
    if ok or not any("required columns" in e for e in errs):
        issues.append(f"missing-column frame not rejected: {errs}")
    # non-numeric spread present -> malformed
    df = _valid_rows()
    df["spread_line"] = df["spread_line"].astype(object)
    df.loc[0, "spread_line"] = "pk"
    ok, errs, _ = fg.validate_frame(df, SEASON)
    if ok or not any("malformed" in e for e in errs):
        issues.append(f"non-numeric spread not rejected: {errs}")
    return issues


def qc_duplicate_ids():
    df = pd.concat([_valid_rows(), _valid_rows().iloc[[0]]], ignore_index=True)
    ok, errs, _ = fg.validate_frame(df, SEASON)
    return [] if (not ok and any("duplicate game_id" in e for e in errs)) else [f"dupe id not rejected: {errs}"]


def qc_missing_current_season():
    df = _valid_rows(season=SEASON - 1)       # only a prior season present
    ok, errs, _ = fg.validate_frame(df, SEASON)
    return [] if (not ok and any("current season" in e for e in errs)) else [f"missing season not caught: {errs}"]


def qc_completed_regression_guard():
    issues = []
    ok, errs, _ = fg.validate_frame(_valid_rows(completed=20), SEASON, prev_completed=40)
    if ok or not any("regress" in e for e in errs):
        issues.append(f"completed regression not blocked: {errs}")
    ok2, _, _ = fg.validate_frame(_valid_rows(completed=20), SEASON, prev_completed=40, allow_regression=True)
    if not ok2:
        issues.append("operator override did not permit a completed regression")
    # future schedule retained: a frame truncated to only completed weeks fails
    trunc = _valid_rows(completed=40, max_week=5)
    ok3, errs3, _ = fg.validate_frame(trunc, SEASON)
    if ok3 or not any("future schedule" in e for e in errs3):
        issues.append(f"truncated (no future) schedule not caught: {errs3}")
    return issues


def qc_permission_failure():
    """An unreadable live parquet is an OPERABILITY failure (exit 3), never 'no current games'."""
    with tempfile.TemporaryDirectory() as d:
        live = Path(d) / "nflverse_games.parquet"
        _seed_live(_valid_rows(), live)

        def _boom(_p):
            raise PermissionError("denied")
        code, msg = fg.check_only_result(live_path=live, reader=_boom)
    if code != 3 or "OPERABILITY" not in msg:
        return [f"unreadable live file not an operability failure: code {code} msg {msg}"]
    # must not FALSELY present it as absent/no-data (the missing-status wording)
    if "absent" in msg.lower() or "no refresh has succeeded" in msg.lower() or "no current games" in msg.lower():
        return ["unreadable file falsely described as missing/absent data"]
    return []


def qc_unchanged_upstream():
    """A 304 leaves the parquet untouched but refreshes the sidecar fetch time (confirmed current)."""
    issues = []
    with tempfile.TemporaryDirectory() as d:
        live = Path(d) / "nflverse_games.parquet"
        _seed_live(_valid_rows(completed=40), live)
        before = _checksum(live)
        side = fg.sidecar_path(live)
        fg.write_sidecar({**fg.read_sidecar(side), "fetch_time_utc": "2026-01-01T00:00:00Z",
                          "upstream_etag": "abc"}, side)

        def _unchanged(url, etag, lastmod):
            return "unchanged", None, etag, lastmod
        now = datetime(2026, 10, 16, 12, 0, tzinfo=timezone.utc)
        code, msg, meta = fg.refresh(live_path=live, download_fn=_unchanged, now_utc=now)
        if code != 0 or "unchanged" not in msg:
            issues.append(f"304 not handled as success: code {code} msg {msg}")
        if _checksum(live) != before:
            issues.append("304 rewrote the parquet (should be untouched)")
        if fg.read_sidecar(side).get("fetch_time_utc") != "2026-10-16T12:00:00Z":
            issues.append("304 did not refresh the sidecar fetch time")
    return issues


def qc_sidecar_freshness():
    """sidecar_fetch_epoch parses the recorded fetch time; check_only flags a stale sidecar (behind)
    and a fresh one (ok), using the sidecar -- not mtime."""
    issues = []
    with tempfile.TemporaryDirectory() as d:
        live = Path(d) / "nflverse_games.parquet"
        _seed_live(_valid_rows(completed=40), live)
        side = fg.sidecar_path(live)
        now = datetime(2026, 10, 16, 12, 0, tzinfo=timezone.utc)
        now_epoch = now.timestamp()
        # fresh: fetched 1h ago
        fresh_ft = datetime(2026, 10, 16, 11, 0, tzinfo=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        fg.write_sidecar({**fg.read_sidecar(side), "fetch_time_utc": fresh_ft}, side)
        code, _ = fg.check_only_result(live_path=live, now_epoch=now_epoch)
        if code != 0:
            issues.append(f"fresh sidecar reported not-fresh: code {code}")
        # stale: fetched 100h ago
        stale_ft = datetime(2026, 10, 12, 8, 0, tzinfo=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        fg.write_sidecar({**fg.read_sidecar(side), "fetch_time_utc": stale_ft}, side)
        code2, msg2 = fg.check_only_result(live_path=live, now_epoch=now_epoch)
        if code2 != 2 or "stale" not in msg2:
            issues.append(f"stale sidecar not flagged behind: code {code2} msg {msg2}")
        if abs(fg.sidecar_fetch_epoch(side) - datetime(2026, 10, 12, 8, 0, tzinfo=timezone.utc).timestamp()) > 1:
            issues.append("sidecar_fetch_epoch did not parse the recorded time")
    return issues


CHECKS = [("atomic_replacement_and_recovery", qc_atomic_replacement_and_recovery),
          ("malformed_schema", qc_malformed_schema), ("duplicate_ids", qc_duplicate_ids),
          ("missing_current_season", qc_missing_current_season),
          ("completed_regression_guard", qc_completed_regression_guard),
          ("permission_failure", qc_permission_failure), ("unchanged_upstream", qc_unchanged_upstream),
          ("sidecar_freshness", qc_sidecar_freshness)]


def main() -> int:
    print("=" * 60)
    print("BANKROLL KINGS NFL GAMES-SOURCE REFRESH QC")
    print("=" * 60)
    failed = 0
    for name, fn in CHECKS:
        try:
            issues = fn()
        except Exception as e:  # noqa
            import traceback
            issues = [f"EXCEPTION {type(e).__name__}: {e}"]
            traceback.print_exc()
        if issues:
            failed += 1
            for i in issues:
                print(f"[FAIL] {name}: {i}")
        else:
            print(f"[PASS] {name}")
    print("-" * 60)
    print(f"FAIL: {failed}" if failed else "NFL games-source refresh verified.")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
