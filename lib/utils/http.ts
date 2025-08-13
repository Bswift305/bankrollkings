// Small helpers shared by API routes & services

/** Clamp a number between min and max */
function clamp(n: number, min: number, max: number) {
  return Math.max(min, Math.min(max, n));
}

/**
 * Reads `limit` from URLSearchParams and clamps it to [min,max].
 * If not present / invalid, returns `min`.
 */
export function getLimitFromSearchParams(
  sp: URLSearchParams,
  min: number,
  max: number
): number {
  const raw = sp.get("limit");
  const n = raw ? Number(raw) : NaN;
  const parsed = Number.isFinite(n) ? Math.floor(n) : min;
  return clamp(parsed, min, max);
}
