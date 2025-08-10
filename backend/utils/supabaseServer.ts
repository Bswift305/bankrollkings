import { createClient } from "@supabase/supabase-js";

/** Server-side Supabase client */
const supabaseUrl = process.env.NEXT_PUBLIC_SUPABASE_URL!;
const serviceKey =
  process.env.SUPABASE_SERVICE_ROLE_KEY || process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!;

export const supabaseServer = createClient(supabaseUrl, serviceKey);
