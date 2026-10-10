import { SessionError } from "@/components/auth/session-error"
import { AppShell } from "@/components/shell/app-shell"
import { guardRoute } from "@/lib/auth/guard"

export default async function CreatorLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  // Sends anonymous visitors to sign-in, users without a role to onboarding, and
  // brands to their own app.
  const guard = await guardRoute("/creator")
  if (guard.kind === "unavailable")
    return <SessionError reason={guard.reason} />

  return <AppShell role="creator">{children}</AppShell>
}
