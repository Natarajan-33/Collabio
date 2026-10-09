import { createServerClient } from "@supabase/ssr"
import { cookies } from "next/headers"

import { getSupabaseEnv } from "@/lib/supabase/env"

/**
 * The Supabase client for Server Components. It reads the session from the request
 * cookies. Create one per request and never share it: the client holds that request's
 * session.
 */
export async function createSupabaseServer() {
  const cookieStore = await cookies()
  const { url, publishableKey } = getSupabaseEnv()

  return createServerClient(url, publishableKey, {
    cookies: {
      getAll() {
        return cookieStore.getAll()
      },
      setAll(cookiesToSet) {
        try {
          for (const { name, value, options } of cookiesToSet) {
            cookieStore.set(name, value, options)
          }
        } catch {
          // A Server Component cannot set cookies. That is fine: `proxy.ts` has already
          // refreshed the session and written the new cookies on the response.
        }
      },
    },
  })
}
