import createClient, { type Client } from "openapi-fetch"

import type { paths } from "./schema"

export type ApiClient = Client<paths>

export interface ApiClientOptions {
  baseUrl: string
  /** The current access token, or null when signed out. */
  getToken: () => Promise<string | null>
  /** Refreshes the session; resolves true when a fresh token is available. */
  refresh: () => Promise<boolean>
  /** Called with the page path when the session cannot be recovered. */
  onUnauthorized: (nextPath: string) => void
}

function currentPath(): string {
  return typeof window === "undefined" ? "/" : window.location.pathname
}

/**
 * A typed client for the Collabio API that sends the session's bearer token.
 *
 * A 401 refreshes the session once and replays the request with the new token. If the
 * refresh fails or the replay is still 401, `onUnauthorized` is called with the current
 * path and the 401 response is returned to the caller.
 */
export function createApiClient({
  baseUrl,
  getToken,
  refresh,
  onUnauthorized,
}: ApiClientOptions): ApiClient {
  const client = createClient<paths>({ baseUrl })
  // Sending a request consumes its body, so each request keeps an untouched copy (keyed
  // by openapi-fetch's per-request id) to replay after a refresh.
  const replayable = new Map<string, Request>()

  client.use({
    async onRequest({ request, id }) {
      const token = await getToken()
      replayable.set(id, request.clone())
      if (token) request.headers.set("Authorization", `Bearer ${token}`)
    },
    async onResponse({ response, id, options }) {
      const original = replayable.get(id)
      replayable.delete(id)
      if (response.status !== 401 || !original) return

      if (await refresh()) {
        const token = await getToken()
        if (token) {
          original.headers.set("Authorization", `Bearer ${token}`)
          const retried = await options.fetch(original)
          if (retried.status === 401) onUnauthorized(currentPath())
          return retried
        }
      }
      onUnauthorized(currentPath())
    },
    onError({ id }) {
      replayable.delete(id)
    },
  })

  return client
}
