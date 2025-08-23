import { NextRequest, NextResponse } from 'next/server';
import { createServerSupabase } from '@/lib/supabase/server';

export async function GET(request: NextRequest) {
  try {
    const { searchParams } = new URL(request.url);
    
    // Map frontend parameters to database fields
    const filters = {
      position: searchParams.get('position') || searchParams.get('defCat'),
      category: searchParams.get('category') || 'pass', // Default to pass instead of rush
      def_tier: searchParams.get('tier') || searchParams.get('defTier'),
      season: searchParams.get('season'),
      team: searchParams.get('team'),
      limit: parseInt(searchParams.get('limit') || '50'),
      offset: parseInt(searchParams.get('offset') || '0')
    };

    console.log('API Filters:', filters); // Debug log

    const supabase = createServerSupabase();
    
    // Build the query - use your aggregated view
    let query = supabase
      .from('v_situational_leaderboard_rows')
      .select(`
        player_id,
        full_name,
        position,
        season,
        category,
        def_tier,
        team_abbr,
        total_yards,
        games,
        per_game
      `);
    
    // Apply filters
    if (filters.position) {
      query = query.eq('position', filters.position);
    }
    
    if (filters.category) {
      query = query.eq('category', filters.category);
    }
    
    if (filters.def_tier) {
      query = query.eq('def_tier', filters.def_tier);
    }
    
    if (filters.season) {
      query = query.eq('season', parseInt(filters.season));
    }
    
    if (filters.team) {
      query = query.eq('team_abbr', filters.team);
    }
    
    // Order by total_yards descending, but handle string conversion
    query = query
      .order('total_yards', { ascending: false })
      .range(filters.offset, filters.offset + filters.limit - 1);

    const { data: rawRows, error } = await query;

    if (error) {
      console.error('Database query error:', error);
      return NextResponse.json(
        { error: 'Failed to fetch leaderboard data', details: error.message },
        { status: 500 }
      );
    }

    console.log('Raw rows from DB:', rawRows?.slice(0, 3)); // Debug: show first 3 rows

    // Transform data to match frontend expectations - CRITICAL FIX HERE
    const transformedRows = rawRows?.map((row, index) => {
      // Convert string numbers to actual numbers
      const totalYards = row.total_yards ? parseInt(row.total_yards.toString()) : 0;
      const gamesPlayed = row.games ? parseInt(row.games.toString()) : 1;
      const perGameAvg = row.per_game ? parseFloat(row.per_game.toString()) : 0;

      return {
        id: row.player_id || `${row.full_name}-${index}`,
        player_name: row.full_name || 'Unknown Player',
        position: row.position || 'N/A',
        team: row.team_abbr || 'N/A',                    // ✅ This should now show!
        total: totalYards,                               // ✅ This should now show real numbers!
        per_game: perGameAvg,
        games: gamesPlayed,
        def_tier: row.def_tier || 'unknown',
        category: row.category || 'unknown',
        season: row.season || 2024,
        
        // Legacy field mappings for backward compatibility
        total_yards: totalYards,
        avg_per_attempt: perGameAvg,
        attempts: gamesPlayed,
        
        // Default values for missing data
        home_away: 'HOME' as 'HOME' | 'AWAY',
        prime_time: false,
        weather_condition: null,
        situation: `${(row.category || 'unknown').toUpperCase()}_VS_${(row.def_tier || 'unknown').toUpperCase()}`
      };
    }) || [];

    console.log('Transformed rows:', transformedRows?.slice(0, 3)); // Debug: show transformed data

    // Remove the deduplication for now - let's see raw data first
    // We can add smart grouping later once we confirm data is flowing

    return NextResponse.json({
      data: transformedRows,
      total: transformedRows.length,
      limit: filters.limit,
      offset: filters.offset,
      filters: filters,
      // Enhanced debugging metadata
      metadata: {
        raw_count: rawRows?.length || 0,
        transformed_count: transformedRows.length,
        sample_raw_row: rawRows?.[0] || null,
        sample_transformed_row: transformedRows?.[0] || null
      }
    });

  } catch (error) {
    console.error('API route error:', error);
    return NextResponse.json(
      { 
        error: 'Internal server error', 
        message: error instanceof Error ? error.message : 'Unknown error',
        stack: error instanceof Error ? error.stack : 'No stack trace'
      },
      { status: 500 }
    );
  }
}
