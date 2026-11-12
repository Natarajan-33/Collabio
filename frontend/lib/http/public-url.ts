/**
 * An absolute URL on the site's public origin. Behind a proxy (Render), a route handler's
 * `request.url` carries the internal address (https://localhost:10000), so redirects built
 * from it send the browser nowhere; the proxy's forwarded host and protocol are the real ones.
 */
export function publicUrl(path: string, request: Request): URL {
  const first = (name: string) => request.headers.get(name)?.split(",")[0]?.trim() || null
  const fallback = new URL(request.url)
  const host = first("x-forwarded-host") ?? first("host")
  if (!host) return new URL(path, fallback)
  const proto = first("x-forwarded-proto") ?? fallback.protocol.replace(":", "")
  return new URL(path, `${proto}://${host}`)
}
