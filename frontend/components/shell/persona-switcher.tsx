"use client"

import * as React from "react"
import { RotateCcw, Users } from "lucide-react"
import { toast } from "sonner"

import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover"
import { clearDiscoverSession } from "@/lib/discover/state"
import { PERSONAS, type Persona } from "@/lib/hackathon"
import { getSupabaseBrowser } from "@/lib/supabase/browser"
import { cn } from "@/lib/utils"

/**
 * Hackathon mode's replacement for "Sign out": jump between the two demo personas, or
 * reset the demo deals to their seeded state.
 */
export function PersonaSwitcher({
  current,
  className,
}: {
  current: Persona
  className?: string
}) {
  const [busy, setBusy] = React.useState(false)

  function switchTo(persona: Persona) {
    clearDiscoverSession()
    // A full navigation on purpose: the route handler sets the new session cookies.
    // eslint-disable-next-line @next/next/no-location-assign-relative-destination
    window.location.assign(`/api/demo-login?as=${persona}`)
  }

  async function resetDemo() {
    setBusy(true)
    try {
      const { data } = await getSupabaseBrowser().auth.getSession()
      const res = await fetch(`${process.env.NEXT_PUBLIC_API_URL}/api/v1/demo/reset`, {
        method: "POST",
        headers: { Authorization: `Bearer ${data.session?.access_token ?? ""}` },
      })
      if (res.status === 429) toast.error("The demo was just reset. Try again in a minute.")
      else if (!res.ok) toast.error("Could not reset the demo.")
      else {
        toast.success("Demo deals restored.")
        window.location.reload()
      }
    } finally {
      setBusy(false)
    }
  }

  return (
    <Popover>
      <PopoverTrigger
        render={
          <button
            type="button"
            className={cn(
              className,
              "text-muted-foreground hover:bg-sidebar-accent hover:text-sidebar-foreground"
            )}
          />
        }
      >
        <Users className="size-5" aria-hidden />
        Persona
      </PopoverTrigger>
      <PopoverContent side="right" sideOffset={8} className="w-60 p-2">
        <p className="px-2 py-1 text-xs text-muted-foreground">
          You are {PERSONAS[current].short} ({PERSONAS[current].role.toLowerCase()})
        </p>
        {(Object.keys(PERSONAS) as Persona[]).map((persona) => (
          <button
            key={persona}
            type="button"
            disabled={persona === current}
            onClick={() => switchTo(persona)}
            className="flex w-full rounded-md px-2 py-2 text-left text-sm hover:bg-muted disabled:opacity-50"
          >
            {PERSONAS[persona].label}
          </button>
        ))}
        <button
          type="button"
          disabled={busy}
          onClick={resetDemo}
          className="mt-1 flex w-full items-center gap-2 rounded-md border-t border-border px-2 py-2 text-left text-sm hover:bg-muted disabled:opacity-50"
        >
          <RotateCcw className="size-4" aria-hidden />
          Reset demo
        </button>
      </PopoverContent>
    </Popover>
  )
}
