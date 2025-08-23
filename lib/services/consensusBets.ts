import { createServerSupabase } from "@/lib/supabase/server";
import { getLimitFromSearchParams } from "@/lib/http/params"; // ✅ FIXED

type ConsensusBet = Record<string, any>; // replace with real columns when ready

export async function listConsensusBets(opts: { limit?: number }) {
  const limit = Math.max(1, Math.min(opts.limit ?? 50, 200));
  const supabase = createServerSupabase();

  const { data, error } = await supabase
    .from("consensus_bets") // TODO: change to your real table
    .select("*")
    .limit(limit);

  if (error) throw new Error(error.message);
  return (data ?? []) as ConsensusBet[];
}
