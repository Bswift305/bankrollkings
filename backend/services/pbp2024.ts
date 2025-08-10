import { supabaseServer } from "../utils/supabaseServer";
export type PbpRow = Record<string, unknown>;
export async function listPbp2024(limit = 50) {
  const { data, error } = await supabaseServer
    .from("pbp_2024")
    .select("*")
    .order("play_id", { ascending: false }) // adjust to your key/timestamp
    .limit(limit);
  if (error) throw new Error(`listPbp2024 failed: ${error.message}`);
  return data as PbpRow[];
}
