export type Role = "brand" | "creator"

/** The part of `GET /me` that decides where a user may go. */
export type RoutingUser = { role: Role | null }

const HOMES = {
  brand: "/brand/discover",
  creator: "/creator/packages",
} as const satisfies Record<Role, string>

/** The first screen of each role's app. */
export function roleHome(role: Role): (typeof HOMES)[Role] {
  return HOMES[role]
}

/** True for `/brand` and everything under it, but not lookalikes such as `/brandon`. */
function isWithin(path: string, root: string): boolean {
  return path === root || path.startsWith(`${root}/`)
}

const GUARDED_ROOTS = ["/brand", "/creator", "/onboarding"]

/** True for the trees that need a signed-in user: both role apps and onboarding. */
export function isGuardedPath(pathname: string): boolean {
  return GUARDED_ROOTS.some((root) => isWithin(pathname, root))
}

/**
 * Where a request for `pathname` should be sent instead, or `null` when the user may
 * stay. `me` is null for an anonymous visitor. `pathname` may carry a query string,
 * which is kept in the sign-in `next` target and ignored for matching.
 *
 * Only call this for the guarded trees (`/brand`, `/creator`, `/onboarding`): an
 * anonymous visitor is always sent to sign-in.
 */
export function resolveRoute(
  me: RoutingUser | null,
  pathname: string
): string | null {
  if (!me) return `/sign-in?next=${encodeURIComponent(pathname)}`

  const path = pathname.split(/[?#]/, 1)[0]

  if (me.role === null) {
    return isWithin(path, "/onboarding") ? null : "/onboarding"
  }
  if (isWithin(path, "/onboarding")) return roleHome(me.role)
  if (me.role === "brand" && isWithin(path, "/creator")) {
    return roleHome("brand")
  }
  if (me.role === "creator" && isWithin(path, "/brand")) {
    return roleHome("creator")
  }
  return null
}

const AUTH_PAGES = ["/sign-in", "/sign-up"]
const SAFE_ORIGIN = "http://collabio.invalid"

/**
 * The page to land on after signing in, from the untrusted `next` query value.
 * Only in-app paths are kept (never another origin) and the auth pages themselves are
 * refused so a user is not bounced back to sign-in. Anything else becomes `/`, which
 * routes the user to their home.
 */
export function safeNextPath(next: string | string[] | undefined): string {
  const value = Array.isArray(next) ? next[0] : next
  if (!value || !value.startsWith("/")) return "/"

  let url: URL
  try {
    // Parsing against a throwaway origin catches `//host` and `/\host`, which a
    // browser would treat as another site.
    url = new URL(value, SAFE_ORIGIN)
  } catch {
    return "/"
  }
  if (url.origin !== SAFE_ORIGIN) return "/"
  if (AUTH_PAGES.some((page) => isWithin(url.pathname, page))) return "/"
  return value
}
