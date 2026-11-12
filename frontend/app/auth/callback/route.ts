import { NextResponse, type NextRequest } from "next/server"

import { safeNextPath } from "@/lib/auth/routing"
import { createSupabaseServer } from "@/lib/supabase/server"
import { publicUrl } from "@/lib/http/public-url"

/**
 * Where Supabase sends a confirmed sign-up: swap the one-time `code` for a session
 * (written to cookies), then continue to `next` or `/`, which routes by role.
 */
export async function GET(request: NextRequest) {
  const { searchParams } = request.nextUrl
  const code = searchParams.get("code")

  if (code) {
    const supabase = await createSupabaseServer()
    const { error } = await supabase.auth.exchangeCodeForSession(code)
    if (!error) {
      const next = safeNextPath(searchParams.get("next") ?? undefined)
      return NextResponse.redirect(publicUrl(next, request))
    }
  }

  return NextResponse.redirect(publicUrl("/sign-in?error=confirmation_failed", request))
}
