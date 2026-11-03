"""QC: props / game-lines AGE is computed between timezone-aware UTC instants (2026-11 correction).

Defect: get_props_refresh_meta / get_lines_refresh_meta parsed LastUpdated (a NAIVE Eastern wall clock
written by the fetchers via to_eastern_datetime_str) and subtracted it from a naive pd.Timestamp.now() --
the server's ambient zone, UTC on prod -- so every customer-facing age was overstated by 4h (EDT) / 5h
(EST) and the 6h CLOCK-A window tripped after ~1-2 real hours. Now: naive = America/New_York, aware is
converted, now is UTC-aware, and DST ambiguity resolves to the earliest plausible instant (an age is never
understated). Offline, pure fixtures; `now` is injected. Exit 0 on pass, 1 on failure.
"""
from __future__ import annotations

import os

import pandas as pd

os.environ.setdefault("SECRET_KEY", "qc-only-not-a-real-secret")   # app import guard; QC-only dummy

from services.timeutils import age_hours, instant_to_utc  # noqa: E402

FAILS: list[str] = []
NOTES: list[str] = []


def check(cond, msg):
    (NOTES if cond else FAILS).append(msg)


def z(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ") if dt is not None else None


def main() -> int:
    # instants
    for value, want, label in (
        ("2026-07-15 08:00", "2026-07-15T12:00:00Z", "naive Eastern in EDT (UTC-4)"),
        ("2026-01-15 08:00", "2026-01-15T13:00:00Z", "naive Eastern in EST (UTC-5)"),
        ("2026-07-15T08:00:00-04:00", "2026-07-15T12:00:00Z", "aware offset"),
        ("2026-07-15T12:00:00Z", "2026-07-15T12:00:00Z", "aware Z"),
        ("2026-11-01 01:30", "2026-11-01T05:30:00Z", "fall-back fold (ambiguous) -> earliest instant"),
        ("2026-03-08 02:30", "2026-03-08T06:30:00Z", "spring-forward gap (nonexistent) -> earliest instant"),
    ):
        got = z(instant_to_utc(value))
        check(got == want, f"instant {value!r} ({label}) -> {got}")
    check(instant_to_utc("garbage") is None and instant_to_utc("") is None and instant_to_utc(None) is None,
          "unparseable/blank -> None (never a guessed instant)")

    # ages across DST transitions: real elapsed time, not wall-clock difference.
    a = age_hours("2026-11-01 00:30", now="2026-11-01T07:30:00Z")   # 00:30 EDT -> 02:30 EST: 3 real hours
    check(a is not None and abs(a - 3.0) < 1e-9, f"age across fall-back = {a}h (wall diff 2h, real 3h)")
    a = age_hours("2026-03-08 01:30", now="2026-03-08T07:30:00Z")   # 01:30 EST -> 03:30 EDT: 1 real hour
    check(a is not None and abs(a - 1.0) < 1e-9, f"age across spring-forward = {a}h (wall diff 2h, real 1h)")

    import app

    def meta_pair(lu, now):
        df = pd.DataFrame([{"Player": "x", "Book": "DraftKings", "LastUpdated": lu}])
        return (app.get_props_refresh_meta(df, now=now), app.get_lines_refresh_meta(df, now=now))

    for lu, now, want, label in (
        ("2026-01-15 08:00", "2026-01-15T15:00:00Z", 2.0, "EST"),
        ("2026-07-15 08:00", "2026-07-15T14:00:00Z", 2.0, "EDT"),
        ("2026-11-01 00:30", "2026-11-01T07:30:00Z", 3.0, "fall-back day"),
        ("2026-03-08 01:30", "2026-03-08T07:30:00Z", 1.0, "spring-forward day"),
    ):
        pm, lm = meta_pair(lu, now)
        legacy_naive = (pd.Timestamp(now.replace("Z", "")) - pd.Timestamp(lu)).total_seconds() / 3600.0
        check(pm["age_hours"] == want and lm["age_hours"] == want and not pm["is_stale"] and not lm["is_stale"],
              f"{label}: props/lines age {pm['age_hours']}/{lm['age_hours']}h (old naive-vs-UTC math said "
              f"{legacy_naive:.1f}h); not stale under the 6h window")
        check(pm["last_updated"].endswith(" ET") and lm["last_updated_utc"] is not None,
              f"{label}: display labelled ET ({pm['last_updated']}), UTC instant exposed ({lm['last_updated_utc']})")

    pm, lm = meta_pair("2026-01-15 08:00", "2026-01-15T19:30:00Z")    # 6.5 real hours
    check(pm["is_stale"] and lm["is_stale"], "6.5 real hours -> stale (window still enforced)")

    df = pd.DataFrame({"Player": ["a", "b", "c"], "LastUpdated": ["2026-01-15 08:00", "2026-01-15T14:00:00Z",
                                                                  "2026-01-15 23:00"]})
    pm = app.get_props_refresh_meta(df, now="2026-01-15T15:00:00Z")
    check(pm["age_hours"] == 1.0, f"mixed naive/aware column: freshest aware 14:00Z wins, future value ignored "
                                  f"(age {pm['age_hours']}h)")

    print("=" * 64)
    print("QC: ODDS/PROPS AGE TIMEZONE (UTC instants, DST-correct)")
    print("=" * 64)
    for n in NOTES:
        print(f"[OK]   {n}")
    for f in FAILS:
        print(f"[FAIL] {f}")
    print(f"\n{len(NOTES)} passed, {len(FAILS)} failed")
    return 1 if FAILS else 0


if __name__ == "__main__":
    raise SystemExit(main())
