import { createServerSupabase } from "@/lib/supabase/server";
import { getLimitFromSearchParams } from "@/lib/http/params";
import { orderOrFallback } from "@/lib/db/safeOrder";

type Injury = Record<string, any>;

export async function listInjuries(sp: URLSearchParams) {
  const limit = getLimitFromSearchParams(sp, 50, 200);
  const supabase = createServerSupabase();

  const base = supabase.from("injuries").select("*").limit(limit);
  const { data, error } = await orderOrFallback<Injury>(
    base,
    ["updated_at", "created_at", "id"]
  );
  if (error) throw new Error(error.message);
  return data;
}
