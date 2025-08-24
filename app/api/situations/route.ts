import { NextRequest, NextResponse } from "next/server";

// Use public anon key if available; fall back to service role on the server.
const SUPABASE_URL =
  process.env.NEXT_PUBLIC_SUPABASE_URL ?? "";
const SUPABASE_KEY =
  process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY ??
  process.env.SUPABASE_SERVICE_ROLE_KEY ?? "";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

function q(params: Record<string, string | undefined>) {
  const ps = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) if (v) ps.set(k, v);
  return ps;
}

export async function GET(req: NextRequest) {
  try {
    const url = new URL(req.url);

    // Get filter parameters (with better naming)
    const position = url.searchParams.get("position") ?? undefined;
    const team = url.searchParams.get("team") ?? undefined;
    const defenseTier = url.searchParams.get("defense_tier") ?? undefined; // Fixed parameter name
    const year = url.searchParams.get("year") ?? "2024"; // Default to 2024
    const week = url.searchParams.get("week") ?? undefined;
    const month = url.searchParams.get("month") ?? undefined;
    const opponent = url.searchParams.get("opponent") ?? undefined;
    const gameResult = url.searchParams.get("game_result") ?? undefined;
    const timeOfDay = url.searchParams.get("time_of_day") ?? undefined;
    const surface = url.searchParams.get("surface") ?? undefined;
    const temperature = url.searchParams.get("temperature") ?? undefined;
    const division = url.searchParams.get("division") ?? undefined;
    const conference = url.searchParams.get("conference") ?? undefined;
    const injuryStatus = url.searchParams.get("injury_status") ?? undefined;
    const experience = url.searchParams.get("experience") ?? undefined;
    const minYards = url.searchParams.get("min_yards") ?? undefined;
    const maxYards = url.searchParams.get("max_yards") ?? undefined;
    const minGames = url.searchParams.get("min_games") ?? undefined;
    const limit = url.searchParams.get("limit") ?? "100"; // Increased default limit

    console.log('Query params:', { 
      position, team, defenseTier, year, week, month, opponent, 
      gameResult, timeOfDay, surface, temperature, division, 
      conference, injuryStatus, experience, minYards, maxYards, minGames 
    });

    // Check if we want aggregated season totals or situational breakdowns
    const aggregate = url.searchParams.get("aggregate") !== "false"; // Default to aggregated

    let query: string;
    let supabaseUrl: string;

    if (aggregate) {
      // AGGREGATED QUERY - Sum across all defense tiers for season totals
      const conditions = [];
      
      if (position) conditions.push(`position.eq.${position}`);
      if (team) conditions.push(`team_abbr.eq.${team}`);
      if (year) conditions.push(`season.eq.${year}`);
      // Note: Other filters would need additional data joins for full implementation
      
      const whereClause = conditions.length > 0 ? `&${conditions.join('&')}` : '';
      
      // Use RPC function for aggregation (you'll need to create this in Supabase)
      supabaseUrl = `${SUPABASE_URL}/rest/v1/rpc/get_aggregated_player_stats`;
      query = q({
        position_filter: position,
        team_filter: team,
        season_filter: year,
        defense_tier_filter: defenseTier,
        min_yards_filter: minYards,
        max_yards_filter: maxYards,
        min_games_filter: minGames,
        limit_count: limit
      }).toString();
      
    } else {
      // SITUATIONAL QUERY - Keep current breakdown by defense tier
      const params = q({
        select: [
          "player_id",
          "full_name",
          "position", 
          "season",
          "category",
          "def_tier",
          "team_abbr",
          "total_yards",
          "games",
          "per_game"
        ].join(","),
        ...(position ? { position: `eq.${position}` } : {}),
        ...(team ? { team_abbr: `eq.${team}` } : {}),
        ...(defenseTier ? { def_tier: `eq.${defenseTier}` } : {}),
        ...(year ? { season: `eq.${year}` } : {}),
        category: "eq.pass", // Default to passing stats
        order: "total_yards.desc.nullslast",
        limit,
      });

      supabaseUrl = `${SUPABASE_URL}/rest/v1/v_situational_leaderboard`;
      query = params.toString();
    }

    console.log('Final query:', query);
    console.log('Supabase URL:', supabaseUrl);

    const resp = await fetch(`${supabaseUrl}?${query}`, {
      headers: {
        apikey: SUPABASE_KEY,
        Authorization: `Bearer ${SUPABASE_KEY}`,
        "Content-Type": "application/json",
      },
      cache: "no-store",
    });

    if (!resp.ok) {
      const text = await resp.text();
      console.error('Supabase error:', text);
      return NextResponse.json(
        { error: `supabase error ${resp.status}`, details: text },
        { status: 500 }
      );
    }

    const rawRows = await resp.json();
    console.log('Raw DB response (first 2):', rawRows.slice(0, 2));
    
    let processedRows;

    if (aggregate && Array.isArray(rawRows)) {
      // If using the direct view (fallback), aggregate in code
      const aggregated = new Map();
      
      rawRows.forEach((row: any) => {
        const key = `${row.full_name}-${row.team_abbr}-${row.season}`;
        if (aggregated.has(key)) {
          const existing = aggregated.get(key);
          existing.total_yards += parseInt(row.total_yards) || 0;
          existing.games = Math.max(existing.games, row.games || 1);
        } else {
          aggregated.set(key, {
            player_id: row.player_id,
            full_name: row.full_name,
            position: row.position,
            team_abbr: row.team_abbr,
            season: row.season,
            total_yards: parseInt(row.total_yards) || 0,
            games: row.games || 1,
            def_tier: 'aggregated'
          });
        }
      });
      
      processedRows = Array.from(aggregated.values())
        .map(row => ({
          ...row,
          per_game: row.games > 0 ? (row.total_yards / row.games).toFixed(1) : 0
        }))
        .sort((a, b) => b.total_yards - a.total_yards)
        .slice(0, parseInt(limit));
        
    } else {
      processedRows = rawRows;
    }
    
    // Transform data for frontend compatibility
    const rows = processedRows.map((row: any) => ({
      player_id: row.player_id,
      player_name: row.full_name,  // ✅ FIXED: Map full_name to player_name
      position: row.position,
      team: row.team_abbr,         // ✅ FIXED: Map team_abbr to team
      total_yards: parseInt(row.total_yards) || 0,
      games: row.games || 1,
      per_game: parseFloat(row.per_game) || 0,
      defense_tier: row.def_tier,
      category: row.category,
      season: row.season,
      
      // Legacy compatibility
      total: parseInt(row.total_yards) || 0,
      avg_per_attempt: parseFloat(row.per_game) || 0,
      id: row.player_id
    }));

    console.log('Transformed response (first 2):', rows.slice(0, 2));

    return NextResponse.json({ rows });
  } catch (err: any) {
    console.error('API Error:', err);
    return NextResponse.json(
      { error: "internal", details: String(err?.message ?? err) },
      { status: 500 }
    );
  }
}
