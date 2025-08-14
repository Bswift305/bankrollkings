import { NextRequest, NextResponse } from "next/server";
import { z } from "zod";
import { createClient } from "@supabase/supabase-js";

const schema = z.object({
  playerId: z.string().uuid(),
  propType: z.enum(["rush_yds","rec_yds","receptions","pass_yds","rush_tds","rec_tds","pass_tds"]),
  seasonFrom: z.coerce.number().int(),
  seasonTo: z.coerce.number().int(),
  defCat: z.enum(["rush","pass","overall"]).nullish(),
  tier: z.enum(["top10","bottom10","mid"]).nullish(),
  prime: z.coerce.boolean().nullish(),
  dome: z.coerce.boolean().nullish(),
  windy: z.coerce.boolean().nullish(),
});

export async function GET(req: NextRequest) {
  const url = new URL(req.url);
  const parse = schema.safeParse(Object.fromEntries(url.searchParams));
  if (!parse.success) return NextResponse.json({ error: parse.error.format() }, { status: 400 });

  const supabase = createClient(process.env.NEXT_PUBLIC_SUPABASE_URL!, process.env.SUPABASE_SERVICE_ROLE_KEY!);

  const { data, error } = await supabase.rpc("api_prop_hit_rate", {
    p_player_id: parse.data.playerId,
    p_prop_type: parse.data.propType,
    p_season_from: parse.data.seasonFrom,
    p_season_to: parse.data.seasonTo,
    p_def_cat: parse.data.defCat ?? null,
    p_def_tier: parse.data.tier ?? null,
    p_prime_only: parse.data.prime ?? null,
    p_dome_only: parse.data.dome ?? null,
    p_windy_only: parse.data.windy ?? null,
  });

  if (error) return NextResponse.json({ error: error.message }, { status: 500 });
  return NextResponse.json({ rows: data ?? [] }, { headers: { "cache-control": "no-store" } });
}
