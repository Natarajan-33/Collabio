import { type NextRequest, NextResponse } from "next/server"

import { isHackathon, isPersona, personaPath } from "@/lib/hackathon"
import { createSupabaseServer } from "@/lib/supabase/server"
import { publicUrl } from "@/lib/http/public-url"

/**
 * `GET /api/demo-login?as=brand|creator` signs in as a seeded demo persona on the server
 * (the shared demo password never reaches the browser) and lands on that persona's deals.
 * Only exists in hackathon mode.
 */
export async function GET(request: NextRequest) {
  const persona = request.nextUrl.searchParams.get("as")
  if (!isHackathon || !isPersona(persona)) {
    return new NextResponse("Not found", { status: 404 })
  }
  const email =
    persona === "brand" ? process.env.DEMO_BRAND_EMAIL : process.env.DEMO_HELPER_EMAIL
  const password = process.env.DEMO_PASSWORD
  if (!email || !password) {
    return new NextResponse("Demo personas are not configured", { status: 503 })
  }

  const supabase = await createSupabaseServer()
  await supabase.auth.signOut()
  const { error } = await supabase.auth.signInWithPassword({ email, password })
  if (error) {
    return NextResponse.redirect(publicUrl("/?demo=unavailable", request))
  }
  return NextResponse.redirect(publicUrl(personaPath(persona), request))
}
