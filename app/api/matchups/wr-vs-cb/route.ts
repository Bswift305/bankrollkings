import { NextRequest, NextResponse } from "next/server";
export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET(req: NextRequest) {
  const sp = req.nextUrl.searchParams;
  const wr = sp.get("wr");
  const cb = sp.get("cb");
  const season = sp.get("season");
  // Minimal echo; add DB query later
  return NextResponse.json({ ok: true, route: "wr-vs-cb", wr, cb, season });
}
