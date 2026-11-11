import { redirect } from "next/navigation"

import { SessionError } from "@/components/auth/session-error"
import { HackathonLanding } from "@/components/landing/hackathon-landing"
import { getMe } from "@/lib/auth/me"
import { roleHome } from "@/lib/auth/routing"
import { isHackathon } from "@/lib/hackathon"

/** Hackathon mode: the public landing with demo personas. Otherwise send everyone to
 * where they belong. */
export default async function Page({
  searchParams,
}: {
  searchParams?: Promise<{ demo?: string }>
} = {}) {
  if (isHackathon) {
    const { demo } = (await searchParams) ?? {}
    return <HackathonLanding unavailable={demo === "unavailable"} />
  }

  const result = await getMe()

  if (result.kind === "unavailable")
    return <SessionError reason={result.reason} />
  if (result.kind === "anonymous") redirect("/sign-in")
  redirect(result.me.role ? roleHome(result.me.role) : "/onboarding")
}
