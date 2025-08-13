import { NextRequest, NextResponse } from "next/server";
import { listUserWatchlist } from "@/lib/services/userWatchlist";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET(req: NextRequest) {
  try {
    // Pass URLSearchParams; the service computes/clamps `limit` internally
    const data = await listUserWatchlist(req.nextUrl.searchParams);
    return NextResponse.json({ ok: true, data });
  } catch (e: any) {
    return NextResponse.json(
      { ok: false, error: e?.message ?? "Unknown error" },
      { status: 500 }
    );
  }
}

