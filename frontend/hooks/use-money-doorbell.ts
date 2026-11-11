"use client"

import * as React from "react"

import { getSupabaseBrowser } from "@/lib/supabase/browser"

/**
 * Rings when money moves on a deal (a `money_events` insert), when the subscription opens,
 * and every `pollMs` while `live` (a verification or payout is in flight: submission and
 * payout updates carry no deal id to filter on). The ring carries no data: refetch.
 */
export function useMoneyDoorbell(
  dealId: string,
  onRing: () => void,
  { live = false, pollMs = 3_000 }: { live?: boolean; pollMs?: number } = {}
): void {
  const latest = React.useRef(onRing)
  React.useEffect(() => {
    latest.current = onRing
  })

  React.useEffect(() => {
    const supabase = getSupabaseBrowser()
    let debounce: ReturnType<typeof setTimeout> | undefined
    // A unique name per subscription: two panels on one deal must not share a channel.
    const channel = supabase
      .channel(`money:${dealId}:${crypto.randomUUID()}`)
      .on(
        "postgres_changes",
        {
          event: "INSERT",
          schema: "public",
          table: "money_events",
          filter: `deal_id=eq.${dealId}`,
        },
        () => {
          clearTimeout(debounce)
          debounce = setTimeout(() => latest.current(), 250)
        }
      )
      .subscribe()
    return () => {
      clearTimeout(debounce)
      void supabase.removeChannel(channel)
    }
  }, [dealId])

  React.useEffect(() => {
    if (!live) return
    const poll = setInterval(() => latest.current(), pollMs)
    return () => clearInterval(poll)
  }, [live, pollMs])
}
