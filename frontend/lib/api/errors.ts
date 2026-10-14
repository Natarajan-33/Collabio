/**
 * Reading the error bodies the API sends. Three shapes are in use:
 * `{detail: "not_found"}` (older endpoints), `{detail: {error: "..."}}` (older, with
 * extras) and `{detail: {code, message, ...extra}}` (every M3 endpoint). Whatever an
 * `openapi-fetch` call returned as `error` can be passed in, including `undefined`.
 */

function detailOf(error: unknown): unknown {
  if (typeof error !== "object" || error === null) return undefined
  return (error as { detail?: unknown }).detail
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value)
}

/** The error's code, from any of the three shapes; null when it has none. */
export function apiErrorCode(error: unknown): string | null {
  const detail = detailOf(error)
  if (typeof detail === "string") return detail
  if (!isRecord(detail)) return null
  if (typeof detail.code === "string") return detail.code
  if (typeof detail.error === "string") return detail.error
  return null
}

/**
 * The `{code, message, ...extra}` detail of an M3 error, typed with its extras
 * (`terms_event_id`, `below_by_cents`, `errors`...). Null for string details, the older
 * `{error}` shape, and anything that is not an API error.
 */
export function apiErrorDetail<T = Record<string, unknown>>(
  error: unknown
): (T & { code: string; message: string }) | null {
  const detail = detailOf(error)
  if (
    isRecord(detail) &&
    typeof detail.code === "string" &&
    typeof detail.message === "string"
  ) {
    return detail as T & { code: string; message: string }
  }
  return null
}
