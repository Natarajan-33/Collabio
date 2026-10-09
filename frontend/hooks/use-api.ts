"use client"

import { useRouter } from "next/navigation"
import { useEffect } from "react"

import { type ApiClient, createApiClient } from "@/lib/api/client"
import { getSupabaseBrowser } from "@/lib/supabase/browser"

type Router = ReturnType<typeof useRouter>

// The client outlives any component, but navigating needs the router that `useRouter`
// only hands to components, so `useApi` keeps the latest router here.
const routerRef: { current: Router | null } = { current: null }
let client: ApiClient | undefined

function getApiClient(): ApiClient {
  if (client) return client

  const baseUrl = process.env.NEXT_PUBLIC_API_URL
  if (!baseUrl) {
    throw new Error(
      "NEXT_PUBLIC_API_URL must be set (see frontend/.env.example)"
    )
  }
  const supabase = getSupabaseBrowser()

  client = createApiClient({
    baseUrl,
    getToken: async () => {
      const { data } = await supabase.auth.getSession()
      return data.session?.access_token ?? null
    },
    refresh: async () => {
      const { data, error } = await supabase.auth.refreshSession()
      return !error && data.session !== null
    },
    onUnauthorized: (path) => {
      const signIn = `/sign-in?next=${encodeURIComponent(path)}`
      if (routerRef.current) routerRef.current.replace(signIn)
      else window.location.replace(signIn)
    },
  })
  return client
}

/** The app's single typed API client, signed in with the current Supabase session. */
export function useApi(): ApiClient {
  const router = useRouter()
  useEffect(() => {
    routerRef.current = router
  }, [router])
  return getApiClient()
}
