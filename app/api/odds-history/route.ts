import { NextRequest, NextResponse } from "next/server";
import { listOddsHistory } from "@/lib/services/oddsHistory";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET(req: NextRequest) {
  try {
    const data = await listOddsHistory(req.nextUrl.searchParams);
    return NextResponse.json({ ok: true, data });
  } catch (e: any) {
    return NextResponse.json({ ok: false, error: e?.message ?? "Unknown error" }, { status: 500 });
  }
}

