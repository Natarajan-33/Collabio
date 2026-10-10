import { createServerClient } from "@supabase/ssr"
import { type NextRequest, NextResponse } from "next/server"

import { getSupabaseEnv } from "@/lib/supabase/env"

/**
 * Refreshes the Supabase session for one request.
 *
 * Supabase refresh tokens are single use, and a Server Component cannot write the new
 * cookies, so the refresh must happen here, before the page renders. The returned
 * response carries the refreshed cookies: return it (or copy its cookies onto another
 * response, such as a redirect) or the browser keeps the stale ones and gets signed out.
 *
 * `signedIn` comes from the verified JWT claims, not from merely finding a cookie.
 */
export async function updateSession(
  request: NextRequest
): Promise<{ response: NextResponse; signedIn: boolean }> {
  const { url, publishableKey } = getSupabaseEnv()
  let response = NextResponse.next({ request })

  const supabase = createServerClient(url, publishableKey, {
    cookies: {
      getAll() {
        return request.cookies.getAll()
      },
      setAll(cookiesToSet, headers) {
        // Mirror the new cookies onto the request so this render sees them, then onto
        // a fresh response so the browser stores them.
        for (const { name, value } of cookiesToSet) {
          request.cookies.set(name, value)
        }
        response = NextResponse.next({ request })
        for (const { name, value, options } of cookiesToSet) {
          response.cookies.set(name, value, options)
        }
        // Keeps a CDN from caching one user's session cookies for another.
        for (const [key, value] of Object.entries(headers)) {
          response.headers.set(key, value)
        }
      },
    },
  })

  // Do not run code between creating the client and this call: it is what refreshes
  // an expiring session.
  const { data } = await supabase.auth.getClaims()

  return { response, signedIn: Boolean(data?.claims) }
}
