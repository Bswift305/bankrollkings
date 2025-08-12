import { createServerSupabase } from "@/lib/supabase/server";
import { getLimitFromSearchParams } from "@/lib/http/params";
import { orderOrFallback } from "@/lib/db/safeOrder";

type GameScript = Record<string, any>;

export async function listGameScripts(sp: URLSearchParams) {
  const limit = getLimitFromSearchParams(sp, 50, 200);
  const supabase = createServerSupabase();

  const base = supabase.from("game_scripts").select("*").limit(limit);
  const { data, error } = await orderOrFallback<GameScript>(
    base,
    ["created_at", "updated_at", "id"]
  );
  if (error) throw new Error(error.message);
  return data;
}

