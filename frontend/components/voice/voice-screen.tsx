"use client"

import * as React from "react"

import type { components } from "@/lib/api/schema"

export type VoiceScreen = components["schemas"]["VoiceCommandRequest"]["screen"]
export type VoiceContext = components["schemas"]["VoiceContext"]
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
}

function createRegistry(): VoiceRegistry {
  const handles: VoiceScreenHandle[] = []
  return {
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
