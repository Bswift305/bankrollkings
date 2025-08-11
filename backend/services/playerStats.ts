import { supabaseServer } from "../utils/supabaseServer";
export type PlayerStat = Record<string, unknown>;
// CHANGE this to your exact table name if different:
const TABLE = "player_stats_2";
export async function listPlayerStats(limit = 50) {
  const { data, error } = await supabaseServer.from(TABLE).select("*").limit(limit);
  if (error) throw new Error(`listPlayerStats failed: ${error.message}`);
  return data as PlayerStat[];
}

