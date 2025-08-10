import { NextResponse } from "next/server";
import { getTeamMetrics } from "../../../backend/services/teamMetrics";

export async function GET() {
  try {
    const data = await getTeamMetrics(5);
    return NextResponse.json({ ok: true, data });
  } catch (err: any) {
    return NextResponse.json({ ok: false, error: err?.message ?? "Unknown error" }, { status: 500 });
  }
}
