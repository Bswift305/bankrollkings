import { NextRequest, NextResponse } from 'next/server';
import { createClient } from '@/lib/supabase/server';

export async function GET(request: NextRequest) {
  try {
    const { searchParams } = new URL(request.url);
    
    // Map frontend parameters to backend expectations
    const paramMapping = {
      defCat: searchParams.get('defCat') || searchParams.get('category'),
      tier: searchParams.get('tier') || searchParams.get('defTier'),
      limit: parseInt(searchParams.get('limit') || '25'),
      offset: parseInt(searchParams.get('offset') || '0')
    };

    const supabase = createClient();
    
    // Build query with mapped parameters
    let query = supabase
      .from('situations_leaderboard')
      .select('*');
    
    if (paramMapping.defCat) {
      query = query.eq('category', paramMapping.defCat);
    }
    
    if (paramMapping.tier) {
      query = query.eq('def_tier', paramMapping.tier);
    }
    
    const { data: rawRows, error } = await query
      .range(paramMapping.offset, paramMapping.offset + paramMapping.limit - 1)
      .order('created_at', { ascending: false });

    if (error) {
      console.error('Database query error:', error);
      return NextResponse.json(
        { error: 'Failed to fetch leaderboard data' },
        { status: 500 }
      );
    }

    // Transform data structure to match frontend expectations
    const transformedRows = rawRows?.map(row => ({
      ...row,
      total: row.total_yards, // Map API field to frontend expectation
      // Add any other field mappings needed
    })) || [];

    return NextResponse.json({
      data: transformedRows,
      total: transformedRows.length,
      limit: paramMapping.limit,
      offset: paramMapping.offset
    });

  } catch (error) {
    console.error('API route error:', error);
    return NextResponse.json(
      { error: 'Internal server error' },
      { status: 500 }
    );
  }
}
