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

    const position = url.searchParams.get("position") ?? undefined;
    const team = url.searchParams.get("team") ?? undefined;
    const defenseTier = url.searchParams.get("defense_tier") ?? undefined;
    const year = url.searchParams.get("year") ?? "2024";
    const limit = url.searchParams.get("limit") ?? "200"; // Increased to 200!

    console.log('Query params:', { position, team, defenseTier, year, limit });

    // Build PostgREST query against the view - KEEP IT SIMPLE
    const sel = [
      "player_id",
      "full_name",
      "position",
      "season",
      "category",
      "def_tier",
      "team_abbr",
      "total_yards",
      "games",
      "per_game",
    ].join(",");

    const params = q({
      select: sel,
      ...(position ? { position: `eq.${position}` } : {}),
      ...(team ? { team_abbr: `eq.${team}` } : {}),
      ...(defenseTier ? { def_tier: `eq.${defenseTier}` } : {}),
      season: `eq.${year}`, // Always filter by year
      category: "eq.pass", // Default to passing stats
      order: "total_yards.desc.nullslast",
      limit,
    });

    const query = params.toString();
    console.log('Final query:', query);

    const resp = await fetch(
      `${SUPABASE_URL}/rest/v1/v_situational_leaderboard?${query}`,
      {
        headers: {
          apikey: SUPABASE_KEY,
          Authorization: `Bearer ${SUPABASE_KEY}`,
          "Content-Type": "application/json",
        },
        cache: "no-store",
      }
    );

    if (!resp.ok) {
      const text = await resp.text();
      console.error('Supabase error:', text);
      return NextResponse.json(
        { error: `supabase error ${resp.status}`, details: text },
        { status: 500 }
      );
    }

    const rawRows = await resp.json();
    console.log('Raw DB response count:', rawRows.length);
    console.log('First 2 rows:', rawRows.slice(0, 2));
    
    // Simple transformation - just map the column names
    const rows = rawRows.map((row: any) => ({
      player_id: row.player_id,
      player_name: row.full_name,      // ✅ Map full_name to player_name
      position: row.position,
      team: row.team_abbr,             // ✅ Map team_abbr to team  
      total_yards: parseInt(row.total_yards) || 0,
      games: row.games || 1,
      per_game: parseFloat(row.per_game) || 0,
      defense_tier: row.def_tier,
      category: row.category,
      season: row.season,
      
      // Additional compatibility
      total: parseInt(row.total_yards) || 0,
      avg_per_attempt: parseFloat(row.per_game) || 0,
      id: row.player_id
    }));

    console.log('Transformed response count:', rows.length);

    return NextResponse.json({ rows });
  } catch (err: any) {
    console.error('API Error:', err);
    return NextResponse.json(
      { error: "internal", details: String(err?.message ?? err) },
      { status: 500 }
    );
  }
}
