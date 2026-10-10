"use client"

import { useRouter } from "next/navigation"
import { useState } from "react"
import { CloudOff } from "lucide-react"

import { Button } from "@/components/ui/button"
import { getSupabaseBrowser } from "@/lib/supabase/browser"

const COPY = {
  unreachable: {
    title: "We can't reach Collabio",
    body: "The server isn't answering right now. Your session is fine; give it a moment and try again.",
  },
  error: {
    title: "Something went wrong on our side",
    body: "We couldn't load your account. Try again, and if it keeps happening, sign out and back in.",
  },
} as const

/**
 * Shown instead of the app when the backend cannot say who the user is. Signing the
 * user out would be wrong (the session is probably fine) so retry comes first.
 */
export function SessionError({ reason }: { reason: "unreachable" | "error" }) {
  const router = useRouter()
  const [leaving, setLeaving] = useState(false)
  const copy = COPY[reason]

  async function signOut() {
    setLeaving(true)
    try {
      await getSupabaseBrowser().auth.signOut()
    } catch {
      // Leave for sign-in regardless: the user asked to start over.
    }
    router.replace("/sign-in")
    router.refresh()
  }

  return (
    <div className="flex min-h-[60svh] items-center justify-center px-6">
      <div className="max-w-md text-center">
        <CloudOff
          aria-hidden
          className="mx-auto size-8 text-muted-foreground"
        />
        <h1 className="mt-6 font-display text-4xl leading-[1.05]">
          {copy.title}
        </h1>
        <p className="mt-3 text-muted-foreground">{copy.body}</p>
        <div className="mt-8 flex flex-col justify-center gap-2 sm:flex-row">
          <Button
            size="lg"
            className="h-10 px-5"
            onClick={() => router.refresh()}
          >
            Try again
          </Button>
          <Button
            size="lg"
            variant="outline"
            className="h-10 px-5"
            disabled={leaving}
            onClick={signOut}
          >
            Sign out
          </Button>
        </div>
      </div>
    </div>
  )
}
