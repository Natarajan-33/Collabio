"use client"

import * as React from "react"

import type { components } from "@/lib/api/schema"

export type VoiceScreen = components["schemas"]["VoiceCommandRequest"]["screen"]
type VoiceContextSchema = components["schemas"]["VoiceContext"]
/** What a page reports; the lists a page has nothing to say about can be left out. */
export type VoiceContext = Omit<VoiceContextSchema, "visible_offers"> & {
  visible_offers?: VoiceContextSchema["visible_offers"]
}
export type VoiceIntent = components["schemas"]["VoiceIntent"]

/** What a page tells the dock about itself while it is on screen. */
export type VoiceScreenHandle = {
  /** Picks which intents the router may return. */
  screen: VoiceScreen
  /** What is on screen now: asked for at the moment a command is sent. */
  getContext: () => VoiceContext
  /** Receives every routed intent except `unclear`, which the dock shows itself. */
  onIntent: (intent: VoiceIntent) => void
}

export type VoiceRegistry = {
  /** Makes `handle` the active screen. Returns the function that withdraws it. */
  register: (handle: VoiceScreenHandle) => () => void
  /** The active screen: the latest registered one that is still mounted. */
  current: () => VoiceScreenHandle | null
  /**
   * Stops the dock listening, for `reason`, until the returned function is called.
   * Pauses stack: the newest reason is the one shown.
   */
  pause: (reason: string) => () => void
  /** Why the dock is paused, or null when it is not. */
  pausedReason: () => string | null
  /** Calls `listener` whenever the pause state changes. Returns the unsubscribe. */
  subscribe: (listener: () => void) => () => void
}

function createRegistry(): VoiceRegistry {
  const handles: VoiceScreenHandle[] = []
  const pauses: { reason: string }[] = []
  const listeners = new Set<() => void>()
  const notify = () => listeners.forEach((listener) => listener())

  return {
    pause(reason) {
      const pause = { reason }
      pauses.push(pause)
      notify()
      return () => {
        const at = pauses.indexOf(pause)
        if (at < 0) return
        pauses.splice(at, 1)
        notify()
      }
    },
    pausedReason: () => pauses.at(-1)?.reason ?? null,
    subscribe(listener) {
      listeners.add(listener)
      return () => {
        listeners.delete(listener)
      }
    },
    register(handle) {
      handles.push(handle)
      return () => {
        const at = handles.lastIndexOf(handle)
        if (at >= 0) handles.splice(at, 1)
      }
    },
    current: () => handles.at(-1) ?? null,
  }
}

const RegistryContext = React.createContext<VoiceRegistry | null>(null)

/** Connects the pages inside it to the dock that sits beside them. */
export function VoiceScreenProvider({
  children,
}: {
  children: React.ReactNode
}) {
  const [registry] = React.useState(createRegistry)
  return <RegistryContext value={registry}>{children}</RegistryContext>
}

/** The dock's side: the registry of the page currently on screen, if mounted in one. */
export function useVoiceRegistry(): VoiceRegistry | null {
  return React.useContext(RegistryContext)
}

/**
 * Makes the calling page the voice target while it is mounted. The dock posts
 * `{ screen, transcript, context: getContext() }` and hands the result to `onIntent`.
 *
 * `getContext` and `onIntent` may be new functions on every render: the latest ones
 * are used. Outside a `VoiceScreenProvider` this does nothing, so a page renders the
 * same in isolation.
 */
export function useVoiceScreen(
  screen: VoiceScreen,
  getContext: () => VoiceContext,
  onIntent: (intent: VoiceIntent) => void
): void {
  const registry = useVoiceRegistry()
  const latest = React.useRef({ getContext, onIntent })

  React.useEffect(() => {
    latest.current = { getContext, onIntent }
  })

  React.useEffect(() => {
    if (!registry) return
    return registry.register({
      screen,
      getContext: () => latest.current.getContext(),
      onIntent: (intent) => latest.current.onIntent(intent),
    })
  }, [registry, screen])
}

const NEVER = () => () => {}
const NOT_PAUSED = () => null

/**
 * Keeps the dock from listening while `reason` is non-null, and shows the reason
 * there. Releases when the reason changes or the caller unmounts. Outside a
 * `VoiceScreenProvider` this does nothing.
 */
export function useVoicePause(reason: string | null): void {
  const registry = useVoiceRegistry()

  React.useEffect(() => {
    if (!registry || reason === null) return
    return registry.pause(reason)
  }, [registry, reason])
}

/** Why the dock is paused, or null. Always null outside a `VoiceScreenProvider`. */
export function useVoicePausedReason(): string | null {
  const registry = useVoiceRegistry()
  return React.useSyncExternalStore(
    registry ? registry.subscribe : NEVER,
    registry ? registry.pausedReason : NOT_PAUSED,
    NOT_PAUSED
  )
}
