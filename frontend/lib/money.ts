/**
 * Mirror of backend `app.core.money.format_cents`: `$1,000` when there are no
 * cents, `$999.50` otherwise, and negatives read `-$5`.
 *
 * Integer math only (no floats) so values never drift; `en-US` is pinned so
 * server and browser render the same string.
 */
const GROUPED = new Intl.NumberFormat("en-US", { maximumFractionDigits: 0 })

export function formatCents(cents: number): string {
  const sign = cents < 0 ? "-" : ""
  const abs = Math.abs(Math.trunc(cents))
  const dollars = Math.floor(abs / 100)
  const rest = abs % 100
  const amount =
    rest === 0
      ? GROUPED.format(dollars)
      : `${GROUPED.format(dollars)}.${String(rest).padStart(2, "0")}`
  return `${sign}$${amount}`
}
