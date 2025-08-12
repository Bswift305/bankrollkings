import { orderOrFallback } from "@/lib/db/safeOrder";

export async function listUserWatchlist(sp: URLSearchParams) {
  const limit = getLimitFromSearchParams(sp, 50, 200);
  const userId = sp.get("userId") ?? sp.get("user_id") ?? undefined;
  const supabase = createServerSupabase();

  let base = supabase.from("user_watchlist").select("*").limit(limit);
  if (userId) base = base.eq("user_id", userId);

  const { data, error } = await orderOrFallback(base, ["created_at", "inserted_at", "added_at", "id"]);
  if (error) throw new Error(error.message);
  return data;
}
