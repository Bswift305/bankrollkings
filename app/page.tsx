"use client";

import { useEffect, useMemo, useState } from "react";
import { createClient } from "@supabase/supabase-js";

type Row = {
  team_id: string;
  redzone_pct: number | null;
  goal_line_td_pct: number | null;
  third_down_stop_pct: number | null;
};

function pct(n: number | null | undefined) {
  if (n == null) return "—";
  return `${(n * 100).toFixed(1)}%`;
}

export default function Home() {
  const [rows, setRows] = useState<Row[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const supabase = useMemo(() => {
    const url = process.env.NEXT_PUBLIC_SUPABASE_URL || "";
    const anon = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY || "";
    return createClient(url, anon);
  }, []);

  useEffect(() => {
    const run = async () => {
      try {
        setLoading(true);
        setError(null);
        const { data, error } = await supabase
          .from("team_metrics")
          .select("team_id, redzone_pct, goal_line_td_pct, third_down_stop_pct")
          .limit(20);
        if (error) throw error;
        setRows(data as Row[]);
      } catch (e: any) {
        setError(e?.message ?? "Unknown error");
      } finally {
        setLoading(false);
      }
    };
    run();
  }, [supabase]);

  return (
    <main style={{ padding: 24, fontFamily: "system-ui", lineHeight: 1.5 }}>
      <h1>BankrollKings</h1>
      <p style={{ marginTop: 6 }}>
        API checks: <a href="/api/health">/api/health</a> •{" "}
        <a href="/api/team-metrics">/api/team-metrics</a>
      </p>

      {loading && <p>Loading…</p>}
      {error && <p style={{ color: "crimson" }}>Error: {error}</p>}

      {!loading && !error && (
        <div
          style={{
            marginTop: 12,
            border: "1px solid #eee",
            borderRadius: 12,
            overflow: "hidden",
            maxWidth: 800
          }}
        >
          <table style={{ width: "100%", borderCollapse: "collapse" }}>
            <thead style={{ background: "#f9f9f9" }}>
              <tr>
                <th style={{ textAlign: "left", padding: 12, borderBottom: "1px solid #eee" }}>
                  Team
                </th>
                <th style={{ textAlign: "left", padding: 12, borderBottom: "1px solid #eee" }}>
                  Red Zone TD%
                </th>
                <th style={{ textAlign: "left", padding: 12, borderBottom: "1px solid #eee" }}>
                  Goal Line TD%
                </th>
                <th style={{ textAlign: "left", padding: 12, borderBottom: "1px solid #eee" }}>
                  3rd Down Stop%
                </th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.team_id}>
                  <td style={{ padding: 12, borderBottom: "1px solid #f1f1f1" }}>{r.team_id}</td>
                  <td style={{ padding: 12, borderBottom: "1px solid #f1f1f1" }}>{pct(r.redzone_pct)}</td>
                  <td style={{ padding: 12, borderBottom: "1px solid #f1f1f1" }}>{pct(r.goal_line_td_pct)}</td>
                  <td style={{ padding: 12, borderBottom: "1px solid #f1f1f1" }}>{pct(r.third_down_stop_pct)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </main>
  );
}
