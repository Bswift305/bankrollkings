import { createServerSupabase } from "@/lib/supabase/server";
import { getLimitFromSearchParams } from "@/lib/http/params";

type WatchItem = Record<string, any>; // adjust to your schema

export async function listUserWatchlist(sp: URLSearchParams) {
  const limit = getLimitFromSearchParams(sp, 50, 200);
  const userId = sp.get("userId") ?? sp.get("user_id") ?? undefined;

  const supabase = createServerSupabase();

  // Base query
  let base = supabase.from("user_watchlist").select("*").limit(limit);
  if (userId) base = base.eq("user_id", userId);

  // Try ordering by created_at first; if that column doesn't exist, retry without ordering.
  let { data, error } = await base.order("created_at", { ascending: false });
  if (error && /column .* does not exist/i.test(error.message)) {
    // Retry without ordering
    const retry = await base;
    data = retry.data;
    error = retry.error;
  }

  if (error) throw new Error(error.message);
  return (data ?? []) as WatchItem[];
}
