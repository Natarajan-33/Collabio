import { cache } from "react"

import { createApiClient } from "@/lib/api/client"
import type { components } from "@/lib/api/schema"
import { createSupabaseServer } from "@/lib/supabase/server"

export type Me = components["schemas"]["MeResponse"]

export type MeResult =
  | { kind: "ok"; me: Me }
  /** No usable session: signed out, or the backend refused the token. */
  | { kind: "anonymous" }
  /** The backend could not answer, so who the user is stays unknown. */
  | { kind: "unavailable"; reason: "unreachable" | "error" }

// Long enough for a cold backend, short enough that a dead one shows an error state
// instead of a hung page.
const REQUEST_TIMEOUT_MS = 5000

async function fetchMe(): Promise<MeResult> {
  const baseUrl = process.env.NEXT_PUBLIC_API_URL
  if (!baseUrl) {
    throw new Error(
      "NEXT_PUBLIC_API_URL must be set (see frontend/.env.example)"
    )
  }

  // proxy.ts has already refreshed the session, so the token in the cookie is fresh.
  // The backend verifies it; nothing here trusts it.
  const supabase = await createSupabaseServer()
  const { data } = await supabase.auth.getSession()
  const token = data.session?.access_token
  if (!token) return { kind: "anonymous" }

  const api = createApiClient({
    baseUrl,
    getToken: async () => token,
    // A rejected token cannot be repaired on the server: report it as anonymous.
    refresh: async () => false,
    onUnauthorized: () => {},
  })

  try {
    const { data: me, response } = await api.GET("/api/v1/me", {
      signal: AbortSignal.timeout(REQUEST_TIMEOUT_MS),
    })
    if (me) return { kind: "ok", me }
    if (response.status === 401) return { kind: "anonymous" }
    return { kind: "unavailable", reason: "error" }
  } catch {
    // Connection refused, DNS failure or the timeout above.
    return { kind: "unavailable", reason: "unreachable" }
  }
}

/**
 * Who is signed in, from `GET /me` with the session's access token. Cached per request
 * so a layout and its page share one backend call.
 */
export const getMe = cache(fetchMe)
