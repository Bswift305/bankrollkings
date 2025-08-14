import { NextRequest, NextResponse } from "next/server";
import { z } from "zod";
import { createClient } from "@supabase/supabase-js";

const schema = z.object({
  position: z.enum(["RB","WR","TE","QB"]),
  stat: z.enum(["rush_yards","rec_yards","receptions","pass_yards"]),
  seasonFrom: z.coerce.number().int(),
  seasonTo: z.coerce.number().int(),
  defCat: z.enum(["rush","pass","overall"]),
  tier: z.enum(["top10","bottom10","mid"]),
  limit: z.coerce.number().int().max(100).default(50),
});

export async function GET(req: NextRequest) {
  const url = new URL(req.url);
  const parse = schema.safeParse(Object.fromEntries(url.searchParams));
  if (!parse.success) return NextResponse.json({ error: parse.error.format() }, { status: 400 });

  const supabase = createClient(process.env.NEXT_PUBLIC_SUPABASE_URL!, process.env.SUPABASE_SERVICE_ROLE_KEY!);

  const { data, error } = await supabase.rpc("api_leaderboard_situational", {
    p_position: parse.data.position,
    p_stat: parse.data.stat,
    p_season_from: parse.data.seasonFrom,
    p_season_to: parse.data.seasonTo,
    p_def_cat: parse.data.defCat,
    p_def_tier: parse.data.tier,
    p_limit: parse.data.limit,
  });

  if (error) return NextResponse.json({ error: error.message }, { status: 500 });
  return NextResponse.json({ rows: data ?? [] }, { headers: { "cache-control": "no-store" } });
}
