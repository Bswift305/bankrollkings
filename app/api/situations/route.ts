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

    const position   = url.searchParams.get("position") ?? undefined;    // e.g. RB | WR | QB | TE
    const category   = url.searchParams.get("category") ?? undefined;    // 'rush' | 'pass'
    const defTier    = url.searchParams.get("defTier") ?? undefined;     // 'top10' | 'mid' | 'bottom10'
    const seasonFrom = url.searchParams.get("seasonFrom") ?? undefined;  // e.g. '2023'
    const seasonTo   = url.searchParams.get("seasonTo") ?? undefined;    // e.g. '2025'
    const limit      = url.searchParams.get("limit") ?? "25";

    console.log('Query params:', { position, category, defTier, seasonFrom, seasonTo });

    // Build PostgREST query against the view
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
      ...(position   ? { position:   `eq.${position}` }   : {}),
      ...(category   ? { category:   `eq.${category}` }   : {}),
      ...(defTier    ? { def_tier:   `eq.${defTier}` }    : {}),
      ...(seasonFrom ? { season:     `gte.${seasonFrom}` } : {}),
      ...(seasonTo   ? { "season2":  `lte.${seasonTo}` }   : {}), // temp key; we'll replace below
      order: "per_game.desc.nullslast",
      limit,
    });

    // PostgREST doesn't support duplicate 'season' keys via URLSearchParams,
    // so stitch manually for season range:
    let query = params.toString().replace("season2=", "season=");

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
    console.log('Raw DB response (first 2):', rawRows.slice(0, 2));
    
    // ✅ FIXED: Transform data with ALL fields including team
    const rows = rawRows.map((row: any) => ({
      player_id: row.player_id,
      full_name: row.full_name,
      position: row.position,
      team: row.team_abbr,                        // ✅ NOW INCLUDES TEAM!
      total: parseInt(row.total_yards) || 0,      // ✅ Convert string to number
      per_game: parseFloat(row.per_game) || 0,    // ✅ Convert string to number
      games: row.games || 1,
      def_tier: row.def_tier,
      category: row.category,
      season: row.season,
      
      // Additional compatibility fields
      player_name: row.full_name,
      total_yards: parseInt(row.total_yards) || 0,
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
