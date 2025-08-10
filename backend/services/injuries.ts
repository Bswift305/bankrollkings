import { supabaseServer } from "../utils/supabaseServer";

export type InjuryRow = Record<string, unknown>;

export async function listInjuries(limit = 20) {
  const { data, error } = await supabaseServer
    .from("injuries")
    .select("*")
    .limit(limit);

  if (error) throw new Error(`listInjuries failed: ${error.message}`);
  return data as InjuryRow[];
}
