"use client";

import { useEffect, useMemo, useState } from "react";
import { createClient } from "@supabase/supabase-js";

type TeamMetric = {
  id: number;
  team?: string | null;
};

export default function Home() {
  const [data, setData] = useState<TeamMetric[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Browser Supabase client (uses public anon key)
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
          .select("*")
          .limit(10);
        if (error) throw error;
        setData(data ?? []);
      } catch (e: any) {
        setError(e?.message ?? "Unknown error");
        setData(null);
      } finally {
        setLoading(false);
      }
    };
    run();
  }, [supabase]);

  return (
    <main style={{ padding: 24, fontFamily: "system-ui", lineHeight: 1.5 }}>
      <h1>BankrollKings</h1>

      <div style={{ marginTop: 8, color: "#666", fontSize: 14 }}>
        <div>
          API checks:{" "}
          <a href="/api/health">/api/health</a> •{" "}
          <a href="/api/team-metrics">/api/team-metrics</a>
        </div>
      </div>

      <section style={{ marginTop: 20 }}>
        {loading && <p>Loading…</p>}
        {error && (
          <p style={{ color: "crimson" }}>
            Supabase error: {error}
          </p>
        )}
        {!loading && !error && (
          <>
            {(!data || data.length === 0) ? (
              <p>
                No rows found in <code>team_metrics</code>. Add one in Supabase
                (Table Editor) to see it here.
              </p>
            ) : (
              <div
                style={{
                  border: "1px solid #eee",
                  borderRadius: 12,
                  overflow: "hidden",
                  maxWidth: 600,
                }}
              >
                <table style={{ width: "100%", borderCollapse: "collapse" }}>
                  <thead style={{ background: "#f9f9f9" }}>
                    <tr>
                      <th style={{ textAlign: "left", padding: 12, borderBottom: "1px solid #eee" }}>
                        ID
                      </th>
                      <th style={{ textAlign: "left", padding: 12, borderBottom: "1px solid #eee" }}>
                        Team
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.map((row) => (
                      <tr key={row.id}>
                        <td style={{ padding: 12, borderBottom: "1px solid #f1f1f1" }}>{row.id}</td>
                        <td style={{ padding: 12, borderBottom: "1px solid #f1f1f1" }}>
                          {row.team ?? <em style={{ color: "#777" }}>—</em>}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </>
        )}
      </section>

      <section style={{ marginTop: 16, color: "#666", fontSize: 12 }}>
        <p>
          Make sure <code>NEXT_PUBLIC_SUPABASE_URL</code> and{" "}
          <code>NEXT_PUBLIC_SUPABASE_ANON_KEY</code> are set in Vercel →
          Project → Settings → Environment Variables.
        </p>
      </section>
    </main>
  );
}
