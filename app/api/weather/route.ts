import { NextRequest, NextResponse } from "next/server";
import { getLimitFromSearchParams } from "../../../backend/utils/http";
import { listGameScripts } from "../../../backend/services/gameScripts";

export async function GET(req: NextRequest) {
  try {
    const limit = getLimitFromSearchParams(req.nextUrl.searchParams, 50, 200);
    const data = await listWeather(limit);
    return NextResponse.json({ ok: true, data });
  } catch (e:any) {
    return NextResponse.json({ ok:false, error:e?.message ?? "Unknown error" }, { status:500 });
  }
}
