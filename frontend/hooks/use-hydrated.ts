"use client"

import { useSyncExternalStore } from "react"

const subscribe = () => () => {}

/**
 * False on the server and while the browser hydrates, true once it is the browser's
 * turn. A page that starts from browser-only state (session storage, say) renders its
 * body only when this is true, so the first render agrees with the server's and the
 * body can read that state directly instead of fixing it up in an effect.
 */
export function useHydrated(): boolean {
  return useSyncExternalStore(
    subscribe,
    () => true,
    () => false
  )
}
