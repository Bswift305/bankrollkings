import { supabaseServer } from "../utils/supabaseServer";
export type PropLine = Record<string, unknown>;
export async function listPropLines(limit = 20) {
  const { data, error } = await supabaseServer.from("props_lines").select("*").limit(limit);
  if (error) throw new Error(`listPropLines failed: ${error.message}`);
  return data as PropLine[];
}
