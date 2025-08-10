export default function Home() {
  return (
    <main style={{ padding: 24, fontFamily: "system-ui" }}>
      <h1>BankrollKings</h1>
      <p>Next.js + Supabase starter is running.</p>
      <p>Health check: <a href="/api/health">/api/health</a></p>
      <p>Sample data: <a href="/api/team-metrics">/api/team-metrics</a></p>
    </main>
  );
}
