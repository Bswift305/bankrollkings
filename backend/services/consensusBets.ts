import { supabaseServer } from "../utils/supabaseServer";
export type ConsensusBet = Record<string, unknown>;
export async function listConsensusBets(limit = 20) {
  const { data, error } = await supabaseServer.from("consensus_bets").select("*").limit(limit);
  if (error) throw new Error(`listConsensusBets failed: ${error.message}`);
  return data as ConsensusBet[];
}
