"""Declarative registry of every sport the platform supports.

Why this exists: each sport's pieces (loaders, stat map, archive thresholds, QC,
calibrator) were discovered by grepping, and a MISSING piece was invisible. That
cost a whole season twice over:

  * NFL/NCAAF had no prop-stat -> gamelog-column map, so grading looked up
    "REC YDS" against a column named RecYd, never matched, and left every
    football pick Pending forever. Archiving worked; grading silently did not.
  * MLB's lineup gate read a field its odds feed never carried, so no MLB
    curated pick could ever be archived.

Neither showed up in the UI. Both were "this sport is missing a part that the
other sports have", which is precisely what a registry makes checkable.

This module holds DATA ONLY -- no imports from app.py -- so app.py can import it
without a cycle. Names are resolved lazily by whoever needs the callable
(qc_sport_registry.py does exactly that to verify they exist).

Adding a sport: add a SportSpec, then run `python qc_sport_registry.py`. It will
tell you which pieces are missing rather than letting the gap ship silently.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class SportSpec:
    code: str                       # archive `Sport` value, e.g. 'NFL'
    key: str                        # url/sport_key, e.g. 'nfl'
    label: str

    # app.py function names. Strings, not callables, to keep this import-free.
    props_loader: str
    gamelog_loader: str
    schedule_loader: str
    odds_loader: str

    # The loader refresh_all_prop_results.py grades against. Usually the same as
    # gamelog_loader -- NBA is the exception: load_gamelogs stops at the regular
    # season (2026-04-12) while load_nba_review_gamelogs includes the playoffs
    # (2026-06-13). Grading against the wrong one silently under-resolves picks.
    grading_gamelog_loader: str

    # Name of the prop-stat -> gamelog-column map in app.py, or None when the
    # sport's prop stat names ARE its gamelog column names (identity).
    # identity_ok records that None is a deliberate, verified choice rather than
    # an oversight -- the distinction the football bug turned on.
    stat_column_map: str | None
    identity_ok: bool

    # Archive eligibility gates. None where the sport archives through a path
    # that does not use these (NBA trends gates on run length / consistency).
    min_market_prob: float | None
    min_lean_gap: float | None

    # Whether the sport's curated archiver requires play_verdict == 'PLAY'.
    # MLB/WNBA do; football does not. Recorded because a verdict that can never
    # be 'PLAY' silently zeroes out archiving.
    requires_play_verdict: bool

    qc_prefix: str                  # qc_<prefix>_*.py
    calibrator: str | None          # calibrate_<x>_model.py
    live: bool = True               # False = shell/planned, not yet built
    notes: str = ''


SPORTS: dict[str, SportSpec] = {
    'NBA': SportSpec(
        code='NBA', key='nba', label='NBA',
        props_loader='load_props',              # NBA predates the prefix convention
        gamelog_loader='load_gamelogs',
        schedule_loader='load_schedule',
        odds_loader='load_game_market_odds',
        grading_gamelog_loader='load_nba_review_gamelogs',
        stat_column_map=None, identity_ok=True,   # PTS/REB/AST already match columns
        min_market_prob=None, min_lean_gap=None,  # trend archiver uses run/consistency
        requires_play_verdict=False,
        qc_prefix='nba', calibrator='calibrate_nba_model.py',
        notes='Unprefixed loader names; archives via archive_trend_candidates.',
    ),
    'WNBA': SportSpec(
        code='WNBA', key='wnba', label='WNBA',
        props_loader='load_wnba_props',
        gamelog_loader='load_wnba_gamelogs',
        schedule_loader='load_wnba_schedule',
        odds_loader='load_wnba_game_market_odds',
        grading_gamelog_loader='load_wnba_gamelogs',
        stat_column_map=None, identity_ok=True,
        min_market_prob=58, min_lean_gap=5,
        requires_play_verdict=True,
        qc_prefix='wnba', calibrator='calibrate_wnba_model.py',
        notes='Reference implementation: the only sport with a proven end-to-end record.',
    ),
    'MLB': SportSpec(
        code='MLB', key='mlb', label='MLB',
        props_loader='load_mlb_props',
        gamelog_loader='load_mlb_gamelogs',
        schedule_loader='load_mlb_schedule',
        odds_loader='load_mlb_game_market_odds',
        grading_gamelog_loader='load_mlb_gamelogs',
        stat_column_map='MLB_STAT_COLUMN_MAP', identity_ok=False,
        min_market_prob=57, min_lean_gap=4,
        requires_play_verdict=True,
        qc_prefix='mlb', calibrator='calibrate_mlb_model.py',
        notes='Batter props need confirmed lineups (fetch_mlb_lineups.py) or the gate blocks archiving.',
    ),
    'NFL': SportSpec(
        code='NFL', key='nfl', label='NFL',
        props_loader='load_nfl_props',
        gamelog_loader='load_nfl_gamelogs',
        schedule_loader='load_nfl_schedule',
        odds_loader='load_nfl_game_market_odds',
        grading_gamelog_loader='load_nfl_gamelogs',
        stat_column_map='FOOTBALL_STAT_COLUMN_MAP', identity_ok=False,
        min_market_prob=56, min_lean_gap=4,
        requires_play_verdict=False,
        qc_prefix='nfl', calibrator='calibrate_nfl_model.py',
    ),
    'NCAAF': SportSpec(
        code='NCAAF', key='ncaaf', label='College Football',
        props_loader='load_ncaaf_props',
        gamelog_loader='load_ncaaf_gamelogs',
        schedule_loader='load_ncaaf_schedule',
        odds_loader='load_ncaaf_game_market_odds',
        grading_gamelog_loader='load_ncaaf_gamelogs',
        stat_column_map='FOOTBALL_STAT_COLUMN_MAP', identity_ok=False,
        min_market_prob=56, min_lean_gap=4,
        requires_play_verdict=False,
        qc_prefix='cfb', calibrator='calibrate_cfb_model.py',
        notes='QC/calibrator use the cfb prefix, not ncaaf -- a grep for "ncaaf" misses them.',
    ),
    'NCAAMB': SportSpec(
        code='NCAAMB', key='ncaamb', label="Men's College Hoops",
        props_loader='load_ncaamb_props', gamelog_loader='load_ncaamb_gamelogs',
        schedule_loader='load_ncaamb_schedule', odds_loader='load_ncaamb_game_market_odds',
        grading_gamelog_loader='load_ncaamb_gamelogs',
        stat_column_map=None, identity_ok=False,
        min_market_prob=None, min_lean_gap=None,
        requires_play_verdict=False,
        qc_prefix='ncaamb', calibrator=None, live=False,
        notes='Themed shell only: routes render, no data pipeline yet. Deferred to tip-off.',
    ),
    'NCAAWB': SportSpec(
        code='NCAAWB', key='ncaawb', label="Women's College Hoops",
        props_loader='load_ncaawb_props', gamelog_loader='load_ncaawb_gamelogs',
        schedule_loader='load_ncaawb_schedule', odds_loader='load_ncaawb_game_market_odds',
        grading_gamelog_loader='load_ncaawb_gamelogs',
        stat_column_map=None, identity_ok=False,
        min_market_prob=None, min_lean_gap=None,
        requires_play_verdict=False,
        qc_prefix='ncaawb', calibrator=None, live=False,
        notes='Themed shell only: routes render, no data pipeline yet. Deferred to tip-off.',
    ),
}


def live_sports() -> list[SportSpec]:
    """Sports with a real pipeline, as opposed to a rendered shell."""
    return [spec for spec in SPORTS.values() if spec.live]


def spec_for(code: str) -> SportSpec | None:
    return SPORTS.get(str(code or '').strip().upper())


def stat_map_name(code: str) -> str | None:
    """Name of the sport's stat-column map, or None for identity mapping."""
    spec = spec_for(code)
    return spec.stat_column_map if spec else None
