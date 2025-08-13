import { NextRequest, NextResponse } from "next/server";
import { getLimitFromSearchParams } from "@/lib/http/params";
import { listPowerRatings } from "@/lib/services/powerRatings";

export async function GET(req: NextRequest) {
  try {
    const limit = getLimitFromSearchParams(req.nextUrl.searchParams, 32, 64);
    const data = await listPowerRatings(limit);
    return NextResponse.json({ ok: true, data });
  } catch (e:any) {
    return NextResponse.json({ ok:false, error:e?.message ?? "Unknown error" }, { status:500 });
  }
}
