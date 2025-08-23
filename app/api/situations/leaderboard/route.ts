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
    
    // Build the query - use your actual table/view name
    let query = supabase
      .from('v_situational_leaderboard_rows') // Or whatever your table/view is called
      .select('*');
    
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
    
    // Order by total_yards descending to show best performers first
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

    // Transform data to match frontend expectations
    const transformedRows = rawRows?.map(row => ({
      id: row.player_id,
      player_name: row.full_name,
      position: row.position,
      team: row.team_abbr,                           // ✅ Now we have teams!
      total: parseInt(row.total_yards) || 0,         // ✅ Convert string to number
      per_game: parseFloat(row.per_game) || 0,       // ✅ Proper per game stats
      games: row.games || 1,
      def_tier: row.def_tier,
      category: row.category,
      season: row.season,
      
      // Map to expected frontend field names
      total_yards: parseInt(row.total_yards) || 0,
      avg_per_attempt: parseFloat(row.per_game) || 0,
      attempts: row.games, // Using games as attempts for now
      
      // Add default values for missing situational data
      home_away: 'HOME', // Add when you have this data
      prime_time: false,  // Add when you have this data
      weather_condition: null,
      situation: `${row.category.toUpperCase()}_VS_${row.def_tier.toUpperCase()}`
    })) || [];

    // Group and deduplicate similar entries for cleaner display
    const deduplicatedRows = transformedRows.reduce((acc, current) => {
      const existingIndex = acc.findIndex(item => 
        item.player_name === current.player_name && 
        item.def_tier === current.def_tier &&
        item.category === current.category
      );
      
      if (existingIndex >= 0) {
        // Combine stats for same player vs same defense tier
        acc[existingIndex].total += current.total;
        acc[existingIndex].games += current.games;
        acc[existingIndex].per_game = acc[existingIndex].total / acc[existingIndex].games;
      } else {
        acc.push(current);
      }
      
      return acc;
    }, [] as any[]);

    console.log(`Returning ${deduplicatedRows.length} transformed rows`); // Debug log

    return NextResponse.json({
      data: deduplicatedRows,
      total: deduplicatedRows.length,
      limit: filters.limit,
      offset: filters.offset,
      filters: filters,
      // Include metadata for debugging
      metadata: {
        raw_count: rawRows?.length || 0,
        transformed_count: transformedRows.length,
        deduplicated_count: deduplicatedRows.length
      }
    });

  } catch (error) {
    console.error('API route error:', error);
    return NextResponse.json(
      { 
        error: 'Internal server error', 
        message: error instanceof Error ? error.message : 'Unknown error' 
      },
      { status: 500 }
    );
  }
}
