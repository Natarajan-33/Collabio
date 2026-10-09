import type { Metadata } from "next"

import { CredentialsForm } from "@/components/auth/credentials-form"
import { demoAccounts } from "@/lib/auth/demo"
import { safeNextPath } from "@/lib/auth/routing"

export const metadata: Metadata = { title: "Sign in" }

export default async function SignInPage({
  searchParams,
}: {
  searchParams: Promise<{ next?: string | string[] }>
}) {
  const { next } = await searchParams

  return (
    <CredentialsForm
      mode="sign-in"
      next={safeNextPath(next)}
      demoAccounts={
        // Read per request from the server's environment, so the hint always matches
        // the accounts the seed was run with. Not NEXT_PUBLIC_: it is not inlined.
        process.env.NEXT_PUBLIC_DEMO_MODE === "1"
          ? demoAccounts({
              brand: process.env.DEMO_BRAND_EMAIL,
              helper: process.env.DEMO_HELPER_EMAIL,
            })
          : []
      }
    />
  )
}
