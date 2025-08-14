import { NextRequest, NextResponse } from "next/server";
import { createClient } from "@supabase/supabase-js";
import { z } from "zod";

const schema = z.object({
  playerId: z.string().uuid(),
  seasonFrom: z.coerce.number().int(),
  seasonTo: z.coerce.number().int(),
  defCat: z.enum(["rush","pass","overall"]).nullish(),
  tier: z.enum(["top10","bottom10","mid"]).nullish(),
  prime: z.coerce.boolean().nullish(),
  dome: z.coerce.boolean().nullish(),
  windy: z.coerce.boolean().nullish(),
  homeAway: z.enum(["home","away"]).nullish(),
  opponent: z.string().length(2).toUpperCase().nullish(),
});

export async function GET(req: NextRequest) {
  const url = new URL(req.url);
  const parse = schema.safeParse(Object.fromEntries(url.searchParams));
  if (!parse.success) {
    return NextResponse.json({ error: parse.error.format() }, { status: 400 });
  }

  const s = parse.data;
  const supabase = createClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.SUPABASE_SERVICE_ROLE_KEY!
  );

  const { data, error } = await supabase.rpc("api_get_player_situational_stats", {
    p_player_id: s.playerId,
    p_season_from: s.seasonFrom,
    p_season_to: s.seasonTo,
    p_def_cat: s.defCat ?? null,
    p_def_tier: s.tier ?? null,
    p_prime_only: s.prime ?? null,
    p_dome_only: s.dome ?? null,
    p_windy_only: s.windy ?? null,
    p_home_away: s.homeAway ?? null,
    p_opponent: s.opponent ?? null,
  });

  if (error) return NextResponse.json({ error: error.message }, { status: 500 });
  return NextResponse.json({ rows: data ?? [] }, { headers: { "cache-control": "no-store" } });
}

