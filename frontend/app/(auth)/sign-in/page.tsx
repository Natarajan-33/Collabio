import type { Metadata } from "next"

import { CredentialsForm } from "@/components/auth/credentials-form"
import { safeNextPath } from "@/lib/auth/routing"

export const metadata: Metadata = { title: "Sign in" }

export default async function SignInPage({
  searchParams,
}: {
  searchParams: Promise<{ next?: string | string[] }>
}) {
  const { next } = await searchParams

  return (
    <CredentialsForm mode="sign-in" next={safeNextPath(next)} />
  )
}
