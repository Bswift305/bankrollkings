"""Verify every registered sport actually has the parts it declares.

This is the check that would have caught two season-costing bugs before they
shipped:

  * NFL/NCAAF had no prop-stat -> gamelog-column map, so every football pick
    graded to nothing. Archiving worked, so nothing looked wrong.
  * A sport can declare a loader that does not exist, or a stat map that does not
    cover the markets its own fetcher produces.

The market cross-check is the important one: it compares MARKET_STAT_MAP in
fetch_player_props.py (what the feed can emit) against the sport's stat column
map plus the gamelog columns (what grading can resolve). A market that can be
fetched but never graded is reported as a WARNING rather than a failure --
sometimes there genuinely is no gamelog counterpart (Anytime TD), and mapping it
to a lookalike column would be worse than leaving it ungraded.

Run: python qc_sport_registry.py
"""
from __future__ import annotations

from datetime import datetime

import app
from services.qc_tracking import append_qc_run_log
from sport_registry import SPORTS, SportSpec

# Sport -> the markets its feed can produce. Football keys come from
# MARKET_STAT_MAP; other sports use their own vocabularies.
FOOTBALL_CODES = {'NFL', 'NCAAF'}


def _resolve(name: str | None):
    # Tolerate None: a sport with no declared stat map is the exact case this QC
    # exists to report, and getattr(app, None) raises TypeError instead.
    if not name:
        return None
    return getattr(app, name, None)


def _check_loaders(spec: SportSpec, failures: list, warnings: list) -> None:
    for field_name in ('props_loader', 'gamelog_loader', 'schedule_loader',
                       'odds_loader', 'grading_gamelog_loader'):
        fn_name = getattr(spec, field_name)
        if not fn_name:
            failures.append(f"{spec.code}: {field_name} is not declared.")
            continue
        if _resolve(fn_name) is None:
            level = warnings if not spec.live else failures
            level.append(f"{spec.code}: {field_name} '{fn_name}' does not exist in app.")


def _check_stat_map(spec: SportSpec, failures: list, warnings: list) -> None:
    if spec.stat_column_map is None:
        if not spec.identity_ok:
            failures.append(
                f"{spec.code}: no stat_column_map and identity_ok=False -- grading "
                f"will look up raw prop names against gamelog columns and resolve nothing."
            )
        return
    mapping = _resolve(spec.stat_column_map)
    if not isinstance(mapping, dict) or not mapping:
        failures.append(f"{spec.code}: stat_column_map '{spec.stat_column_map}' missing or empty.")
        return

    # Every mapped target must be a real gamelog column, or grading silently
    # skips it exactly as it did for football.
    loader = _resolve(spec.grading_gamelog_loader)
    if loader is None:
        return
    try:
        logs = loader()
    except Exception as exc:
        warnings.append(f"{spec.code}: could not load gamelogs to verify stat map ({exc}).")
        return
    if logs is None or getattr(logs, 'empty', True):
        warnings.append(f"{spec.code}: gamelogs empty (offseason?), stat map targets unverified.")
        return
    columns = set(logs.columns)
    unknown = sorted({col for col in mapping.values() if col not in columns})
    if unknown:
        failures.append(
            f"{spec.code}: stat map points at columns absent from gamelogs: {', '.join(unknown)}."
        )


def _check_market_coverage(spec: SportSpec, warnings: list) -> None:
    """Markets the feed can emit but grading cannot resolve."""
    if spec.code not in FOOTBALL_CODES:
        return
    try:
        import fetch_player_props as fetcher
        market_stats = getattr(fetcher, 'MARKET_STAT_MAP', {})
    except Exception:
        return
    mapping = _resolve(spec.stat_column_map) or {}
    football_markets = {k: v for k, v in market_stats.items()
                        if any(t in k for t in ('pass', 'rush', 'reception', 'receptions', 'anytime'))}
    ungraded = sorted({label for label in football_markets.values()
                       if str(label).upper() not in mapping})
    if ungraded:
        warnings.append(
            f"{spec.code}: markets fetchable but not gradeable (no gamelog counterpart): "
            f"{', '.join(ungraded)}."
        )


def _check_calibrator_and_qc(spec: SportSpec, warnings: list) -> None:
    from pathlib import Path
    base = Path(__file__).resolve().parent
    if spec.calibrator and not (base / spec.calibrator).exists():
        warnings.append(f"{spec.code}: declared calibrator {spec.calibrator} not found.")
    if spec.live and not list(base.glob(f'qc_{spec.qc_prefix}_*.py')):
        warnings.append(f"{spec.code}: no qc_{spec.qc_prefix}_*.py scripts found.")


def run_qc() -> dict:
    checked_at = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    failures: list[str] = []
    warnings: list[str] = []

    for spec in SPORTS.values():
        if not spec.live:
            # Shells are expected to be incomplete; report as info, never fail.
            warnings.append(f"{spec.code}: declared not-live ({spec.notes or 'shell only'}).")
            continue
        _check_loaders(spec, failures, warnings)
        _check_stat_map(spec, failures, warnings)
        _check_market_coverage(spec, warnings)
        _check_calibrator_and_qc(spec, warnings)

    report = {
        'checked_at': checked_at,
        'clean': len(failures) == 0,
        'pass_count': max(len(SPORTS) - len(failures), 0),
        'warning_count': len(warnings),
        'failure_count': len(failures),
        'route_count': len(SPORTS),
        'notes': f"Verified {len(SPORTS)} registered sports ({len([s for s in SPORTS.values() if s.live])} live).",
        'warnings': warnings,
        'failures': failures,
    }
    append_qc_run_log('sport_registry', report)
    return report


def main() -> int:
    report = run_qc()
    print('=' * 60)
    print('SPORT REGISTRY QC')
    print('=' * 60)
    print(f"Checked at: {report['checked_at']}")
    print(f"Sports registered: {report['route_count']}")
    print(f"Warnings: {report['warning_count']}")
    print(f"Failures: {report['failure_count']}")
    print(f"Clean: {report['clean']}")
    print(report['notes'])
    print()
    for item in report['warnings']:
        print(f'[WARN] {item}')
    for item in report['failures']:
        print(f'[FAIL] {item}')
    return 0 if report['clean'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
