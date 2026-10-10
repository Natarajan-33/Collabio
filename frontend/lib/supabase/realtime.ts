"use client"

import * as React from "react"

import { getSupabaseBrowser } from "@/lib/supabase/browser"

export type BatchDoorbellOptions = {
  /** Poll while true: the safety net for a missed realtime message. */
  live?: boolean
  /** Poll interval while `live`. */
  pollMs?: number
  /** A burst of inserts inside this window rings once. */
  debounceMs?: number
}

/**
 * Rings `onRing` when something may have changed on a batch: an insert into
 * `thread_events` for it (debounced into one ring), the subscription opening (to catch
 * up on anything missed meanwhile), and, while `live`, every `pollMs`. The ring carries
 * no data: the caller refetches. `onRing` may be a new function on every render.
 */
export function useBatchDoorbell(
  batchId: string,
  onRing: () => void,
  { live = false, pollMs = 10_000, debounceMs = 250 }: BatchDoorbellOptions = {}
): void {
  const latest = React.useRef(onRing)
  React.useEffect(() => {
    latest.current = onRing
  })

  React.useEffect(() => {
    const ring = () => latest.current()
    const supabase = getSupabaseBrowser()
    let debounce: ReturnType<typeof setTimeout> | undefined

    const channel = supabase
      .channel(`thread-events:${batchId}`)
      .on(
        "postgres_changes",
        {
          event: "INSERT",
          schema: "public",
          table: "thread_events",
          filter: `batch_id=eq.${batchId}`,
        },
        () => {
          clearTimeout(debounce)
          debounce = setTimeout(ring, debounceMs)
        }
      )
      .subscribe((status) => {
        if (status === "SUBSCRIBED") ring()
      })

    return () => {
      clearTimeout(debounce)
      void supabase.removeChannel(channel)
    }
  }, [batchId, debounceMs])

  React.useEffect(() => {
    if (!live) return
    const poll = setInterval(() => latest.current(), pollMs)
    return () => clearInterval(poll)
  }, [live, pollMs])
}
