import { supabaseServer } from "../utils/supabaseServer";
export type EventRow = Record<string, unknown>;
export async function listEvents(limit = 20) {
  const { data, error } = await supabaseServer
    .from("events")
    .select("*")
    .order("created_at", { ascending: false }) // adjust to your timestamp
    .limit(limit);
  if (error) throw new Error(`listEvents failed: ${error.message}`);
  return data as EventRow[];
}
