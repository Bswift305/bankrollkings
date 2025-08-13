export function getLimitFromSearchParams(
  sp: URLSearchParams,
  fallback = 50,
  max = 200
): number {
  const raw = sp.get("limit");
  const n = raw ? Number(raw) : NaN;
  if (!Number.isFinite(n) || n <= 0) return fallback;
  return Math.min(n, max);
}
