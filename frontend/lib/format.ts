/**
 * A follower count in the short form people say it: `950`, `24k`, `78.1k`, `142k`,
 * `1.2M`. Under 100k one decimal is kept (78.1k) because it still tells creators apart.
 */
export function formatFollowers(count: number): string {
  if (count < 1000) return String(count)
  if (count < 1_000_000) {
    const thousands =
      count >= 100_000 ? Math.round(count / 1000) : Math.round(count / 100) / 10
    // 999,999 rounds up to a thousand thousands.
    if (thousands < 1000) return `${thousands}k`
  }
  return `${Math.round(count / 100_000) / 10}M`
}

/**
 * An engagement rate for display. The API sends percentage points (5.8 means 5.8%),
 * so nothing is scaled here. A creator with no rate reads as a dash.
 */
export function formatEngagement(points: number | null): string {
  if (points === null) return "—"
  return `${Number(points.toFixed(1))}%`
}
