"use client"

import { useEffect } from "react"
import { toast } from "sonner"

import { consumeWelcomeNotePending } from "@/lib/auth/welcome-note"

function WelcomeNoteBody() {
  return (
    <div className="space-y-3 text-sm leading-relaxed text-foreground">
      <p className="font-semibold">A Note from the Collabio Team</p>
      <p>
        Collabio uses multiple AI services for voice, calling, and messaging. Due to
        current usage limits, some voice features may occasionally not work as expected.
        We sincerely apologize for any inconvenience and appreciate your patience.
      </p>
      <p>
        We&apos;re continuously improving the experience, with subscription plans for
        full access and a free trial for everyone coming soon.
      </p>
      <p className="font-medium">
        Thank you for exploring Collabio and being part of our journey. We truly
        appreciate your support!
      </p>
    </div>
  )
}

/** One-time toast after a new account finishes onboarding. */
export function WelcomeNoteToast() {
  useEffect(() => {
    if (!consumeWelcomeNotePending()) return
    toast(<WelcomeNoteBody />, {
      id: "collabio-welcome-note",
      duration: 30_000,
    })
  }, [])

  return null
}
