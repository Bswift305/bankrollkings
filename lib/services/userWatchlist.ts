import { supabaseServer } from "../utils/supabaseServer";
export type WatchRow = Record<string, unknown>;
export async function listUserWatchlist(limit = 50) {
  const { data, error } = await supabaseServer.from("user_watchlist").select("*").limit(limit);
  if (error) throw new Error(`listUserWatchlist failed: ${error.message}`);
  return data as WatchRow[];
}
