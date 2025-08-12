import { createServerSupabase } from "@/lib/supabase/server";
import { getLimitFromSearchParams } from "@/lib/http/params";

type WeatherRow = Record<string, any>; // adjust to your schema

export async function listWeather(sp: URLSearchParams) {
  const limit = getLimitFromSearchParams(sp, 50, 200);
  const supabase = createServerSupabase();

  const { data, error } = await supabase
    .from("weather") // TODO: match your table
    .select("*")
    .order("id", { ascending: false })
    .limit(limit);

  if (error) throw new Error(error.message);
  return (data ?? []) as WeatherRow[];
}
