/**
 * The public Supabase project settings for the server and the proxy. Read as literal
 * `process.env.NEXT_PUBLIC_*` expressions so Next inlines them.
 */
export function getSupabaseEnv(): { url: string; publishableKey: string } {
  const url = process.env.NEXT_PUBLIC_SUPABASE_URL
  const publishableKey = process.env.NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY
  if (!url || !publishableKey) {
    throw new Error(
      "NEXT_PUBLIC_SUPABASE_URL and NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY must be set (see frontend/.env.example)"
    )
  }
  return { url, publishableKey }
}
