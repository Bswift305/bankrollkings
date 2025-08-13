import { supabaseServer } from "../utils/supabaseServer";
export type WeatherRow = Record<string, unknown>;
export async function listWeather(limit = 50) {
  const { data, error } = await supabaseServer.from("weather").select("*").limit(limit);
  if (error) throw new Error(`listWeather failed: ${error.message}`);
  return data as WeatherRow[];
}
