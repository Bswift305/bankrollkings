import { orderOrFallback } from "@/lib/db/safeOrder";

export async function listWeather(sp: URLSearchParams) {
  const limit = getLimitFromSearchParams(sp, 50, 200);
  const supabase = createServerSupabase();

  const base = supabase.from("weather").select("*").limit(limit);
  const { data, error } = await orderOrFallback(base, ["observed_at", "created_at", "id"]);
  if (error) throw new Error(error.message);
  return data;
}
