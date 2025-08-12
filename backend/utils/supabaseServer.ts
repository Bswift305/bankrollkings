import { createClient } from "@supabase/supabase-js";

export const supabaseServer = createClient(
  process.env.NEXT_PUBLIC_SUPABASE_URL!,          // read-only is fine for SELECT views
  process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!
);

