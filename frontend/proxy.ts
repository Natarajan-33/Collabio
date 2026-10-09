import { type NextRequest, NextResponse } from "next/server"

import { isGuardedPath, resolveRoute } from "@/lib/auth/routing"
import { updateSession } from "@/lib/supabase/proxy"

// Headers Supabase sets so a CDN never caches one user's session for another.
const CACHE_HEADERS = ["cache-control", "expires", "pragma"]

/**
 * Keeps the Supabase session fresh on every page request and does one optimistic
 * check: an anonymous visitor to a guarded tree is sent to sign-in. Roles are not
 * decided here (that needs the backend); the role layouts do it from `GET /me`.
 */
export async function proxy(request: NextRequest) {
  const { response, signedIn } = await updateSession(request)

  const { pathname, search } = request.nextUrl
  if (signedIn || !isGuardedPath(pathname)) return response

  const target = resolveRoute(null, pathname + search)
  if (!target) return response

  const redirect = NextResponse.redirect(new URL(target, request.url))
  // The refresh may have rewritten or cleared the auth cookies; losing them here would
  // leave the browser holding a dead refresh token.
  for (const cookie of response.cookies.getAll()) redirect.cookies.set(cookie)
  for (const name of CACHE_HEADERS) {
    const value = response.headers.get(name)
    if (value) redirect.headers.set(name, value)
  }
  return redirect
}

export const config = {
  // Every page, so the session is refreshed before any Server Component reads it;
  // static assets and the favicon are skipped. Only `isGuardedPath` redirects.
  // The dot before the extension is `\\.` because this is a plain JS string: a bare
  // `\.` collapses to `.` and would skip pages whose path merely ends in "ico".
  matcher: [
    "/((?!_next/static|_next/image|favicon.ico|.*\\.(?:svg|png|jpg|jpeg|gif|webp|ico)$).*)",
  ],
}
