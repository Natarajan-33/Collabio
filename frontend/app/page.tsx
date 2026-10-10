import { redirect } from "next/navigation"

import { SessionError } from "@/components/auth/session-error"
import { getMe } from "@/lib/auth/me"
import { roleHome } from "@/lib/auth/routing"

/** No landing page yet: send everyone to where they belong. */
export default async function Page() {
  const result = await getMe()

  if (result.kind === "unavailable")
    return <SessionError reason={result.reason} />
  if (result.kind === "anonymous") redirect("/sign-in")
  redirect(result.me.role ? roleHome(result.me.role) : "/onboarding")
}
