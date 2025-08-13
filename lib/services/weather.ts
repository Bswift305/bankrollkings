import { createServerSupabase } from "@/lib/supabase/server";
import { getLimitFromSearchParams } from "@/lib/http/params";

type WatchItem = Record<string, any>; // adjust to your schema

export async function listUserWatchlist(sp: URLSearchParams) {
  const limit = getLimitFromSearchParams(sp, 50, 200);
  const userId = sp.get("userId") ?? sp.get("user_id") ?? undefined;

  const supabase = createServerSupabase();

  let query = supabase
    .from("user_watchlist") // TODO: match your table name
    .select("*")
    .limit(limit);

  if (userId) query = query.eq("user_id", userId);

  const { data, error } = await query;
  if (error) {
    throw new Error(error.message);
  }
  return (data ?? []) as WatchItem[];
}

