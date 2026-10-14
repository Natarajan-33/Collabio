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

/** Which `thread_events` rows ring the bell: those of one batch, or of one creator. */
export type ThreadEventsFilter = {
  column: "batch_id" | "creator_id"
  id: string
}

let channelCount = 0

/**
 * A topic names one channel in the client, and leaving a channel is asynchronous. So every
 * subscription (every run of the effect) gets a topic of its own: creator doorbells are
 * mounted several at once (the rail badge and the page), and React Strict Mode unmounts
 * and remounts an effect at once in development; reusing a topic would hand back (or
 * remove) a channel that is still leaving, and `.on` after `subscribe` throws.
 */
function channelName({ column, id }: ThreadEventsFilter): string {
  channelCount += 1
  const prefix =
    column === "batch_id" ? `thread-events:${id}` : `thread-events:creator:${id}`
  return `${prefix}:${channelCount}`
}

/**
 * Rings `onRing` when something may have changed in the `thread_events` selected by
 * `filter`: an insert (debounced into one ring), the subscription opening (to catch up
 * on anything missed meanwhile), and, while `live`, every `pollMs`. The ring carries
 * no data: the caller refetches. `onRing` may be a new function on every render. With
 * a `null` filter nothing is subscribed (the id is not known yet); polling still runs.
 */
export function useThreadEventsDoorbell(
  filter: ThreadEventsFilter | null,
  onRing: () => void,
  { live = false, pollMs = 10_000, debounceMs = 250 }: BatchDoorbellOptions = {}
): void {
  const latest = React.useRef(onRing)
  React.useEffect(() => {
    latest.current = onRing
  })

  const column = filter?.column
  const id = filter?.id

  React.useEffect(() => {
    if (!column || !id) return
    const ring = () => latest.current()
    const supabase = getSupabaseBrowser()
    let debounce: ReturnType<typeof setTimeout> | undefined

    const channel = supabase
      .channel(channelName({ column, id }))
      .on(
        "postgres_changes",
        {
          event: "INSERT",
          schema: "public",
          table: "thread_events",
          filter: `${column}=eq.${id}`,
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
  }, [column, id, debounceMs])

  React.useEffect(() => {
    if (!live) return
    const poll = setInterval(() => latest.current(), pollMs)
    return () => clearInterval(poll)
  }, [live, pollMs])
}

/** The doorbell for one batch: the brand's board. */
export function useBatchDoorbell(
  batchId: string,
  onRing: () => void,
  options?: BatchDoorbellOptions
): void {
  useThreadEventsDoorbell({ column: "batch_id", id: batchId }, onRing, options)
}

/**
 * The doorbell for one creator across every brand: the Offers inbox, the offer desk and
 * the rail badge. `null` until the creator is known.
 */
export function useCreatorDoorbell(
  creatorId: string | null,
  onRing: () => void,
  options?: BatchDoorbellOptions
): void {
  useThreadEventsDoorbell(
    creatorId ? { column: "creator_id", id: creatorId } : null,
    onRing,
    options
  )
}
