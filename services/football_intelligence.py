from __future__ import annotations

from typing import Callable

import numpy as np
import pandas as pd


NormalizeTeamName = Callable[[str], str]


def _clean_display_text(value) -> str:
    if value is None:
        return ''
    try:
        if pd.isna(value):
            return ''
    except Exception:
        pass
    text = str(value).strip()
    return '' if text.lower() in {'nan', 'none', 'null'} else text


def build_ncaaf_signal_profile(row: dict | pd.Series) -> dict:
    if isinstance(row, pd.Series):
        row = row.to_dict()
    else:
        row = dict(row or {})
    returning_production = float(pd.to_numeric(row.get('ReturningProduction'), errors='coerce') or 0.0)
    pass_yds = float(pd.to_numeric(row.get('pass_yds'), errors='coerce') or 0.0)
    tackles = float(pd.to_numeric(row.get('tackles'), errors='coerce') or 0.0)
    portal_in = int(pd.to_numeric(row.get('PortalIn'), errors='coerce') or 0)
    portal_out = int(pd.to_numeric(row.get('PortalOut'), errors='coerce') or 0)
    portal_net = int(pd.to_numeric(row.get('PortalNet'), errors='coerce') or 0)
    high_continuity = bool(row.get('HighContinuityFlag', False))
    qb_continuity = bool(row.get('QBContinuityFlag', False))
    defensive_support = bool(row.get('DefensiveSupportFlag', False))
    portal_volatility = bool(row.get('PortalVolatilityFlag', False))

    score = 50.0
    if high_continuity:
        score += 16
    if qb_continuity:
        score += 12
    if defensive_support:
        score += 8
    if portal_net >= 3:
        score += min(8.0, float(portal_net))
    if returning_production >= 0.70:
        score += 4
    elif returning_production < 0.45:
        score -= 7
    if portal_volatility:
        score -= 15
    if portal_out >= max(portal_in + 4, 10):
        score -= 6
    if qb_continuity and pass_yds >= 2500:
        score += 4
    if defensive_support and tackles >= 65:
        score += 2

    score = round(max(20.0, min(score, 95.0)), 1)

    if score >= 72:
        tier = 'stable'
        badge = 'STABLE'
        note = 'This roster has enough continuity support to help sides and totals hold their shape early.'
    elif score >= 60:
        tier = 'supported'
        badge = 'SUPPORTED'
        note = 'There is enough continuity here to support a market read, but not enough to ignore matchup context.'
    elif score >= 48:
        tier = 'mixed'
        badge = 'MIXED'
        note = 'This profile has some support, but the roster still carries enough uncertainty to keep reads moderate.'
    else:
        tier = 'volatile'
        badge = 'VOLATILE'
        note = 'Roster churn and weak continuity make this team harder to trust until the season settles in.'

    verdict = 'Balanced continuity read'
    if tier == 'stable' and qb_continuity:
        verdict = 'Stable offense profile'
    elif tier == 'stable' and defensive_support:
        verdict = 'Supportive early-season under/dog profile'
    elif tier == 'volatile' and portal_volatility:
        verdict = 'Roster churn is the main story'
    elif tier == 'supported' and qb_continuity:
        verdict = 'Quarterback continuity supports the baseline'
    elif tier == 'mixed':
        verdict = 'Useful support, but not enough to carry a bet by itself'

    return {
        'score': score,
        'tier': tier,
        'badge': badge,
        'note': note,
        'verdict': verdict,
    }
NormalizePlayerJoinKey = Callable[[str], str]
NormalizePositionGroup = Callable[[str], str]


def build_ncaaf_player_master(
    current_roster: pd.DataFrame,
    player_history: pd.DataFrame,
    portal: pd.DataFrame,
    *,
    last_season: int | None,
    normalize_team_name: NormalizeTeamName,
    normalize_player_join_key: NormalizePlayerJoinKey,
    normalize_position_group: NormalizePositionGroup,
) -> pd.DataFrame:
    roster = current_roster.copy() if current_roster is not None else pd.DataFrame()
    history = player_history.copy() if player_history is not None else pd.DataFrame()
    portal_df = portal.copy() if portal is not None else pd.DataFrame()

    if roster.empty:
        return pd.DataFrame()

    if history.empty:
        working = roster.copy()
        working['LastSeasonTeam'] = ''
        working['TransferFlag'] = False
        for col in [
            'CareerGames', 'CareerPassYds', 'CareerPassTD', 'CareerPassInt',
            'CareerRushYds', 'CareerRushTD', 'CareerReceptions', 'CareerRecYds',
            'CareerRecTD', 'CareerTackles', 'CareerSacks', 'CareerDefInt',
        ]:
            working[col] = np.nan
        if not portal_df.empty:
            portal_working = portal_df.copy()
            portal_working['NameKey'] = portal_working['Player'].apply(normalize_player_join_key)
            portal_working['PositionGroup'] = portal_working['Position'].apply(normalize_position_group)
            portal_working['DestinationTeam'] = portal_working['DestinationTeam'].apply(normalize_team_name)
            portal_working['OriginTeam'] = portal_working['OriginTeam'].apply(normalize_team_name)
            working['NameKey'] = working['Player'].apply(normalize_player_join_key)
            working['PositionGroup'] = working['Position'].apply(normalize_position_group)
            working = working.merge(
                portal_working[['NameKey', 'PositionGroup', 'DestinationTeam', 'OriginTeam']]
                .drop_duplicates(subset=['NameKey', 'PositionGroup', 'DestinationTeam'], keep='first'),
                left_on=['NameKey', 'PositionGroup', 'CurrentTeam'],
                right_on=['NameKey', 'PositionGroup', 'DestinationTeam'],
                how='left',
            )
            working['LastSeasonTeam'] = working['OriginTeam'].fillna('')
            working['TransferFlag'] = working['LastSeasonTeam'].astype(str).str.strip() != ''
            working = working.drop(
                columns=['NameKey', 'PositionGroup', 'DestinationTeam', 'OriginTeam'],
                errors='ignore',
            )
        return working

    roster['NameKey'] = roster['Player'].apply(normalize_player_join_key)
    roster['PositionKey'] = roster['Position'].fillna('').astype(str).str.upper().str.replace(r'[^A-Z]', '', regex=True)
    roster['PositionGroup'] = roster['Position'].apply(normalize_position_group)
    roster['NamePosKey'] = roster['NameKey'] + '|' + roster['PositionGroup']

    history['NameKey'] = history['Player'].apply(normalize_player_join_key)
    history['PositionKey'] = history['Position'].fillna('').astype(str).str.upper().str.replace(r'[^A-Z]', '', regex=True)
    history['PositionGroup'] = history['Position'].apply(normalize_position_group)
    history['NamePosKey'] = history['NameKey'] + '|' + history['PositionGroup']

    season_numeric = pd.to_numeric(history['Season'], errors='coerce')
    if last_season is None:
        valid = season_numeric.dropna()
        last_season = int(valid.max()) if not valid.empty else None

    agg_cols = [
        'Games', 'PassYds', 'PassTD', 'PassInt', 'RushYds', 'RushTD',
        'Receptions', 'RecYds', 'RecTD', 'Tackles', 'Sacks', 'DefInt',
    ]
    career = history.groupby('PlayerJoinKey', dropna=False)[agg_cols].sum(min_count=1).reset_index()
    career = career.rename(columns={
        'Games': 'CareerGames',
        'PassYds': 'CareerPassYds',
        'PassTD': 'CareerPassTD',
        'PassInt': 'CareerPassInt',
        'RushYds': 'CareerRushYds',
        'RushTD': 'CareerRushTD',
        'Receptions': 'CareerReceptions',
        'RecYds': 'CareerRecYds',
        'RecTD': 'CareerRecTD',
        'Tackles': 'CareerTackles',
        'Sacks': 'CareerSacks',
        'DefInt': 'CareerDefInt',
    })

    last_team = pd.DataFrame(columns=['PlayerJoinKey', 'LastSeasonTeam'])
    if last_season is not None:
        last_rows = history[season_numeric == float(last_season)].copy()
        if not last_rows.empty:
            last_rows = last_rows.sort_values(['PlayerJoinKey', 'Games'], ascending=[True, False])
            last_team = (
                last_rows.drop_duplicates(subset=['PlayerJoinKey'], keep='first')[['PlayerJoinKey', 'Team']]
                .rename(columns={'Team': 'LastSeasonTeam'})
            )

    latest_identity = (
        history.sort_values(['PlayerJoinKey', 'Season', 'Games'], ascending=[True, False, False])
        .drop_duplicates(subset=['PlayerJoinKey'], keep='first')
    )
    latest_identity = latest_identity[['PlayerJoinKey', 'Player', 'Position', 'Class']].copy()

    playerkey_by_name = (
        history[['PlayerJoinKey', 'NameKey']].drop_duplicates()
        .groupby('NameKey')['PlayerJoinKey'].nunique()
        .reset_index(name='PlayerKeyCount')
    )
    unique_name_keys = set(playerkey_by_name.loc[playerkey_by_name['PlayerKeyCount'] == 1, 'NameKey'])
    unique_name_map = (
        history[history['NameKey'].isin(unique_name_keys)][['NameKey', 'PlayerJoinKey']]
        .drop_duplicates(subset=['NameKey'], keep='first')
        .rename(columns={'PlayerJoinKey': 'FallbackJoinKey_Name'})
    )

    playerkey_by_namepos = (
        history[['PlayerJoinKey', 'NamePosKey']].drop_duplicates()
        .groupby('NamePosKey')['PlayerJoinKey'].nunique()
        .reset_index(name='PlayerKeyCount')
    )
    unique_namepos_keys = set(playerkey_by_namepos.loc[playerkey_by_namepos['PlayerKeyCount'] == 1, 'NamePosKey'])
    unique_namepos_map = (
        history[history['NamePosKey'].isin(unique_namepos_keys)][['NamePosKey', 'PlayerJoinKey']]
        .drop_duplicates(subset=['NamePosKey'], keep='first')
        .rename(columns={'PlayerJoinKey': 'FallbackJoinKey_NamePos'})
    )

    roster = roster.merge(unique_name_map, on='NameKey', how='left')
    roster = roster.merge(unique_namepos_map, on='NamePosKey', how='left')
    roster['ResolvedHistoryJoinKey'] = roster['PlayerJoinKey']
    roster['ResolvedHistoryJoinKey'] = roster['ResolvedHistoryJoinKey'].replace('', pd.NA)
    roster['ResolvedHistoryJoinKey'] = roster['ResolvedHistoryJoinKey'].fillna(roster['FallbackJoinKey_Name'])
    roster['ResolvedHistoryJoinKey'] = roster['ResolvedHistoryJoinKey'].fillna(roster['FallbackJoinKey_NamePos']).fillna('')

    latest_identity_resolved = latest_identity.rename(columns={'PlayerJoinKey': 'ResolvedHistoryJoinKey'})
    career_resolved = career.rename(columns={'PlayerJoinKey': 'ResolvedHistoryJoinKey'})
    last_team_resolved = last_team.rename(columns={'PlayerJoinKey': 'ResolvedHistoryJoinKey'})

    master = roster.merge(latest_identity_resolved, on='ResolvedHistoryJoinKey', how='left', suffixes=('', '_Hist'))
    for col in ['Player', 'Position', 'Class']:
        hist_col = f'{col}_Hist'
        if hist_col in master.columns:
            master[col] = master[col].replace('', pd.NA).fillna(master[hist_col]).fillna('')
            master = master.drop(columns=[hist_col])
    master = master.merge(last_team_resolved, on='ResolvedHistoryJoinKey', how='left')
    master = master.merge(career_resolved, on='ResolvedHistoryJoinKey', how='left')
    master['LastSeasonTeam'] = master['LastSeasonTeam'].fillna('')

    if not portal_df.empty:
        portal_working = portal_df.copy()
        portal_working['NameKey'] = portal_working['Player'].apply(normalize_player_join_key)
        portal_working['PositionGroup'] = portal_working['Position'].apply(normalize_position_group)
        portal_working['DestinationTeam'] = portal_working['DestinationTeam'].apply(normalize_team_name)
        portal_working['OriginTeam'] = portal_working['OriginTeam'].apply(normalize_team_name)
        if {'Rating', 'Stars'}.issubset(portal_working.columns):
            portal_working = portal_working.sort_values(['Rating', 'Stars'], ascending=False, na_position='last')
        portal_lookup = (
            portal_working[['NameKey', 'PositionGroup', 'DestinationTeam', 'OriginTeam']]
            .drop_duplicates(subset=['NameKey', 'PositionGroup', 'DestinationTeam'], keep='first')
        )
        master = master.merge(
            portal_lookup,
            left_on=['NameKey', 'PositionGroup', 'CurrentTeam'],
            right_on=['NameKey', 'PositionGroup', 'DestinationTeam'],
            how='left',
        )
        portal_origin = master['OriginTeam'].fillna('').astype(str).str.strip()
        missing_last_team = master['LastSeasonTeam'].astype(str).str.strip() == ''
        mask = missing_last_team & (portal_origin != '')
        master.loc[mask, 'LastSeasonTeam'] = portal_origin[mask]
        master = master.drop(columns=['DestinationTeam', 'OriginTeam'], errors='ignore')

    master['TransferFlag'] = (
        (master['LastSeasonTeam'].astype(str).str.strip() != '') &
        (master['CurrentTeam'].astype(str).str.strip() != '') &
        (master['LastSeasonTeam'].astype(str).str.strip() != master['CurrentTeam'].astype(str).str.strip())
    )
    master = master.drop(
        columns=[
            'FallbackJoinKey_Name', 'FallbackJoinKey_NamePos', 'ResolvedHistoryJoinKey',
            'NameKey', 'PositionKey', 'PositionGroup', 'NamePosKey',
        ],
        errors='ignore',
    )
    return master


def build_ncaaf_current_season_context(
    roster: pd.DataFrame,
    history: pd.DataFrame,
    returning: pd.DataFrame,
    portal: pd.DataFrame,
    coverage: pd.DataFrame,
    *,
    next_steps: list[str],
    normalize_team_name: NormalizeTeamName,
    normalize_player_join_key: NormalizePlayerJoinKey,
    normalize_position_group: NormalizePositionGroup,
    last_season: int | None,
) -> dict:
    master = build_ncaaf_player_master(
        roster,
        history,
        portal,
        last_season=last_season,
        normalize_team_name=normalize_team_name,
        normalize_player_join_key=normalize_player_join_key,
        normalize_position_group=normalize_position_group,
    )

    if roster.empty:
        return {
            'available': False,
            'state': 'waiting',
            'note': 'Add the current college-football roster file to start the present-season layer. This is the foundation for continuity, transfers, and returning production.',
            'next_steps': next_steps,
            'cards': [
                {'label': 'Rostered Players', 'value': 0, 'note': 'Current-season players currently loaded into the CFB roster file.'},
                {'label': 'Teams Loaded', 'value': 0, 'note': 'Distinct college programs represented in the current roster file.'},
                {'label': 'Confirmed Transfers', 'value': 0, 'note': 'Player-level transfer matches only count when roster, portal, and prior-team data line up cleanly.'},
            ],
            'position_cards': [
                {'label': 'Quarterbacks', 'value': 0, 'note': 'Signal-callers currently loaded into the roster layer.'},
                {'label': 'Running Backs', 'value': 0, 'note': 'Backfield bodies available for continuity and rushing-production reads.'},
                {'label': 'Receivers + TEs', 'value': 0, 'note': 'Primary pass-catchers available for returning production support.'},
            ],
            'top_qbs': [],
            'top_skill': [],
            'top_defense': [],
            'team_rollups': [],
            'top_returning_teams': [],
            'portal_moves': [],
            'plain_english_cards': [],
            'team_signals': [],
            'team_signals_all': [],
            'coverage_summary': {},
            'coverage_alert': None,
            'matchup_verdict_cards': [],
        }

    confirmed_transfers = int(master['TransferFlag'].sum()) if not master.empty and 'TransferFlag' in master.columns else 0
    cards = [
        {'label': 'Rostered Players', 'value': len(roster), 'note': 'Current-season players currently loaded into the CFB roster file.'},
        {'label': 'Teams Loaded', 'value': roster['CurrentTeam'].replace('', pd.NA).dropna().nunique(), 'note': 'Distinct college programs represented in the current roster file.'},
        {'label': 'Confirmed Transfers', 'value': confirmed_transfers, 'note': 'Player-level transfer matches only count when roster, portal, and prior-team data line up cleanly.'},
    ]

    def _position_count(mask: pd.Series | None, label: str, note: str) -> dict:
        count = int(mask.sum()) if mask is not None else 0
        return {'label': label, 'value': count, 'note': note}

    position = master['Position'].fillna('').astype(str).str.upper() if not master.empty and 'Position' in master.columns else pd.Series(dtype=str)
    position_cards = []
    if not master.empty:
        position_cards = [
            _position_count(position.str.contains('QB', na=False), 'Quarterbacks', 'Signal-callers currently loaded into the roster layer.'),
            _position_count(position.str.contains('RB|HB', na=False, regex=True), 'Running Backs', 'Backfield bodies available for continuity and rushing-production reads.'),
            _position_count(position.str.contains('WR|TE', na=False, regex=True), 'Receivers + TEs', 'Primary pass-catchers available for returning production support.'),
        ]
    if not returning.empty:
        position_cards.append({
            'label': 'Returning Prod Teams',
            'value': int(returning['Team'].replace('', pd.NA).dropna().nunique()) if 'Team' in returning.columns else 0,
            'note': 'Teams with official CFBD returning-production coverage loaded into the continuity layer.',
        })
    if not portal.empty:
        position_cards.append({
            'label': 'Portal Moves',
            'value': int(len(portal)),
            'note': 'Transfer portal player rows currently loaded from CFBD.',
        })

    coverage_summary = {}
    coverage_alert = None
    if not coverage.empty:
        working = coverage.copy()
        if 'RosterRows' in working.columns:
            working['RosterRows'] = pd.to_numeric(working['RosterRows'], errors='coerce').fillna(0).astype(int)
        else:
            working['RosterRows'] = 0
        working['Status'] = working.get('Status', '').fillna('').astype(str).str.strip().str.lower()
        ok_count = int((working['Status'] == 'ok').sum())
        empty_count = int((working['Status'] == 'empty').sum())
        error_count = int((working['Status'] == 'error').sum())
        total_count = int(len(working))
        coverage_summary = {'ok': ok_count, 'empty': empty_count, 'error': error_count, 'total': total_count}
        if empty_count or error_count:
            problem_rows = working[working['Status'].isin(['empty', 'error'])].copy()
            problem_rows['DisplayTeam'] = problem_rows['RequestedTeam'].fillna('').astype(str).str.strip()
            problem_rows.loc[problem_rows['DisplayTeam'] == '', 'DisplayTeam'] = problem_rows['ResolvedTeam'].fillna('').astype(str).str.strip()
            problem_rows = problem_rows[['DisplayTeam', 'Status', 'RosterRows', 'Error']].head(8)
            coverage_alert = {
                'title': 'Roster coverage warning',
                'note': f"ESPN roster coverage is mostly live, but {empty_count} teams came back empty and {error_count} returned request errors on the latest pull.",
                'items': [{
                    'team': row.get('DisplayTeam', ''),
                    'status': str(row.get('Status', '')).upper(),
                    'rows': int(row.get('RosterRows', 0) or 0),
                    'error': str(row.get('Error', '') or '').strip(),
                } for _, row in problem_rows.iterrows()],
            }

    def _leaders(df: pd.DataFrame, metric: str, label: str, count: int = 8) -> list[dict]:
        if df.empty or metric not in df.columns:
            return []
        working = df.copy()
        working[metric] = pd.to_numeric(working[metric], errors='coerce')
        working = working.dropna(subset=[metric])
        if working.empty:
            return []
        working = working.sort_values(metric, ascending=False).head(count)
        rows = []
        for _, row in working.iterrows():
            rows.append({
                'player': row.get('Player', ''),
                'team': row.get('CurrentTeam', ''),
                'position': row.get('Position', ''),
                'value': round(float(row.get(metric, 0) or 0), 1),
                'label': label,
                'transfer': bool(row.get('TransferFlag', False)),
                'last_team': row.get('LastSeasonTeam', ''),
            })
        return rows

    top_qbs = _leaders(
        master[master['Position'].fillna('').astype(str).str.upper().str.contains('QB', na=False)] if not master.empty else pd.DataFrame(),
        'CareerPassYds',
        'Career Pass Yds',
    )
    skill_df = pd.DataFrame()
    if not master.empty:
        skill_df = master.copy()
        skill_df['SkillYards'] = pd.to_numeric(skill_df.get('CareerRushYds'), errors='coerce').fillna(0) + pd.to_numeric(skill_df.get('CareerRecYds'), errors='coerce').fillna(0)
    top_skill = _leaders(skill_df, 'SkillYards', 'Career Skill Yds')

    defense_df = pd.DataFrame()
    if not master.empty:
        defense_df = master.copy()
        defense_df['DefenseImpact'] = (
            pd.to_numeric(defense_df.get('CareerTackles'), errors='coerce').fillna(0) +
            (pd.to_numeric(defense_df.get('CareerSacks'), errors='coerce').fillna(0) * 4) +
            (pd.to_numeric(defense_df.get('CareerDefInt'), errors='coerce').fillna(0) * 6)
        )
    top_defense = _leaders(defense_df, 'DefenseImpact', 'Defense Impact')

    top_returning_teams = []
    if not returning.empty:
        working = returning.copy()
        if 'ReturningProduction' in working.columns:
            working['ReturningProduction'] = pd.to_numeric(working['ReturningProduction'], errors='coerce')
        else:
            working['ReturningProduction'] = np.nan
        if 'Team' in working.columns:
            working = working.dropna(subset=['Team']).sort_values('ReturningProduction', ascending=False).head(10)
            for _, row in working.iterrows():
                top_returning_teams.append({
                    'team': row.get('Team', ''),
                    'conference': _clean_display_text(row.get('Conference', '')),
                    'value': round(float(row.get('ReturningProduction', 0) or 0), 1),
                    'passing': round(float(row.get('PassingUsage', 0) or 0), 1),
                    'rushing': round(float(row.get('RushingUsage', 0) or 0), 1),
                    'receiving': round(float(row.get('ReceivingUsage', 0) or 0), 1),
                })

    portal_moves = []
    if not portal.empty:
        working = portal.copy()
        working['Rating'] = pd.to_numeric(working.get('Rating'), errors='coerce')
        working['Stars'] = pd.to_numeric(working.get('Stars'), errors='coerce')
        available_sort_cols = [col for col in ['Rating', 'Stars'] if col in working.columns]
        if available_sort_cols:
            working = working.sort_values(available_sort_cols, ascending=False, na_position='last')
        working = working.head(10)
        for _, row in working.iterrows():
            portal_moves.append({
                'player': row.get('Player', ''),
                'position': row.get('Position', ''),
                'origin': row.get('OriginTeam', ''),
                'destination': row.get('DestinationTeam', ''),
                'rating': row.get('Rating', ''),
                'stars': row.get('Stars', ''),
            })

    team_rollups = []
    grouped = pd.DataFrame()
    if not master.empty:
        grouped = master.groupby('CurrentTeam', dropna=False).agg(
            players=('Player', 'count'),
            transfers=('TransferFlag', 'sum'),
            qbs=('Position', lambda s: int(s.fillna('').astype(str).str.upper().str.contains('QB', na=False).sum())),
            pass_yds=('CareerPassYds', 'sum'),
            rush_yds=('CareerRushYds', 'sum'),
            rec_yds=('CareerRecYds', 'sum'),
            tackles=('CareerTackles', 'sum'),
        ).reset_index()
        grouped = grouped.fillna(0)
        grouped['returning_offense'] = grouped['pass_yds'] + grouped['rush_yds'] + grouped['rec_yds']
        # Keep the FULL sorted frame: it feeds signal_rows -> the live game-line
        # matchup map, which must cover every team, not a top-N. The .head(18) here
        # was a display cap for team_rollups that doubled as the modeling universe,
        # so only 18 teams could ever be enriched. Cap the DISPLAY loop only.
        grouped = grouped.sort_values(['returning_offense', 'tackles'], ascending=False)
        for _, row in grouped.head(18).iterrows():
            team_rollups.append({
                'team': row.get('CurrentTeam', ''),
                'players': int(row.get('players', 0) or 0),
                'transfers': int(row.get('transfers', 0) or 0),
                'qbs': int(row.get('qbs', 0) or 0),
                'returning_offense': round(float(row.get('returning_offense', 0) or 0), 1),
                'tackles': round(float(row.get('tackles', 0) or 0), 1),
            })

    returning_map = pd.DataFrame()
    if not returning.empty and 'Team' in returning.columns:
        returning_map = returning.copy()
        if 'ReturningProduction' in returning_map.columns:
            returning_map['ReturningProduction'] = pd.to_numeric(returning_map['ReturningProduction'], errors='coerce').fillna(0)
        if 'PassingUsage' in returning_map.columns:
            returning_map['PassingUsage'] = pd.to_numeric(returning_map['PassingUsage'], errors='coerce').fillna(0)
        returning_map = returning_map[['Team', 'Conference', 'ReturningProduction', 'PassingUsage']].drop_duplicates(subset=['Team'], keep='first')

    portal_team = pd.DataFrame()
    if not portal.empty:
        portal_working = portal.copy()
        outgoing = (
            portal_working[portal_working['OriginTeam'].fillna('').astype(str).str.strip() != '']
            .groupby('OriginTeam').size().reset_index(name='PortalOut').rename(columns={'OriginTeam': 'Team'})
        )
        incoming = (
            portal_working[portal_working['DestinationTeam'].fillna('').astype(str).str.strip() != '']
            .groupby('DestinationTeam').size().reset_index(name='PortalIn').rename(columns={'DestinationTeam': 'Team'})
        )
        portal_team = outgoing.merge(incoming, on='Team', how='outer').fillna(0)
        portal_team['PortalIn'] = portal_team['PortalIn'].astype(int)
        portal_team['PortalOut'] = portal_team['PortalOut'].astype(int)
        portal_team['PortalNet'] = portal_team['PortalIn'] - portal_team['PortalOut']

    signal_rows = pd.DataFrame()
    if not grouped.empty:
        signal_rows = grouped.copy().rename(columns={'CurrentTeam': 'Team'})
        if not returning_map.empty:
            signal_rows = signal_rows.merge(returning_map, on='Team', how='left')
        else:
            signal_rows['Conference'] = ''
            signal_rows['ReturningProduction'] = np.nan
            signal_rows['PassingUsage'] = np.nan
        if not portal_team.empty:
            signal_rows = signal_rows.merge(portal_team, on='Team', how='left')
        else:
            signal_rows['PortalIn'] = 0
            signal_rows['PortalOut'] = 0
            signal_rows['PortalNet'] = 0
        for col in ['ReturningProduction', 'PassingUsage', 'PortalIn', 'PortalOut', 'PortalNet']:
            signal_rows[col] = pd.to_numeric(signal_rows.get(col), errors='coerce').fillna(0)
        signal_rows['QBContinuityFlag'] = (signal_rows['qbs'] > 0) & (signal_rows['pass_yds'] >= 1500)
        signal_rows['HighContinuityFlag'] = signal_rows['ReturningProduction'] >= 0.60
        signal_rows['PortalVolatilityFlag'] = signal_rows['PortalOut'] >= 12
        signal_rows['DefensiveSupportFlag'] = signal_rows['tackles'] >= signal_rows['tackles'].quantile(0.75) if len(signal_rows) > 3 else signal_rows['tackles'] > 0

    plain_english_cards = []
    if not signal_rows.empty:
        high_cont = signal_rows[signal_rows['HighContinuityFlag']]
        qbs_ready = signal_rows[signal_rows['QBContinuityFlag']]
        portal_volatile = signal_rows[signal_rows['PortalVolatilityFlag']].sort_values('PortalOut', ascending=False)
        defense_ready = signal_rows[signal_rows['DefensiveSupportFlag']].sort_values('tackles', ascending=False)

        if not high_cont.empty:
            top_team = high_cont.sort_values('ReturningProduction', ascending=False).iloc[0]
            plain_english_cards.append({
                'label': 'High Continuity',
                'title': f"{top_team['Team']} brings back a strong production base",
                'note': f"{float(top_team['ReturningProduction']):.0%} returning production makes early-season projection cleaner than average.",
            })
        else:
            plain_english_cards.append({
                'label': 'High Continuity',
                'title': 'Continuity looks mixed across the board',
                'note': 'Treat early-season reads carefully when returning production support is thin or uneven.',
            })

        if not portal_volatile.empty:
            top_team = portal_volatile.iloc[0]
            plain_english_cards.append({
                'label': 'Portal Volatility',
                'title': f"{top_team['Team']} shows heavy roster churn",
                'note': f"{int(top_team['PortalOut'])} portal exits make chemistry and role certainty harder to trust right away.",
            })
        else:
            plain_english_cards.append({
                'label': 'Portal Volatility',
                'title': 'Portal churn looks manageable right now',
                'note': 'No single team is flashing extreme outgoing portal volume from the current feed.',
            })

        if not qbs_ready.empty:
            top_team = qbs_ready.sort_values('pass_yds', ascending=False).iloc[0]
            plain_english_cards.append({
                'label': 'Returning QB Support',
                'title': f"{top_team['Team']} has proven QB continuity",
                'note': f"{round(float(top_team['pass_yds']), 0):.0f} returning pass yards is a strong early signal for offense stability.",
            })
        else:
            plain_english_cards.append({
                'label': 'Returning QB Support',
                'title': 'Quarterback continuity is shaky in places',
                'note': 'When the returning QB signal is weak, sides and totals deserve more caution until roles settle.',
            })

        if not defense_ready.empty:
            top_team = defense_ready.iloc[0]
            plain_english_cards.append({
                'label': 'Defensive Support',
                'title': f"{top_team['Team']} brings back real tackle volume",
                'note': f"{round(float(top_team['tackles']), 0):.0f} returning tackles suggests defensive retention can support unders or dog resistance.",
            })
        else:
            plain_english_cards.append({
                'label': 'Defensive Support',
                'title': 'Defensive retention is harder to trust broadly',
                'note': "Without clear returning defensive volume, don't overrate preseason defensive assumptions.",
            })

    # team_signals_all is the COMPLETE per-team signal set used to enrich the live
    # game-line board's matchup context. team_signals is the 12-team shortlist the
    # command-center UI displays. These were the same object, capped at .head(12),
    # so only 12 teams' games ever received roster/continuity context and every
    # other matchup quietly got none despite the data existing. Build the full set,
    # then slice for the UI.
    team_signals = []
    team_signals_all = []
    if not signal_rows.empty:
        signal_profiles = {}
        for _, row in signal_rows.iterrows():
            team = str(row.get('Team', '') or '').strip()
            if team:
                signal_profiles[team] = build_ncaaf_signal_profile(row)
        signal_rows = signal_rows.copy()
        signal_rows['SignalScore'] = signal_rows['Team'].map(lambda team: (signal_profiles.get(str(team), {}) or {}).get('score', 50.0))
        signal_rows['SignalTier'] = signal_rows['Team'].map(lambda team: (signal_profiles.get(str(team), {}) or {}).get('tier', 'mixed'))
        signal_sorted = signal_rows.sort_values(
            ['SignalScore', 'ReturningProduction', 'pass_yds', 'tackles'],
            ascending=[False, False, False, False],
        )
        for _, row in signal_sorted.iterrows():
            tags = []
            if bool(row.get('HighContinuityFlag', False)):
                tags.append('High continuity')
            if bool(row.get('QBContinuityFlag', False)):
                tags.append('Returning QB')
            if bool(row.get('DefensiveSupportFlag', False)):
                tags.append('Defensive support')
            if bool(row.get('PortalVolatilityFlag', False)):
                tags.append('Portal volatility')
            if int(row.get('PortalNet', 0)) >= 3:
                tags.append('Portal adds')
            profile = signal_profiles.get(str(row.get('Team', '') or '').strip(), {})
            team_signals_all.append({
                'team': row.get('Team', ''),
                'conference': _clean_display_text(row.get('Conference', '')),
                'returning_production': round(float(row.get('ReturningProduction', 0) or 0), 3),
                'portal_in': int(row.get('PortalIn', 0) or 0),
                'portal_out': int(row.get('PortalOut', 0) or 0),
                'tags': tags,
                'signal_score': profile.get('score', 50.0),
                'signal_tier': profile.get('tier', 'mixed'),
                'signal_badge': profile.get('badge', 'MIXED'),
                'signal_note': profile.get('note', ''),
                'verdict': profile.get('verdict', 'Balanced continuity read'),
            })
        team_signals = team_signals_all[:12]

    matchup_verdict_cards = []
    if not signal_rows.empty:
        stable_offense = signal_rows[signal_rows['HighContinuityFlag'] & signal_rows['QBContinuityFlag']].sort_values(['ReturningProduction', 'pass_yds'], ascending=False)
        if not stable_offense.empty:
            top_team = stable_offense.iloc[0]
            matchup_verdict_cards.append({
                'label': 'Stable Offense',
                'team': top_team.get('Team', ''),
                'title': f"{top_team.get('Team', '')} projects as a steadier offensive opponent",
                'note': f"{float(top_team.get('ReturningProduction', 0) or 0):.0%} returning production and proven QB continuity support cleaner side and total reads.",
            })

        volatile = signal_rows[signal_rows['PortalVolatilityFlag']].sort_values('PortalOut', ascending=False)
        if not volatile.empty:
            top_team = volatile.iloc[0]
            matchup_verdict_cards.append({
                'label': 'Volatility Risk',
                'team': top_team.get('Team', ''),
                'title': f"{top_team.get('Team', '')} looks more fragile in early-season matchup reads",
                'note': f"{int(top_team.get('PortalOut', 0) or 0)} outgoing portal moves can make chemistry and role confidence weaker than the market assumes.",
            })

        defense_anchor = signal_rows[signal_rows['DefensiveSupportFlag']].sort_values('tackles', ascending=False)
        if not defense_anchor.empty:
            top_team = defense_anchor.iloc[0]
            matchup_verdict_cards.append({
                'label': 'Defensive Support',
                'team': top_team.get('Team', ''),
                'title': f"{top_team.get('Team', '')} brings back enough defense to change the environment",
                'note': f"{round(float(top_team.get('tackles', 0) or 0), 0):.0f} returning tackles support under or dog-resistance reads more than a blank roster would.",
            })

        portal_adds = signal_rows[signal_rows['PortalNet'] >= 3].sort_values('PortalNet', ascending=False)
        if not portal_adds.empty:
            top_team = portal_adds.iloc[0]
            matchup_verdict_cards.append({
                'label': 'Portal Adds',
                'team': top_team.get('Team', ''),
                'title': f"{top_team.get('Team', '')} may be more dangerous than its old baseline",
                'note': f"A positive portal net of {int(top_team.get('PortalNet', 0) or 0)} says this roster added enough pieces to deserve a second look before fading it automatically.",
            })

    note = 'Current-season college football should start with rosters, portal churn, and returning production, then layer lines, totals, and matchup context on top.'
    if history.empty:
        note = 'Current rosters are ready, but player production history is still empty. Once last-season stats are added, this layer will start flagging returning production and transfer impact.'
    elif returning.empty and portal.empty:
        note = 'Current rosters and last-season player stats are loaded. Returning-production and portal layers can sharpen continuity and roster-churn reads even further.'
    elif confirmed_transfers == 0 and not portal.empty:
        note = 'Team-level portal churn is live, but player-level transfer tags are intentionally conservative until roster, portal, and last-season team data align cleanly enough to confirm moves.'

    return {
        'available': True,
        'state': 'ready' if not history.empty else 'partial',
        'note': note,
        'next_steps': next_steps if history.empty else [],
        'cards': cards,
        'position_cards': position_cards,
        'top_qbs': top_qbs,
        'top_skill': top_skill,
        'top_defense': top_defense,
        'team_rollups': team_rollups,
        'top_returning_teams': top_returning_teams,
        'portal_moves': portal_moves,
        'plain_english_cards': plain_english_cards,
        'team_signals': team_signals,
        'team_signals_all': team_signals_all,
        'coverage_summary': coverage_summary,
        'coverage_alert': coverage_alert,
        'matchup_verdict_cards': matchup_verdict_cards,
    }


def build_ncaaf_team_signal_map(team_signal_rows: list[dict], normalize_team_name: NormalizeTeamName) -> dict:
    signal_map = {}
    for row in team_signal_rows or []:
        team = normalize_team_name(row.get('team', ''))
        if not team:
            continue
        signal_map[team] = {
            'team': team,
            'conference': _clean_display_text(row.get('conference', '')),
            'tags': list(row.get('tags') or []),
            'verdict': str(row.get('verdict') or '').strip(),
            'returning_production': row.get('returning_production'),
            'portal_in': int(row.get('portal_in') or 0),
            'portal_out': int(row.get('portal_out') or 0),
            'signal_score': float(pd.to_numeric(row.get('signal_score'), errors='coerce') or 50.0),
            'signal_tier': str(row.get('signal_tier') or 'mixed').strip().lower(),
            'signal_badge': str(row.get('signal_badge') or 'MIXED').strip(),
            'signal_note': str(row.get('signal_note') or '').strip(),
        }
    return signal_map


def build_ncaaf_matchup_signal_context(
    away: str,
    home: str,
    *,
    method_key: str,
    signal_map: dict,
    normalize_team_name: NormalizeTeamName,
) -> dict:
    away_team = normalize_team_name(away)
    home_team = normalize_team_name(home)
    away_signal = signal_map.get(away_team, {})
    home_signal = signal_map.get(home_team, {})
    away_tags = list(away_signal.get('tags') or [])
    home_tags = list(home_signal.get('tags') or [])

    away_score = float(pd.to_numeric(away_signal.get('signal_score'), errors='coerce') or 50.0)
    home_score = float(pd.to_numeric(home_signal.get('signal_score'), errors='coerce') or 50.0)
    score_delta = round((away_score - home_score) / 6.0, 1)
    if str(method_key).strip().lower() == 'totals':
        defensive_bonus = 0.0
        if 'Defensive support' in away_tags:
            defensive_bonus += 0.8
        if 'Defensive support' in home_tags:
            defensive_bonus += 0.8
        if 'Portal volatility' in away_tags or 'Portal volatility' in home_tags:
            defensive_bonus -= 0.6
        score_delta = round(score_delta + defensive_bonus, 1)

    verdict = ''
    away_tier = str(away_signal.get('signal_tier') or 'mixed').strip().lower()
    home_tier = str(home_signal.get('signal_tier') or 'mixed').strip().lower()
    if abs(away_score - home_score) >= 12:
        edge_team = away_team if away_score > home_score else home_team
        weak_team = home_team if away_score > home_score else away_team
        verdict = f'{edge_team} brings the cleaner continuity profile while {weak_team} needs more proof early.'
    elif away_tier == 'stable' and home_tier == 'volatile':
        verdict = f'{away_team} looks steadier while {home_team} carries more churn risk.'
    elif home_tier == 'stable' and away_tier == 'volatile':
        verdict = f'{home_team} looks steadier while {away_team} carries more churn risk.'
    elif away_tier == 'stable' and home_tier == 'stable':
        verdict = 'Both teams bring stable continuity support into this matchup.'
    elif 'Returning QB' in away_tags and 'Returning QB' in home_tags:
        verdict = 'Both offenses bring quarterback continuity into this matchup.'
    elif 'Defensive support' in away_tags and 'Defensive support' in home_tags:
        verdict = 'Both teams bring real returning defensive support into the game environment.'
    elif away_tier == 'volatile' or home_tier == 'volatile':
        volatile_team = away_team if 'Portal volatility' in away_tags else home_team
        verdict = f'{volatile_team} shows enough portal churn to add uncertainty to the early read.'
    elif away_tags or home_tags:
        verdict = 'Continuity signals support the market read more than a blank roster environment would.'

    return {
        'away': away_team,
        'home': home_team,
        'away_signal': away_signal,
        'home_signal': home_signal,
        'away_tags': away_tags,
        'home_tags': home_tags,
        'away_score': away_score,
        'home_score': home_score,
        'score_delta': score_delta,
        'verdict': verdict,
    }
