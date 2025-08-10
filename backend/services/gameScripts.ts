import { supabaseServer } from "../utils/supabaseServer";
export type GameScript = Record<string, unknown>;
export async function listGameScripts(limit = 20) {
  const { data, error } = await supabaseServer.from("game_scripts").select("*").limit(limit);
  if (error) throw new Error(`listGameScripts failed: ${error.message}`);
  return data as GameScript[];
}
