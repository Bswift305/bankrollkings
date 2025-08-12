import { createServerSupabase } from "@/lib/supabase/server";
import { getLimitFromSearchParams } from "@/lib/http/params";
import { orderOrFallback } from "@/lib/db/safeOrder";

type PbpRow = Record<string, any>; // adjust to your schema

// <-- this is the named export your route expects
export async function listPbp2024(sp: URLSearchParams) {
  const limit = getLimitFromSearchParams(sp, 50, 200);
  const supabase = createServerSupabase();

  const base = supabase
    .from("pbp_2024") // TODO: update table name if different
    .select("*")
    .limit(limit);

  const { data, error } = await orderOrFallback<PbpRow>(base, [
    "play_id",
    "created_at",
    "id",
  ]);
  if (error) throw new Error(error.message);
  return data;
}
