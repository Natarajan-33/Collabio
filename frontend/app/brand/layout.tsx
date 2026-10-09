import { SessionError } from "@/components/auth/session-error"
import { AppShell } from "@/components/shell/app-shell"
import { guardRoute } from "@/lib/auth/guard"

export default async function BrandLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  // Sends anonymous visitors to sign-in, users without a role to onboarding, and
  // creators to their own app.
  const guard = await guardRoute("/brand")
  if (guard.kind === "unavailable")
    return <SessionError reason={guard.reason} />

  return <AppShell role="brand">{children}</AppShell>
}
