"""NFL Same-Game-Parlay Workbench — deterministic alignment/contradiction engine (V1, frozen rules).

Pure functions over the user's SELECTED legs + their SELECTED thesis. No hidden score, no ordering
authority, no probability claim. Every finding names its exact rule and the legs it touches. Buckets:
SUPPORTS (logical compatibility with the thesis only -- never a value claim), CONFLICT (direct), TENSION
(mixed / "show the math" relationships that are not automatic contradictions), CONCENTRATION (exposure
warnings, not predictions), UNKNOWN (insufficient evidence -- never silently treated as aligned).

A leg is a dict with (at least):
    kind       : 'player' | 'game' | 'team_total'
    category   : 'QB' | 'Rushing' | 'Receiving' | 'Touchdowns' | 'Defense' | 'Game Line' | 'Team Total'
    player     : str | None            # player legs
    team       : str | None            # the team the leg belongs to (player's team, team-total, or side)
    stat       : str                   # 'Pass Yards', 'Rush Yards', 'Receptions', 'Anytime TD', 'Total', ...
    direction  : 'OVER' | 'UNDER'
    line       : float | None
    label      : str                   # human label for the leg (for findings)
Game-total legs use kind='game', category='Game Line', stat containing 'Total'. Team-total legs use
kind='team_total', category='Team Total', team set. Game-side legs use kind='game' with stat
containing 'Spread'/'Moneyline'/'Side'.
"""
from __future__ import annotations


# Presentation buckets. TENSION is distinct from CONFLICT (a mixed relationship is not a contradiction).
SUPPORTS, CONFLICT, TENSION, CONCENTRATION, UNKNOWN = (
    'supports', 'conflict', 'tension', 'concentration', 'unknown')

# User-selectable theses (presentation + logical compatibility only; never a value claim).
THESES = [
    ('home_controls', 'Home team controls the game'),
    ('away_trails_passes', 'Away team trails and passes'),
    ('low_scoring_defensive', 'Low-scoring defensive game'),
    ('shootout', 'High-scoring shootout'),
    ('run_heavy', 'Run-heavy game'),
    ('pass_heavy', 'Pass-heavy game'),
    ('custom', 'Custom thesis'),
]
_THESIS_KEYS = {k for k, _ in THESES}

# Theses that explicitly imply a trailing / pass-heavy script (used only for mechanically-defensible
# thesis conflicts, never to score a bet).
_TRAILING_PASS_THESES = {'away_trails_passes', 'pass_heavy'}


# ---- leg classifiers (mechanical, from the leg's own fields; no inference about "primary" anything) ----

def _dir(leg):
    return str(leg.get('direction') or '').strip().upper()


def _cat(leg):
    return str(leg.get('category') or '').strip()


def _stat(leg):
    return str(leg.get('stat') or '')


def _team(leg):
    t = leg.get('team')
    return str(t).strip().upper() if t else None


def is_qb_pass(leg):
    return _cat(leg) == 'QB' and 'Pass' in _stat(leg)


def is_receiving(leg):
    return _cat(leg) == 'Receiving'


def is_rushing(leg):
    return _cat(leg) == 'Rushing'


def is_rb_rushing(leg):
    # RB rushing: a rushing leg whose position is RB/FB when known; otherwise a rushing player leg that is
    # not the QB category. We never infer beyond the leg's own position field.
    if not is_rushing(leg):
        return False
    pos = str(leg.get('position') or '').strip().upper()
    return pos in ('RB', 'FB') if pos else True


def is_touchdown(leg):
    return _cat(leg) == 'Touchdowns'


def is_game_total(leg):
    return leg.get('kind') == 'game' and 'Total' in _stat(leg)


def is_game_side(leg):
    s = _stat(leg)
    return leg.get('kind') == 'game' and ('Spread' in s or 'Moneyline' in s or 'Side' in s)


def is_team_total(leg):
    return leg.get('kind') == 'team_total'


def is_offensive_over(leg):
    """A selected OVER on QB passing, rushing, receiving, or a touchdown leg."""
    return _dir(leg) == 'OVER' and (is_qb_pass(leg) or is_rushing(leg) or is_receiving(leg)
                                    or is_touchdown(leg))


def leg_label(leg):
    base = leg.get('label')
    if base:
        return str(base)
    who = leg.get('player') or leg.get('team') or 'Leg'
    ln = leg.get('line')
    ln = '' if ln is None else f' {ln}'
    return f"{who} {_dir(leg)} {_stat(leg)}{ln}".strip()


def _finding(bucket, rule_id, text, legs):
    return {'bucket': bucket, 'rule_id': rule_id, 'rule': text,
            'legs': [leg_label(x) for x in legs]}


# ---- the frozen V1 ruleset ----------------------------------------------------------------------------

def _same_player_opposing(legs):
    out = []
    by = {}
    for lg in legs:
        key = (str(lg.get('player') or '').strip().lower(), _stat(lg)) if lg.get('player') else None
        if key and key[0]:
            by.setdefault(key, []).append(lg)
    for (player, stat), group in by.items():
        dirs = {_dir(x) for x in group}
        if 'OVER' in dirs and 'UNDER' in dirs:
            out.append(_finding(CONFLICT, 'R1_same_player_stat_opposing',
                                'Same player and stat selected Over and Under.', group))
    return out


def _same_market_opposing(legs):
    out = []
    buckets = {}
    for lg in legs:
        if is_game_total(lg):
            key = ('game_total',)
        elif is_game_side(lg):
            key = ('game_side',)
        elif is_team_total(lg):
            key = ('team_total', _team(lg))
        else:
            continue
        buckets.setdefault(key, []).append(lg)
    for key, group in buckets.items():
        if {_dir(x) for x in group} >= {'OVER', 'UNDER'}:
            if key[0] == 'team_total':
                name = f'{key[1]} team total'
            else:
                name = {'game_total': 'game total', 'game_side': 'game side'}.get(key[0], key[0])
            out.append(_finding(CONFLICT, 'R2_same_market_opposing',
                                f'Opposing directions selected on the same {name}.', group))
    return out


def _concentration(legs):
    out = []
    # >2 legs on the same player
    by_player = {}
    for lg in legs:
        p = str(lg.get('player') or '').strip()
        if p:
            by_player.setdefault(p.lower(), []).append(lg)
    for _p, group in by_player.items():
        if len(group) > 2:
            out.append(_finding(CONCENTRATION, 'R3_player_concentration',
                                'More than two selected legs involve the same player (exposure '
                                'concentration, not a prediction).', group))
    # >=4 legs on one team
    by_team = {}
    for lg in legs:
        t = _team(lg)
        if t:
            by_team.setdefault(t, []).append(lg)
    for _t, group in by_team.items():
        if len(group) >= 4:
            out.append(_finding(CONCENTRATION, 'R4_team_script_concentration',
                                "Four or more selected legs depend on one team's script "
                                '(exposure concentration, not a prediction).', group))
    # >=3 touchdown-scorer legs
    td = [lg for lg in legs if is_touchdown(lg)]
    if len(td) >= 3:
        out.append(_finding(CONCENTRATION, 'R5_touchdown_concentration',
                            'Three or more touchdown-scorer legs compete for a limited number of '
                            'scoring events (concentration, not a prediction).', td))
    return out


def _qb_receiver_relationships(legs, thesis):
    out = []
    # group by team
    teams = {}
    for lg in legs:
        t = _team(lg)
        if t:
            teams.setdefault(t, []).append(lg)
    for _t, group in teams.items():
        qb_over = [x for x in group if is_qb_pass(x) and _dir(x) == 'OVER']
        qb_under = [x for x in group if is_qb_pass(x) and _dir(x) == 'UNDER']
        rec_over = [x for x in group if is_receiving(x) and _dir(x) == 'OVER']
        rec_under = [x for x in group if is_receiving(x) and _dir(x) == 'UNDER']
        # R6: QB pass Over + any same-team receiver Under -> TENSION (mixed); never auto-conflict in V1
        # (the thesis set has no "depends on receiver X" selector).
        if qb_over and rec_under:
            out.append(_finding(TENSION, 'R6_qb_over_receiver_under',
                                'QB passing Over is selected with a same-team receiver Under — a mixed '
                                'relationship to review, not an automatic contradiction.',
                                qb_over + rec_under))
        # R7: QB pass Under + >=2 same-team receiving Overs -> CONFLICT (internally inconsistent volume)
        if qb_under and len(rec_over) >= 2:
            out.append(_finding(CONFLICT, 'R7_qb_under_multi_receiver_over',
                                'QB passing Under is selected with multiple same-team receiving Overs — '
                                'they conflict on passing volume.', qb_under + rec_over))
    return out


def _thesis_conflicts(legs, thesis):
    out = []
    # R8: RB rushing Over with an explicitly selected trailing/pass-heavy thesis
    if thesis in _TRAILING_PASS_THESES:
        rb_over = [x for x in legs if is_rb_rushing(x) and _dir(x) == 'OVER']
        if rb_over:
            out.append(_finding(CONFLICT, 'R8_rb_over_vs_pass_thesis',
                                'RB rushing Over conflicts with the selected trailing / pass-heavy '
                                'thesis.', rb_over))
    return out


def _game_under_tension(legs):
    out = []
    game_unders = [x for x in legs if is_game_total(x) and _dir(x) == 'UNDER']
    if not game_unders:
        return out
    off_overs = [x for x in legs if is_offensive_over(x) and not is_touchdown(x)]
    td_legs = [x for x in legs if is_touchdown(x)]
    if len(off_overs) >= 2 or len(td_legs) >= 2:
        out.append(_finding(TENSION, 'R9_game_under_vs_offense',
                            'A game Under is selected alongside multiple offensive Overs or touchdown '
                            'legs — a tension to review (not a mathematical impossibility).',
                            game_unders + off_overs + td_legs))
    return out


def _team_total_vs_game_under(legs, game_total_line):
    out = []
    game_unders = [x for x in legs if is_game_total(x) and _dir(x) == 'UNDER']
    tt_overs = [x for x in legs if is_team_total(x) and _dir(x) == 'OVER' and x.get('line') is not None]
    if not (game_unders and tt_overs):
        return out
    gline = None
    for gu in game_unders:
        if gu.get('line') is not None:
            gline = float(gu['line'])
            break
    if gline is None and game_total_line is not None:
        gline = float(game_total_line)
    if gline is None:
        # cannot do the math -> Unknown, never silently aligned
        out.append(_finding(UNKNOWN, 'R10_team_total_game_under_no_line',
                            'Team-total Over with a game Under, but the game total line is unavailable — '
                            'cannot compute the implied opponent points.', tt_overs + game_unders))
        return out
    for tt in tt_overs:
        team = _team(tt)
        tline = float(tt['line'])
        remaining = round(gline - tline, 1)
        # opponent team-total Over legs selected for the OTHER team
        opp_tt_over = [x for x in legs if is_team_total(x) and _dir(x) == 'OVER'
                       and _team(x) and _team(x) != team and x.get('line') is not None]
        requires_more = [x for x in opp_tt_over if float(x['line']) > remaining]
        detail = (f"{team} team-total Over {tline} with a game Under {gline} leaves ~{remaining} implied "
                  f"points for the opponent.")
        if requires_more:
            out.append(_finding(CONFLICT, 'R10_team_total_game_under_conflict',
                                detail + ' Selected opponent legs require more than that remaining amount.',
                                [tt] + game_unders + requires_more))
        else:
            out.append(_finding(TENSION, 'R10_team_total_game_under_tension',
                                detail + ' Within the remaining amount for now — tension, not a conflict.',
                                [tt] + game_unders))
    return out


# ---- thesis "supports" (logical compatibility ONLY; never evidence of value) --------------------------

def _supports(legs, thesis):
    """A leg SUPPORTS the thesis when its direction/category is LOGICALLY COMPATIBLE with the selected
    game story. This is compatibility, not a claim the bet wins. Legs with no determinable relationship
    are left for the UNKNOWN pass, never silently 'supporting'."""
    rules = {
        'shootout': lambda lg: is_game_total(lg) and _dir(lg) == 'OVER'
                    or (is_offensive_over(lg)),
        'low_scoring_defensive': lambda lg: (is_game_total(lg) and _dir(lg) == 'UNDER')
                    or (_cat(lg) == 'Defense' and _dir(lg) == 'OVER')
                    or ((is_qb_pass(lg) or is_receiving(lg) or is_rushing(lg)) and _dir(lg) == 'UNDER'),
        'pass_heavy': lambda lg: (is_qb_pass(lg) and _dir(lg) == 'OVER')
                    or (is_receiving(lg) and _dir(lg) == 'OVER')
                    or (is_rb_rushing(lg) and _dir(lg) == 'UNDER'),
        'run_heavy': lambda lg: (is_rb_rushing(lg) and _dir(lg) == 'OVER')
                    or (is_qb_pass(lg) and _dir(lg) == 'UNDER'),
        'away_trails_passes': lambda lg: (is_qb_pass(lg) and _dir(lg) == 'OVER')
                    or (is_receiving(lg) and _dir(lg) == 'OVER'),
        'home_controls': lambda lg: (is_rb_rushing(lg) and _dir(lg) == 'OVER'),
    }
    pred = rules.get(thesis)
    if pred is None:   # custom / unknown thesis -> nothing auto-supports
        return []
    hits = [lg for lg in legs if pred(lg)]
    if not hits:
        return []
    return [_finding(SUPPORTS, f'S_{thesis}',
                     'Logically compatible with the selected game story (compatibility only — not '
                     'evidence the bet has value).', hits)]


def evaluate(legs, thesis='custom', game_total_line=None):
    """Return the full deterministic read of the selected legs under the selected thesis.
    { 'thesis', 'findings': [...], 'buckets': {supports/conflict/tension/concentration/unknown: [...]},
      'disclosure': <verbatim correlation disclosure> }. Pure function; no ordering/score/probability."""
    legs = list(legs or [])
    thesis = thesis if thesis in _THESIS_KEYS else 'custom'
    findings = []
    findings += _same_player_opposing(legs)
    findings += _same_market_opposing(legs)
    findings += _concentration(legs)
    findings += _qb_receiver_relationships(legs, thesis)
    findings += _thesis_conflicts(legs, thesis)
    findings += _game_under_tension(legs)
    findings += _team_total_vs_game_under(legs, game_total_line)
    findings += _supports(legs, thesis)
    buckets = {SUPPORTS: [], CONFLICT: [], TENSION: [], CONCENTRATION: [], UNKNOWN: []}
    for f in findings:
        buckets[f['bucket']].append(f)
    return {'thesis': thesis, 'findings': findings, 'buckets': buckets,
            'disclosure': CORRELATION_DISCLOSURE}


CORRELATION_DISCLOSURE = (
    'These legs may move together, but the sportsbook prices same-game correlation. Alignment can make '
    'the ticket coherent; it does not prove the combined price is favorable.')

INDEPENDENCE_LABEL = (
    "Assumes independence; not the sportsbook's correlation-adjusted probability.")
