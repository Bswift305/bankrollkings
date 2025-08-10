"use client";

import { useEffect, useMemo, useState } from "react";
import { createClient, SupabaseClient } from "@supabase/supabase-js";

type TeamMetric = {
  id: number;
  team?: string | null;
  // add any other columns you have, e.g. rating?: number | null;
};

export default function Home() {
  const [data, setData] = useState<TeamMetric[] | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);

  // Create a browser (public) Supabase client
  const supabase = useMemo(() => {
    const url = process.env.NEXT_PUBLIC_SUPABASE_URL;
    const anon = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;

    if (!url || !anon) {
      console.warn("Missing NEXT_PUBLIC_SUPABASE_URL or NEXT_PUBLIC_SUPABASE_ANON_KEY.");
    }
    return createClient(url ?? "", anon ?? "") as SupabaseClient;
  }, []);

  const fetchData = async () => {
    try {
      setLoading(true);
      setError(null);

      const { data, error } = await supabase
        .from("team_metrics")
        .select("*")
        .limit(20);

      if (error) throw error;
      setData(data ?? []);
    } catch (err: any) {
      setError(err?.message ?? "Unknown error");
      setData(null);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchData();
    // If you want realtime later, we can add a channel subscription here.
  }, []);

  return (
    <main style={{ padding: 24, fontFamily: "system-ui", lineHeight: 1.5 }}>
      <h1 style={{ margin: 0 }}>BankrollKings</h1>
      <p style={{ marginTop: 6, color: "#555" }}>
        Next.js + Supabase starter.{" "}
        <a href="/api/health" style={{ textDecoration: "underline" }}>
          /api/health
        </a>{" "}
        •{" "}
        <a href="/api/team-metrics" style={{ textDecoration: "underline" }}>
          /api/team-metrics
        </a>
      </p>

      <section style={{ marginTop: 24 }}>
        <div style={{ display: "flex", gap: 12, alignItems: "center" }}>
          <button
            onClick={fetchData}
            style={{
              padding: "8px 14px",
              borderRadius: 8,
              border: "1px solid #ddd",
              cursor: "pointer",
              background: "#111",
              color: "#fff",
            }}
          >
            Refresh
          </button>
          {loading && <span>Loading…</span>}
          {error && (
            <span style={{ color: "crimson" }}>
              Error: {error}
            </span>
          )}
        </div>

        <div style={{ marginTop: 16 }}>
          {(!loading && !error && data && data.length === 0) && (
            <p>No rows found in <code>team_metrics</code>. Add one in Supabase to see it here.</p>
          )}

          {data && data.length > 0 && (
            <div
              style={{
                marginTop: 8,
                border: "1px solid #eee",
                borderRadius: 12,
                overflow: "hidden",
              }}
            >
              <table style={{ width: "100%", borderCollapse: "collapse" }}>
                <thead style={{ background: "#f9f9f9" }}>
                  <tr>
                    <th style={{ textAlign: "left", padding: 12, borderBottom: "1px solid #eee" }}>ID</th>
                    <th style={{ textAlign: "left", padding: 12, borderBottom: "1px solid #eee" }}>Team</th>
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
        </div>
      </section>

      <section style={{ marginTop: 24, color: "#666", fontSize: 14 }}>
        <p>
          Env check:{" "}
          <code>NEXT_PUBLIC_SUPABASE_URL</code> and{" "}
          <code>NEXT_PUBLIC_SUPABASE_ANON_KEY</code> must be set in Vercel →
          Project → Settings → Environment Variables.
        </p>
      </section>
    </main>
  );
}
