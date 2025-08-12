import { createServerSupabase } from "@/lib/supabase/server";
import { getLimitFromSearchParams } from "@/lib/http/params";

type PowerRating = Record<string, any>;

export async function listPowerRatings(sp: URLSearchParams) {
  const limit = getLimitFromSearchParams(sp, 50, 200);
  const supabase = createServerSupabase();

  const { data, error } = await supabase
    .from("power_ratings") // TODO: update to your schema
    .select("*")
    .order("id", { ascending: false })
    .limit(limit);

  if (error) throw new Error(error.message);
  return (data ?? []) as PowerRating[];
}


