import { act, cleanup, render, screen } from "@testing-library/react"
import { useEffect } from "react"
import { afterEach, describe, expect, it, vi } from "vitest"

import {
  type VoiceContext,
  type VoiceIntent,
  type VoiceRegistry,
  VoiceScreenProvider,
  useVoicePause,
  useVoicePausedReason,
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

describe("voice pause", () => {
  it("a pause reports its reason until it is released", () => {
    const { registry } = setup(null)
    const reg = registry.current!
    expect(reg.pausedReason()).toBeNull()

    const listener = vi.fn()
    reg.subscribe(listener)
    let release!: () => void
    act(() => {
      release = reg.pause("Voice is in the brief conversation")
    })
    expect(reg.pausedReason()).toBe("Voice is in the brief conversation")
    expect(listener).toHaveBeenCalledTimes(1)

    act(() => release())
    expect(reg.pausedReason()).toBeNull()
    expect(listener).toHaveBeenCalledTimes(2)

    // Releasing twice does nothing more.
    act(() => release())
    expect(listener).toHaveBeenCalledTimes(2)
  })

  it("the newest of two pauses is the one shown", () => {
    const { registry } = setup(null)
    const reg = registry.current!
    let first!: () => void
    let second!: () => void
    act(() => {
      first = reg.pause("first")
      second = reg.pause("second")
    })
    expect(reg.pausedReason()).toBe("second")

    act(() => second())
    expect(reg.pausedReason()).toBe("first")
    act(() => first())
    expect(reg.pausedReason()).toBeNull()
  })

  it("an unsubscribed listener hears nothing more", () => {
    const { registry } = setup(null)
    const reg = registry.current!
    const listener = vi.fn()
    const off = reg.subscribe(listener)
    off()
    act(() => {
      reg.pause("x")
    })
    expect(listener).not.toHaveBeenCalled()
  })

  function Pauser({ reason }: { reason: string | null }) {
    useVoicePause(reason)
    return null
  }
  function Reader() {
    return <p data-testid="reason">{useVoicePausedReason() ?? "none"}</p>
  }

  it("useVoicePause pauses while the reason is set and releases on change or unmount", () => {
    const tree = (reason: string | null | undefined) => (
      <VoiceScreenProvider>
        <Reader />
        {reason === undefined ? null : <Pauser reason={reason} />}
      </VoiceScreenProvider>
    )
    const { rerender } = render(tree(null))
    const shown = () => screen.getByTestId("reason").textContent

    expect(shown()).toBe("none")
    rerender(tree("in the call"))
    expect(shown()).toBe("in the call")
    rerender(tree(null))
    expect(shown()).toBe("none")
    rerender(tree("again"))
    expect(shown()).toBe("again")
    rerender(tree(undefined))
    expect(shown()).toBe("none")
  })

  it("useVoicePausedReason is null outside a provider", () => {
    render(<Reader />)
    expect(screen.getByTestId("reason").textContent).toBe("none")
  })

  it("useVoicePause does nothing outside a provider", () => {
    expect(() => render(<Pauser reason="x" />)).not.toThrow()
  })
})
