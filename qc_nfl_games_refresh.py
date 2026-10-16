"""QC: NFL games-source refresh pipeline (fetch_nfl_games.py), generation-store edition.

No network. Exercises the refresh core against controlled frames + injected downloads in throwaway
temp generation stores, proving: schema/dup/season/completed-regression validation; a failed
publication leaves the PRIOR complete generation active; a 304 with a tampered live file fails closed;
a missing / checksum-mismatched sidecar fails closed; a 304 advances checked_at while leaving
content_fetched_at fixed; the shell-wrapper orchestrator propagates fetch and verifier failures; an
operability (permission/read) failure is named, never 'no games'; and the sports date is Eastern
regardless of host timezone. Exits 0 on success, 1 otherwise.
"""
from __future__ import annotations

import os
import tempfile
from datetime import date, datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

import fetch_nfl_games as fg

SEASON = fg.current_nfl_season()


def _valid_rows(season=SEASON, completed=40, teams=32, max_week=18):
    tm = [f"T{i:02d}" for i in range(teams)]
    rows, gi = [], 0
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


def _src(df, d, name="src.parquet"):
    p = os.path.join(d, name)
    df.to_parquet(p, index=False)
    return p


# --------------------------------------------------------------------------- pure validation
def qc_validation():
    issues = []
    ok, errs, _ = fg.validate_frame(_valid_rows().drop(columns=["game_id"]), SEASON)
    if ok or not any("required columns" in e for e in errs):
        issues.append(f"missing-column not rejected: {errs}")
    df = _valid_rows(); df["spread_line"] = df["spread_line"].astype(object); df.loc[0, "spread_line"] = "pk"
    ok, errs, _ = fg.validate_frame(df, SEASON)
    if ok or not any("malformed" in e for e in errs):
        issues.append(f"non-numeric spread not rejected: {errs}")
    dup = pd.concat([_valid_rows(), _valid_rows().iloc[[0]]], ignore_index=True)
    ok, errs, _ = fg.validate_frame(dup, SEASON)
    if ok or not any("duplicate game_id" in e for e in errs):
        issues.append(f"dup id not rejected: {errs}")
    ok, errs, _ = fg.validate_frame(_valid_rows(season=SEASON - 1), SEASON)
    if ok or not any("current season" in e for e in errs):
        issues.append(f"missing season not caught: {errs}")
    ok, errs, _ = fg.validate_frame(_valid_rows(completed=20), SEASON, prev_completed=40)
    if ok or not any("regress" in e for e in errs):
        issues.append(f"completed regression not blocked: {errs}")
    ok2, _, _ = fg.validate_frame(_valid_rows(completed=20), SEASON, prev_completed=40, allow_regression=True)
    if not ok2:
        issues.append("operator override did not permit a completed regression")
    ok, errs, _ = fg.validate_frame(_valid_rows(max_week=5), SEASON)
    if ok or not any("future schedule" in e for e in errs):
        issues.append(f"truncated schedule not caught: {errs}")
    return issues


# --------------------------------------------------------------------------- publication / recovery
def qc_publication_failure_keeps_prior():
    """A failed publication (pointer-swap error) leaves the PRIOR complete generation active + intact."""
    issues = []
    with tempfile.TemporaryDirectory() as root:
        c1, m1, _ = fg.refresh(source=_src(_valid_rows(completed=10), root), root=root)
        if c1 != 0:
            return [f"first publish failed: {m1}"]
        prior = fg.resolve_current(root)
        orig_write = fg._write_json_atomic

        def _boom(path, obj):
            raise OSError("pointer write denied")
        fg._write_json_atomic = _boom
        try:
            c2, m2, _ = fg.refresh(source=_src(_valid_rows(completed=40), root, "good2.parquet"), root=root)
        finally:
            fg._write_json_atomic = orig_write
        if c2 != 3:
            issues.append(f"publication failure not an operability error: code {c2} ({m2})")
        now = fg.resolve_current(root)
        if now["content_sha256"] != prior["content_sha256"] or now["completed_games"] != 10:
            issues.append("prior generation not preserved after a failed publication")
        # a subsequent good publish advances to the new generation
        c3, _, _ = fg.refresh(source=_src(_valid_rows(completed=40), root, "good3.parquet"), root=root)
        if c3 != 0 or fg.resolve_current(root)["completed_games"] != 40:
            issues.append("recovery publish after failure did not advance the generation")
    return issues


# --------------------------------------------------------------------------- sidecar integrity
def qc_missing_or_mismatched_sidecar_fails_closed():
    issues = []
    with tempfile.TemporaryDirectory() as root:
        fg.refresh(source=_src(_valid_rows(), root), root=root)
        ptr = fg._read_json(fg.pointer_path(root))
        gen = Path(root) / ptr["generation"]
        # (a) missing sidecar
        (gen / "meta.json").unlink()
        code, msg = fg.check_only_result(root=root)
        if code != 3 or "OPERABILITY" not in msg:
            issues.append(f"missing sidecar not failed closed as operability: {code} {msg}")
    with tempfile.TemporaryDirectory() as root:
        fg.refresh(source=_src(_valid_rows(), root), root=root)
        pq = fg.resolve_current(root)["parquet_path"]
        with open(pq, "ab") as fh:         # tamper the parquet -> sha mismatch vs sidecar/pointer
            fh.write(b"tampered")
        try:
            fg.resolve_current(root)
            issues.append("checksum mismatch not raised by resolve_current")
        except fg.GamesSourceError as exc:
            if "sha256" not in str(exc):
                issues.append(f"mismatch raised wrong error: {exc}")
        code, msg = fg.check_only_result(root=root)
        if code != 3:
            issues.append(f"checksum mismatch not exit 3: {code} {msg}")
    return issues


# --------------------------------------------------------------------------- 304 hardening
def qc_304_tampered_fails_closed():
    issues = []
    with tempfile.TemporaryDirectory() as root:
        fg.refresh(source=_src(_valid_rows(), root), root=root)
        before = fg.resolve_current(root)["checked_at_utc"]
        pq = fg.resolve_current(root)["parquet_path"]
        with open(pq, "ab") as fh:
            fh.write(b"x")

        def _unchanged(url, etag, lastmod):
            return "unchanged", None, etag, lastmod
        code, msg, _ = fg.refresh(root=root, download_fn=_unchanged,
                                  now_utc=datetime(2026, 10, 16, 12, 0, tzinfo=timezone.utc))
        if code != 4 or "not marking fresh" not in msg:
            issues.append(f"304 with tampered live file did not fail closed: {code} {msg}")
        # pointer must be untouched (still points at the now-tampered gen, checked_at unchanged) -- but
        # the board still fails closed because resolve_current rejects the checksum mismatch.
        try:
            after = fg._read_json(fg.pointer_path(root)).get("checked_at_utc")
            if after != before:
                issues.append("304-on-tamper advanced checked_at (should not)")
        except Exception as exc:
            issues.append(f"pointer unreadable after 304-tamper: {exc}")
    return issues


def qc_304_advances_checked_not_fetched():
    issues = []
    with tempfile.TemporaryDirectory() as root:
        t0 = datetime(2026, 10, 10, 8, 0, tzinfo=timezone.utc)
        fg.refresh(source=_src(_valid_rows(), root), root=root, now_utc=t0)
        cur0 = fg.resolve_current(root)

        def _unchanged(url, etag, lastmod):
            return "unchanged", None, etag, lastmod
        t1 = datetime(2026, 10, 16, 12, 0, tzinfo=timezone.utc)
        code, msg, _ = fg.refresh(root=root, download_fn=_unchanged, now_utc=t1)
        cur1 = fg.resolve_current(root)
        if code != 0:
            issues.append(f"valid 304 not success: {code} {msg}")
        if cur1["checked_at_utc"] != "2026-10-16T12:00:00Z":
            issues.append(f"304 did not advance checked_at: {cur1['checked_at_utc']}")
        if cur1["content_fetched_at_utc"] != cur0["content_fetched_at_utc"]:
            issues.append("304 changed content_fetched_at (should be fixed)")
        if cur1["content_sha256"] != cur0["content_sha256"]:
            issues.append("304 changed the parquet checksum (should be untouched)")
    return issues


# --------------------------------------------------------------------------- freshness / operability
def qc_freshness_and_operability():
    issues = []
    with tempfile.TemporaryDirectory() as root:
        t = datetime(2026, 10, 16, 11, 0, tzinfo=timezone.utc)
        fg.refresh(source=_src(_valid_rows(), root), root=root, now_utc=t)
        now_epoch = datetime(2026, 10, 16, 12, 0, tzinfo=timezone.utc).timestamp()   # 1h later -> fresh
        code, _ = fg.check_only_result(root=root, now_epoch=now_epoch)
        if code != 0:
            issues.append(f"fresh generation reported not-fresh: {code}")
        stale_epoch = datetime(2026, 10, 20, 12, 0, tzinfo=timezone.utc).timestamp()  # 4+ days later
        code2, msg2 = fg.check_only_result(root=root, now_epoch=stale_epoch)
        if code2 != 2 or "stale" not in msg2:
            issues.append(f"stale generation not flagged behind: {code2} {msg2}")
        # operability: an unreadable parquet (sha compute raises) -> exit 3, never 'no games'
        orig = fg._sha256_file
        fg._sha256_file = lambda p: (_ for _ in ()).throw(PermissionError("denied"))
        try:
            code3, msg3 = fg.check_only_result(root=root)
        finally:
            fg._sha256_file = orig
        if code3 != 3 or "OPERABILITY" not in msg3 or "no current games" in msg3.lower():
            issues.append(f"unreadable parquet not a named operability failure: {code3} {msg3}")
    return issues


# --------------------------------------------------------------------------- wrapper orchestration
def qc_wrapper_propagates_failures():
    issues = []
    cases = [((4, 0), True, "fetch validation failure"), ((5, 0), True, "download failure"),
             ((3, 0), True, "publish failure"), ((0, 3), True, "verifier failure"),
             ((0, 0), False, "all ok"), ((2, 0), False, "behind (not a failure)")]
    for (fr, vr), want_fail, desc in cases:
        rc = fg.run_refresh_and_verify(fetch_fn=lambda fr=fr: fr, verify_fn=lambda vr=vr: vr,
                                       in_season_fn=lambda: True)
        if (rc != 0) != want_fail:
            issues.append(f"{desc}: wrapper rc {rc} (want {'nonzero' if want_fail else '0'})")
    # the verifier must run EVEN after a fetch failure
    ran = {"verify": False}

    def _vf():
        ran["verify"] = True
        return 0
    fg.run_refresh_and_verify(fetch_fn=lambda: 4, verify_fn=_vf, in_season_fn=lambda: True)
    if not ran["verify"]:
        issues.append("verifier did not run after a fetch failure")
    # off-season gate short-circuits without fetching
    fetched = {"n": 0}

    def _ff():
        fetched["n"] += 1
        return 0
    rc = fg.run_refresh_and_verify(gate=True, fetch_fn=_ff, verify_fn=lambda: 0, in_season_fn=lambda: False)
    if rc != 0 or fetched["n"] != 0:
        issues.append(f"off-season gate did not short-circuit: rc {rc} fetched {fetched['n']}")
    return issues


# --------------------------------------------------------------------------- eastern date
def qc_eastern_date():
    issues = []
    if fg._today_et() != datetime.now(ZoneInfo("America/New_York")).date():
        issues.append("_today_et is not Eastern")
    if fg.current_nfl_season(date(2026, 1, 15)) != 2025:
        issues.append("Jan belongs to the prior season label")
    if fg.current_nfl_season(date(2026, 9, 15)) != 2026:
        issues.append("Sep belongs to the current season label")
    return issues


CHECKS = [("validation", qc_validation),
          ("publication_failure_keeps_prior", qc_publication_failure_keeps_prior),
          ("missing_or_mismatched_sidecar_fails_closed", qc_missing_or_mismatched_sidecar_fails_closed),
          ("304_tampered_fails_closed", qc_304_tampered_fails_closed),
          ("304_advances_checked_not_fetched", qc_304_advances_checked_not_fetched),
          ("freshness_and_operability", qc_freshness_and_operability),
          ("wrapper_propagates_failures", qc_wrapper_propagates_failures),
          ("eastern_date", qc_eastern_date)]


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
