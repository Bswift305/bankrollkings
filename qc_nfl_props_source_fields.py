"""QC (fixture, no network): the props fetcher persists provider identity + provable-UTC clocks additively
(2026-10-24 capture-precision fix, Commit 1).

Proves, with synthetic Odds API payloads (NO paid request):
  * EventId survives parse_market_rows -> build_dataframe unchanged;
  * commence_time becomes EventCommenceAtUTC as an equivalent canonical UTC 'Z' value;
  * bookmaker last_update becomes SourceUpdatedAtUTC as canonical UTC;
  * missing / malformed / timezone-NAIVE provider timestamps become '' (never assumed UTC);
  * the existing LastUpdated (Eastern display) column is unchanged and still present;
  * build_dataframe keeps the three additive columns; no existing column is dropped.
"""
from __future__ import annotations

import fetch_player_props as fp


def _mk_event(eid="evt-123", commence="2026-10-26T17:00:00Z"):
    ev = {"away_team": "Atlanta Falcons", "home_team": "Green Bay Packers",
          "markets": []}  # markets live on the bookmaker
    if eid is not None:
        ev["id"] = eid
    if commence is not None:
        ev["commence_time"] = commence
    return ev


def _mk_book(last_update="2026-10-25T13:30:00Z"):
    mkey = next(iter(fp.MARKET_STAT_MAP))  # any supported market key
    bk = {"key": "draftkings", "title": "DraftKings",
          "markets": [{"key": mkey, "outcomes": [
              {"description": "Jordan Love", "name": "Over", "point": 245.5, "price": -110},
              {"description": "Jordan Love", "name": "Under", "point": 245.5, "price": -110},
          ]}]}
    if last_update is not None:
        bk["last_update"] = last_update
    return bk, mkey


def run_qc() -> dict:
    failures = []
    checks = []
    mkey0 = next(iter(fp.MARKET_STAT_MAP))
    allowed = {mkey0}

    # valid
    bk, mkey = _mk_book()
    rows = fp.parse_market_rows(_mk_event(), bk, allowed)
    if not rows:
        failures.append("valid fixture produced no rows")
    else:
        r = rows[0]
        if r.get("EventId") != "evt-123":
            failures.append(f"EventId not propagated: {r.get('EventId')!r}")
        if r.get("EventCommenceAtUTC") != "2026-10-26T17:00:00Z":
            failures.append(f"EventCommenceAtUTC wrong: {r.get('EventCommenceAtUTC')!r}")
        if r.get("SourceUpdatedAtUTC") != "2026-10-25T13:30:00Z":
            failures.append(f"SourceUpdatedAtUTC wrong: {r.get('SourceUpdatedAtUTC')!r}")
        if not r.get("LastUpdated"):
            failures.append("LastUpdated (Eastern display) missing/empty")
        checks.append("valid: EventId + UTC clocks propagated; LastUpdated preserved")

    # to_utc_iso edge cases
    cases = {
        "2026-10-26T17:00:00Z": "2026-10-26T17:00:00Z",
        "2026-10-26T17:00:00+00:00": "2026-10-26T17:00:00Z",
        "2026-10-26T12:00:00-05:00": "2026-10-26T17:00:00Z",   # tz-aware -> converted
        "2026-10-26T17:00:00": "",                              # NAIVE -> ineligible
        "not-a-date": "",
        "": "",
        None: "",
    }
    for raw, want in cases.items():
        got = fp.to_utc_iso(raw)
        if got != want:
            failures.append(f"to_utc_iso({raw!r}) = {got!r}, want {want!r}")
    checks.append("to_utc_iso: Z/offset normalized, naive/malformed/empty -> '' (never assumed UTC)")

    # missing commence / id / last_update -> ''
    rows2 = fp.parse_market_rows(_mk_event(eid=None, commence=None), _mk_book(last_update=None)[0], allowed)
    if rows2:
        r = rows2[0]
        if r.get("EventId") != "":
            failures.append(f"missing id should be '': {r.get('EventId')!r}")
        if r.get("EventCommenceAtUTC") != "":
            failures.append(f"missing commence should be '': {r.get('EventCommenceAtUTC')!r}")
        if r.get("SourceUpdatedAtUTC") != "":
            failures.append(f"missing last_update should be '': {r.get('SourceUpdatedAtUTC')!r}")
        checks.append("missing provider fields -> '' (classified, not fabricated)")

    # build_dataframe keeps the additive columns + all originals
    df = fp.build_dataframe(rows)
    for col in ("EventId", "EventCommenceAtUTC", "SourceUpdatedAtUTC", "Player", "Stat", "Line", "LastUpdated"):
        if col not in df.columns:
            failures.append(f"build_dataframe dropped column {col!r}")
    if "EventId" in df.columns and not (df["EventId"] == "evt-123").all():
        failures.append("EventId altered through build_dataframe")
    checks.append("build_dataframe retains additive + original columns")

    # empty-df schema also carries the columns
    empty = fp.build_dataframe([])
    for col in ("EventId", "EventCommenceAtUTC", "SourceUpdatedAtUTC"):
        if col not in empty.columns:
            failures.append(f"empty build_dataframe missing {col!r}")

    return {"clean": not failures, "checks": checks, "failures": failures}


def main() -> int:
    r = run_qc()
    print("=" * 66)
    print("NFL PROPS SOURCE-FIELD QC (fixture; fetcher capture-precision Commit 1)")
    print("=" * 66)
    for c in r["checks"]:
        print(f"  [ok] {c}")
    for f in r["failures"]:
        print(f"  [FAIL] {f}")
    print(f"Clean: {r['clean']}")
    return 0 if r["clean"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
