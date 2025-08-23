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
      return NextResponse.json(
        { error: `supabase error ${resp.status}`, details: text },
        { status: 500 }
      );
    }

    const rawRows = await resp.json();
    
    // ✅ FIXED: Transform data to match frontend expectations
    const rows = rawRows.map((row: any) => ({
      player_id: row.player_id,
      full_name: row.full_name,
      total: row.total_yards,  // Map total_yards to total
      per_game: row.per_game,
      games: row.games,
    }));

    return NextResponse.json({ rows });
  } catch (err: any) {
    return NextResponse.json(
      { error: "internal", details: String(err?.message ?? err) },
      { status: 500 }
    );
  }
}
