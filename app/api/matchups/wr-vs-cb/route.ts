import { NextRequest, NextResponse } from "next/server";
import { supabaseServer } from "../../../backend/utils/supabaseServer";

export async function GET(req: NextRequest) {
  const sp = req.nextUrl.searchParams;
  const wr = sp.get("wr");
  const cb = sp.get("cb");
  const season = sp.get("season");
  const week = sp.get("week");
  const limit = Number(sp.get("limit") ?? 50);

  // Require at least WR and CB for now (we can relax later)
  if (!wr || !cb) {
    return NextResponse.json(
      { ok: false, error: "wr and cb are required" },
      { status: 400 }
    );
  }

  let q = supabaseServer
    .from("wr_vs_cb")
    .select("*")
    .eq("wr_name", wr)
    .eq("cb_name", cb)
    .order("season", { ascending: false })
    .order("week", { ascending: false })
    .limit(limit);

  if (season) q = q.eq("season", season);
  if (week) q = q.eq("week", week);

  const { data, error } = await q;
  if (error) return NextResponse.json({ ok: false, error: error.message }, { status: 500 });
  return NextResponse.json({ ok: true, data });
}
