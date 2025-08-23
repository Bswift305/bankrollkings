import { NextRequest, NextResponse } from "next/server";
import { getLimitFromSearchParams } from "@/lib/http"; // ✅ Fixed import path
import { listConsensusBets } from "@/lib/services/consensusBets";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET(req: NextRequest) {
  try {
    // this service currently accepts an object with { limit }
    const limit = getLimitFromSearchParams(req.nextUrl.searchParams, 50, 200);
    const data = await listConsensusBets({ limit });
    return NextResponse.json({ ok: true, data });
  } catch (e: any) {
    return NextResponse.json({ ok: false, error: e?.message ?? "Unknown error" }, { status: 500 });
  }
}
