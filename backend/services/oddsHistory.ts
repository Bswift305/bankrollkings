import { supabaseServer } from "../utils/supabaseServer";
export type OddsHistory = Record<string, unknown>;
export async function listOddsHistory(limit = 20) {
  const { data, error } = await supabaseServer
    .from("odds_history")
    .select("*")
    .order("created_at", { ascending: false }) // adjust if your timestamp column differs
    .limit(limit);
  if (error) throw new Error(`listOddsHistory failed: ${error.message}`);
  return data as OddsHistory[];
}
