import type { Metadata } from "next"

import { OnboardingFlow } from "@/components/auth/onboarding-flow"
import { SessionError } from "@/components/auth/session-error"
import { guardRoute } from "@/lib/auth/guard"

export const metadata: Metadata = { title: "Welcome" }

export default async function OnboardingPage() {
  // Anonymous visitors go to sign-in and users who already have a role to their app.
  const guard = await guardRoute("/onboarding")
  if (guard.kind === "unavailable")
    return <SessionError reason={guard.reason} />

  return <OnboardingFlow />
}
