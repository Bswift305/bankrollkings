import { supabaseServer } from "../utils/supabaseServer";

export type PropLine = Record<string, unknown>; // we'll refine once columns are finalized

export async function listPropLines(limit = 20) {
  const { data, error } = await supabaseServer
    .from("props_lines")
    .select("*")
    .limit(limit);

  if (error) throw new Error(`listPropLines failed: ${error.message}`);
  return data as PropLine[];
}
