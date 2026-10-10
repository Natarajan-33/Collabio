import { render } from "@testing-library/react"
import { afterEach, describe, expect, it, vi } from "vitest"

import { ThemeProvider } from "@/components/theme-provider"

type KeyHandler = (event: KeyboardEvent) => void

function captureKeydownHandler(): KeyHandler {
  // next-themes reads the system preference; jsdom has no matchMedia.
  vi.stubGlobal(
    "matchMedia",
    vi.fn(() => ({
      matches: false,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      addListener: vi.fn(),
      removeListener: vi.fn(),
    }))
  )
  const spy = vi.spyOn(window, "addEventListener")
  render(
    <ThemeProvider>
      <div />
    </ThemeProvider>
  )
  const call = spy.mock.calls.find(([type]) => type === "keydown")
  if (!call) throw new Error("ThemeProvider registered no keydown listener")
  return call[1] as KeyHandler
}

describe("ThemeProvider hotkey", () => {
  afterEach(() => {
    vi.restoreAllMocks()
    vi.unstubAllGlobals()
  })

  it("ignores keydown events that carry no key (browser autofill)", () => {
    const onKeyDown = captureKeydownHandler()
    // Chrome's password autofill dispatches a plain Event typed "keydown": no `key`.
    const autofill = new Event("keydown") as KeyboardEvent

    expect(() => onKeyDown(autofill)).not.toThrow()
  })
})
