// lib/services/gameScripts.ts
import { createServerSupabase } from "@/lib/supabase/server";
import { getLimitFromSearchParams } from "@/lib/utils/http";

export async function listGameScripts(sp: URLSearchParams) {
  const limit = getLimitFromSearchParams(sp, 50, 200);
  const supabase = createServerSupabase();

  const { data, error } = await supabase
    .from("game_scripts")
    .select("*")
    .order("game_id", { ascending: false }) // <— CHANGED from "id" → "game_id"
    .limit(limit);

  if (error) throw new Error(error.message);
  return data ?? [];
}
