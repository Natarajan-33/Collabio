import { createBrowserClient } from "@supabase/ssr"

/**
 * The Supabase client for Client Components. `createBrowserClient` returns the same
 * instance on every call in the browser, so it holds the one shared auth session.
 */
export function getSupabaseBrowser() {
  // Read as literal `process.env.NEXT_PUBLIC_*` expressions so Next inlines them.
  const url = process.env.NEXT_PUBLIC_SUPABASE_URL
  const publishableKey = process.env.NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY
  if (!url || !publishableKey) {
    throw new Error(
      "NEXT_PUBLIC_SUPABASE_URL and NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY must be set (see frontend/.env.example)"
    )
  }
  return createBrowserClient(url, publishableKey)
}
