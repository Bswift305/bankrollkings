export function getLimitFromSearchParams(searchParams: URLSearchParams, def = 20, max = 200) {
  const v = Number(searchParams.get("limit") ?? def);
  if (Number.isNaN(v) || v <= 0) return def;
  return Math.min(v, max);
}
