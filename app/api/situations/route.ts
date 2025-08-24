import { NextRequest, NextResponse } from "next/server";

const SUPABASE_URL = process.env.NEXT_PUBLIC_SUPABASE_URL ?? "";
const SUPABASE_KEY = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY ?? process.env.SUPABASE_SERVICE_ROLE_KEY ?? "";

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
    const limit = url.searchParams.get("limit") ?? "200"; // Increased limit!

    const sel = ["player_id", "full_name", "position", "season", "category", "def_tier", "team_abbr", "total_yards", "games", "per_game"].join(",");

    const params = q({
      select: sel,
      ...(position ? { position: `eq.${position}` } : {}),
      ...(team ? { team_abbr: `eq.${team}` } : {}),
      ...(defenseTier ? { def_tier: `eq.${defenseTier}` } : {}),
      season: "eq.2024",
      category: "eq.pass",
      order: "total_yards.desc.nullslast",
      limit,
    });

    const resp = await fetch(`${SUPABASE_URL}/rest/v1/v_situational_leaderboard?${params.toString()}`, {
      headers: {
        apikey: SUPABASE_KEY,
        Authorization: `Bearer ${SUPABASE_KEY}`,
        "Content-Type": "application/json",
      },
      cache: "no-store",
    });

    if (!resp.ok) {
      const text = await resp.text();
      return NextResponse.json({ error: `supabase error ${resp.status}`, details: text }, { status: 500 });
    }

    const rawRows = await resp.json();
    
    const rows = rawRows.map((row: any) => ({
      player_name: row.full_name,  // ✅ Fixed mapping
      team: row.team_abbr,         // ✅ Fixed mapping
      position: row.position,
      total_yards: parseInt(row.total_yards) || 0,
      games: row.games || 1,
      defense_tier: row.def_tier,
      per_game: parseFloat(row.per_game) || 0
    }));

    return NextResponse.json({ rows });
  } catch (err: any) {
    return NextResponse.json({ error: "internal", details: String(err?.message ?? err) }, { status: 500 });
  }
}
