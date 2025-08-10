import { supabaseServer } from "../utils/supabaseServer";
export type PlayerStat = Record<string, unknown>;
export async function listPlayerStats(limit = 50) {
  const { data, error } = await supabaseServer
    .from("player_stats_2") // <-- change if your table name differs
    .select("*")
    .limit(limit);
  if (error) throw new Error(`listPlayerStats failed: ${error.message}`);
  return data as PlayerStat[];
}
