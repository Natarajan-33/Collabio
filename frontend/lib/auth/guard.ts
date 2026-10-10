import { redirect } from "next/navigation"

import { getMe, type Me } from "@/lib/auth/me"
import { resolveRoute } from "@/lib/auth/routing"

export type Guard =
  | { kind: "ok"; me: Me }
  | { kind: "unavailable"; reason: "unreachable" | "error" }

/**
 * Lets a Server Component render only if `resolveRoute` allows the signed-in user
 * into `pathname`; otherwise redirects (this does not return). When the backend is
 * down it returns `unavailable` so the caller can show an error state.
 *
 * A layout does not know the URL beneath it, so role layouts pass their own root
 * (`/brand`). The proxy has already sent anonymous visitors on deep links to sign-in
 * with the full path; this is the check that needs the backend.
 */
export async function guardRoute(pathname: string): Promise<Guard> {
  const result = await getMe()
  if (result.kind === "unavailable") return result

  const me = result.kind === "ok" ? result.me : null
  const target = resolveRoute(me, pathname)
  if (target !== null || me === null) redirect(target ?? "/sign-in")
  return { kind: "ok", me }
}
