import { cleanup, render } from "@testing-library/react"
import { useEffect } from "react"
import { afterEach, describe, expect, it, vi } from "vitest"

import {
  type VoiceContext,
  type VoiceIntent,
  type VoiceRegistry,
  VoiceScreenProvider,
  useVoiceRegistry,
  useVoiceScreen,
} from "@/components/voice/voice-screen"

afterEach(cleanup)

const intent: VoiceIntent = {
  kind: "clear_selection",
  heard: "Clear",
  suggestions: [],
}
const nothing: VoiceContext = { visible_creators: [] }

type RegistryHolder = { current: VoiceRegistry | null }

/** Hands the dock-side registry to the test. */
function Registry({
  onRegistry,
}: {
  onRegistry: (registry: VoiceRegistry | null) => void
}) {
  const registry = useVoiceRegistry()
  useEffect(() => {
    onRegistry(registry)
  })
  return null
}

function Screen({
  name,
  context = nothing,
  onIntent = vi.fn(),
}: {
  name: "discover" | "review" | "packages"
  context?: VoiceContext
  onIntent?: (intent: VoiceIntent) => void
}) {
  useVoiceScreen(name, () => context, onIntent)
  return null
}

function setup(page: React.ReactNode) {
  const registry: RegistryHolder = { current: null }
  const view = render(
    <VoiceScreenProvider>
      <Registry onRegistry={(r) => (registry.current = r)} />
      {page}
    </VoiceScreenProvider>
  )
  return { registry, ...view }
}

describe("useVoiceScreen", () => {
  it("registers the page while it is mounted", () => {
    const { registry, rerender } = setup(<Screen name="discover" />)

    expect(registry.current?.current()?.screen).toBe("discover")

    rerender(
      <VoiceScreenProvider>
        <Registry onRegistry={(r) => (registry.current = r)} />
      </VoiceScreenProvider>
    )
    expect(registry.current?.current()).toBeNull()
  })

  it("answers with the page's current context and intent handler, however often it re-renders", () => {
    const first = vi.fn()
    const second = vi.fn()
    const creators = {
      visible_creators: [{ id: "a", name: "Priya", handle: "priya" }],
    }
    const { registry, rerender } = setup(
      <Screen name="discover" onIntent={first} />
    )

    rerender(
      <VoiceScreenProvider>
        <Registry onRegistry={(r) => (registry.current = r)} />
        <Screen name="discover" context={creators} onIntent={second} />
      </VoiceScreenProvider>
    )
    const page = registry.current?.current()
    page?.onIntent(intent)

    expect(page?.getContext()).toEqual(creators)
    expect(second).toHaveBeenCalledExactlyOnceWith(intent)
    expect(first).not.toHaveBeenCalled()
  })

  it("a page that mounts later takes over, and the earlier one returns when it leaves", () => {
    const registry: RegistryHolder = { current: null }
    const tree = (review: boolean) => (
      <VoiceScreenProvider>
        <Registry onRegistry={(r) => (registry.current = r)} />
        <Screen name="discover" />
        {review ? <Screen name="review" /> : null}
      </VoiceScreenProvider>
    )
    const { rerender } = render(tree(false))
    expect(registry.current?.current()?.screen).toBe("discover")

    rerender(tree(true))
    expect(registry.current?.current()?.screen).toBe("review")

    rerender(tree(false))
    expect(registry.current?.current()?.screen).toBe("discover")
  })

  it("keeps one registration when the page re-renders", () => {
    const { registry, rerender } = setup(<Screen name="packages" />)
    const before = registry.current?.current()

    rerender(
      <VoiceScreenProvider>
        <Registry onRegistry={(r) => (registry.current = r)} />
        <Screen name="packages" />
      </VoiceScreenProvider>
    )

    expect(registry.current?.current()).toBe(before)
  })

  it("does nothing outside a provider", () => {
    expect(() => render(<Screen name="discover" />)).not.toThrow()
  })
})
