import { supabaseServer } from "../utils/supabaseServer";
export type PowerRating = Record<string, unknown>;
export async function listPowerRatings(limit = 32) {
  const { data, error } = await supabaseServer
    .from("power_ratings")
    .select("*")
    .order("rating", { ascending: false }) // adjust if your column differs
    .limit(limit);
  if (error) throw new Error(`listPowerRatings failed: ${error.message}`);
  return data as PowerRating[];
}
