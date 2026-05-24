from __future__ import annotations

import pandas as pd


def collect_live_prop_rows(
    *,
    props_df,
    gamelogs,
    current_team_map,
    sample_mode,
    playoff_gamelogs,
    postseason_only,
    team_filter,
    team_game_lookup,
    upcoming,
    player_advanced,
    player_tracking,
    player_snapshot,
    active_boosts,
    return_impacts,
    props_market_groups,
    min_sample_games,
    date_filter,
    direction_filter,
    min_confidence=None,
    deps,
):
    rows = []
    if props_df.empty or gamelogs.empty:
        return rows

    series_context_cache = {}
    defense_cache = {}

    get_player_analysis_logs = deps['get_player_analysis_logs']
    team_in_filter = deps['team_in_filter']
    calculate_over_under_rates = deps['calculate_over_under_rates']
    calculate_streak = deps['calculate_streak']
    calculate_under_streak = deps['calculate_under_streak']
    calculate_trend = deps['calculate_trend']
    get_player_projection_context = deps['get_player_projection_context']
    get_player_tracking_context = deps['get_player_tracking_context']
    get_postseason_matchup_context = deps['get_postseason_matchup_context']
    get_playoff_defense_context = deps['get_playoff_defense_context']
    normalize_team_for_filter = deps['normalize_team_for_filter']
    score_prop = deps['score_prop']
    get_prop_market_context = deps['get_prop_market_context']
    build_prop_multi_book_context = deps['build_prop_multi_book_context']
    recalibrate_live_market_confidence = deps['recalibrate_live_market_confidence']
    get_grade = deps['get_grade']
    build_lock_reason = deps['build_lock_reason']
    build_public_trend_note = deps['build_public_trend_note']
    build_core_baseline_fields = deps['build_core_baseline_fields']
    build_method_supports = deps['build_method_supports']
    apply_live_method_market_guardrails = deps['apply_live_method_market_guardrails']
    floor_multipliers = deps['FLOOR_MULTIPLIERS']
    postseason_teams = deps['POSTSEASON_TEAMS']

    for _, prop in props_df.iterrows():
        player, stat, line = prop.get('Player', ''), prop.get('Stat', ''), prop.get('Line', 0)
        if pd.isna(player) or pd.isna(stat) or pd.isna(line):
            continue

        pl, player_context = get_player_analysis_logs(
            player,
            gamelogs,
            current_team_map,
            sample_mode,
            postseason_logs=playoff_gamelogs,
            postseason_only=postseason_only,
        )
        if len(pl) < min_sample_games or stat not in pl.columns:
            continue

        team = player_context.get('current_team') or current_team_map.get(player, pl.iloc[0].get('Team', ''))
        if not team_in_filter(team, team_filter):
            continue
        if postseason_only and team not in team_game_lookup:
            continue

        scheduled_game = team_game_lookup.get(team, {})
        plays_today = scheduled_game.get('bucket') == 'today'
        plays_tomorrow = scheduled_game.get('bucket') == 'tomorrow'
        plays_upcoming = scheduled_game.get('bucket') == 'upcoming'

        if date_filter == 'today' and not plays_today:
            continue
        if date_filter == 'tomorrow' and not plays_tomorrow:
            continue
        if date_filter == 'upcoming' and not (plays_today or plays_tomorrow or plays_upcoming):
            continue

        projection_context = get_player_projection_context(
            player, team, stat, pl, player_advanced, active_boosts, player_snapshot, return_impacts
        )
        tracking_context = get_player_tracking_context(player, player_tracking, player_advanced)

        over_streak = calculate_streak(pl, stat, line)
        under_streak = calculate_under_streak(pl, stat, line)
        trend, _ = calculate_trend(pl, stat)
        current_run_side = 'flat'
        current_streak = 0
        if over_streak > 0:
            current_run_side = 'over'
            current_streak = int(over_streak)
        elif under_streak > 0:
            current_run_side = 'under'
            current_streak = int(under_streak)

        opponent = scheduled_game.get('opponent_abbr') or normalize_team_for_filter(scheduled_game.get('opponent'))
        opponent_display = scheduled_game.get('opponent_display') or scheduled_game.get('opponent') or opponent

        valid_vs_opponent = pd.DataFrame()
        matchup_ou_rates = {'over': None, 'under': None}
        if opponent and 'Opp' in pl.columns:
            valid_vs_opponent = pl[
                pl['Opp'].astype(str).apply(normalize_team_for_filter) == normalize_team_for_filter(opponent)
            ]
            if not valid_vs_opponent.empty:
                matchup_ou_rates = calculate_over_under_rates(valid_vs_opponent, stat, line)

        score = score_prop(
            pl,
            stat,
            line,
            player=player,
            team=team,
            opponent=opponent,
            gamelogs=gamelogs,
            projection_context=projection_context,
            scheduled_game=scheduled_game,
            postseason_only=postseason_only,
            series_context=get_postseason_matchup_context(gamelogs, team, opponent, series_context_cache) if postseason_only else None,
            defense_context=get_playoff_defense_context(gamelogs, opponent, stat, defense_cache, postseason_teams) if postseason_only else None,
        )

        avg = score['avg']
        ou_rates = score['ou_rates']
        game_environment = score['game_environment']
        playoff_adjustments = score['playoff_adjustments']
        core_baseline = score['core_baseline']
        volatility_context = score.get('volatility_context', {}) or {}
        best_play = score['best_play']
        combined_situations = score['combined_situations']

        if min_confidence is not None and float(best_play.get('confidence', 0) or 0) < float(min_confidence):
            continue
        if direction_filter == 'over' and best_play['direction'] != 'OVER':
            continue
        if direction_filter == 'under' and best_play['direction'] != 'UNDER':
            continue

        game_day = scheduled_game.get('label', '')
        model_prob = max(0.01, min(best_play['confidence'], 99.0)) / 100
        market_context = get_prop_market_context(prop, best_play['direction'], model_prob)
        multi_book_context = build_prop_multi_book_context(prop, best_play['direction'], props_market_groups)
        calibration = recalibrate_live_market_confidence(best_play['confidence'], multi_book_context)
        calibrated_confidence = calibration['confidence']
        line_low = multi_book_context.get('line_low')
        line_high = multi_book_context.get('line_high')
        range_gap = None
        if line_low is not None and line_high is not None:
            try:
                range_gap = round(float(line_high) - float(line_low), 1)
            except Exception:
                range_gap = None
        floor_line = round(float(avg) * floor_multipliers.get(str(stat).upper(), 0.75) * 2) / 2 if avg is not None else None
        if floor_line is not None and floor_line < 0.5:
            floor_line = 0.5

        row = {
            'player': player,
            'team': team,
            'stat': stat,
            'line': line,
            'avg': avg,
            'over_rate': ou_rates['over'],
            'under_rate': ou_rates['under'],
            'over_streak': over_streak,
            'under_streak': under_streak,
            'current_streak': current_streak,
            'current_run_side': current_run_side,
            'trend': trend,
            'direction': best_play['direction'],
            'confidence': calibrated_confidence,
            'raw_confidence': calibration['raw_confidence'],
            'is_lock': bool(best_play['is_lock'] and calibrated_confidence >= 80),
            'grade': get_grade(calibrated_confidence),
            'plays_today': plays_today,
            'plays_tomorrow': plays_tomorrow,
            'game_day': game_day,
            'situations': combined_situations,
            'market_calibration_note': calibration['note'],
            'market_calibration_tags': calibration['tags'],
            'weighted_over_rate': playoff_adjustments['weighted_over'],
            'weighted_under_rate': playoff_adjustments['weighted_under'],
            'live_line_over_rate': ou_rates['over'],
            'live_line_under_rate': ou_rates['under'],
            'live_line_games': int(len(pl)),
            'matchup_games': int(len(valid_vs_opponent)),
            'matchup_over_rate': matchup_ou_rates.get('over'),
            'matchup_under_rate': matchup_ou_rates.get('under'),
            'opponent': opponent_display,
            'floor_line': floor_line,
            'matchup': scheduled_game.get('matchup', ''),
            'projected_minutes': projection_context.get('projected_minutes'),
            'usage_pct': projection_context.get('usage_pct'),
            'return_impact_pct': projection_context.get('return_impact_pct'),
            'return_player': projection_context.get('return_player'),
            'return_status': projection_context.get('return_status'),
            'ts_pct': tracking_context.get('ts_pct'),
            'ast_pct': tracking_context.get('ast_pct'),
            'touches': tracking_context.get('touches'),
            'drives': tracking_context.get('drives'),
            'avg_speed': tracking_context.get('avg_speed'),
            'distance_miles': tracking_context.get('distance_miles'),
            'off_rating': tracking_context.get('off_rating'),
            'def_rating': tracking_context.get('def_rating'),
            'net_rating': tracking_context.get('net_rating'),
            'role_label': projection_context.get('role_label'),
            'snapshot_consistency': projection_context.get('snapshot_consistency'),
            'snapshot_tier': projection_context.get('snapshot_tier'),
            'snapshot_load_label': projection_context.get('snapshot_load_label'),
            'snapshot_signal': projection_context.get('snapshot_signal'),
            'snapshot_stat_trend': projection_context.get('snapshot_stat_trend'),
            'game_total': game_environment.get('game_total'),
            'team_spread': game_environment.get('team_spread'),
            'game_environment': game_environment.get('game_environment'),
            'game_market_summary': scheduled_game.get('market_summary', ''),
            'sample_label': player_context.get('sample_label'),
            'is_multi_team': player_context.get('is_multi_team'),
            'team_history': ' / '.join(player_context.get('teams', [])),
            'weight_profile': playoff_adjustments.get('weight_profile'),
            'component_weights': playoff_adjustments.get('component_weights', {}),
            'series_weight': playoff_adjustments.get('series_weight'),
            'series_game_number': playoff_adjustments.get('series_game_number'),
            'volatility_flag': volatility_context.get('flag', 'STABLE'),
            'volatility_note': volatility_context.get('note', ''),
            'volatility_penalty': volatility_context.get('penalty', 0.0),
            'volatility_minutes_delta': volatility_context.get('minutes_delta'),
            'volatility_stat_delta': volatility_context.get('stat_delta'),
            'market_price': market_context['market_price'],
            'implied_prob': market_context['implied_prob'],
            'model_prob': market_context['model_prob'],
            'market_gap_pct': market_context['market_gap_pct'],
            'market_view': market_context['market_view'],
            'fair_price': market_context['fair_price'],
            'ev_pct': market_context['ev_pct'],
            'edge_pct': market_context['edge_pct'],
            'book': market_context['book'],
            'book_count': multi_book_context['book_count'],
            'books': multi_book_context['books'],
            'draftkings_line': multi_book_context['draftkings_line'],
            'vegas_line': multi_book_context['vegas_line'],
            'line_low': multi_book_context['line_low'],
            'line_high': multi_book_context['line_high'],
            'range_gap': range_gap,
            'best_book': multi_book_context['best_book'],
            'book_comparison_note': multi_book_context['book_comparison_note'],
            'current_line': market_context['current_line'],
            'open_line': market_context['open_line'],
            'close_line': market_context['close_line'],
            'line_move': market_context['line_move'],
            'clv_line': market_context['clv_line'],
            'clv_price_pct': market_context['clv_price_pct'],
            'lock_reason': build_lock_reason(best_play, playoff_adjustments['weighted_over'], playoff_adjustments['weighted_under']),
            'public_trend_note': build_public_trend_note(pl, stat, line, best_play['direction'], postseason_only=postseason_only),
            'soft_boost_cap': score['soft_boost_cap'],
            'raw_over_boost': score['raw_over_boost'],
            'raw_under_boost': score['raw_under_boost'],
            'capped_over_boost': score['capped_over_boost'],
            'capped_under_boost': score['capped_under_boost'],
            'hard_signal_note': best_play.get('hard_signal_note', ''),
            'hard_signal_ceiling': best_play.get('hard_signal_ceiling', ''),
            **build_core_baseline_fields(stat, best_play['direction'], core_baseline, line, projection_context),
        }
        row['method_supports'] = build_method_supports(row)
        row = apply_live_method_market_guardrails(row)
        rows.append(row)

    return rows
