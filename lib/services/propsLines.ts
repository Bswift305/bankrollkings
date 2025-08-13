import { createServerSupabase } from "@/lib/supabase/server";
import { getLimitFromSearchParams } from "@/lib/http/params";

type PropLine = Record<string, any>;

export async function listPropsLines(sp: URLSearchParams) {
  const limit = getLimitFromSearchParams(sp, 50, 200);
  const supabase = createServerSupabase();

  const { data, error } = await supabase
    .from("props_lines") // TODO: update to your schema
    .select("*")
    .order("created_at", { ascending: false })
    .limit(limit);

  if (error) throw new Error(error.message);
  return (data ?? []) as PropLine[];
}

// (Optional) Back-compat name if any route still imports listPropLines
export const listPropLines = listPropsLines;
