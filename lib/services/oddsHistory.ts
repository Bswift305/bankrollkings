import { orderOrFallback } from "@/lib/db/safeOrder";

export async function listOddsHistory(sp: URLSearchParams) {
  const limit = getLimitFromSearchParams(sp, 50, 200);
  const supabase = createServerSupabase();

  const base = supabase.from("odds_history").select("*").limit(limit);
  const { data, error } = await orderOrFallback(base, ["created_at", "updated_at", "id"]);
  if (error) throw new Error(error.message);
  return data;
}
