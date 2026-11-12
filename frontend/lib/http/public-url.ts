/**
 * An absolute URL on the site's public origin. Behind a proxy (Render), a route handler's
 * `request.url` and Host carry the internal address (https://localhost:10000), so redirects
 * built from them send the browser nowhere. The configured public origin wins
 * (`PUBLIC_SITE_URL`, else Render's own `RENDER_EXTERNAL_URL`), then a proxy's forwarded
 * host and protocol, then the request URL (local development).
 */
export function publicUrl(path: string, request: Request): URL {
  const configured = process.env.PUBLIC_SITE_URL || process.env.RENDER_EXTERNAL_URL
  if (configured) return new URL(path, configured)
  const first = (name: string) => request.headers.get(name)?.split(",")[0]?.trim() || null
  const fallback = new URL(request.url)
  const host = first("x-forwarded-host") ?? first("host")
  if (!host) return new URL(path, fallback)
  const proto = first("x-forwarded-proto") ?? fallback.protocol.replace(":", "")
  return new URL(path, `${proto}://${host}`)
}
