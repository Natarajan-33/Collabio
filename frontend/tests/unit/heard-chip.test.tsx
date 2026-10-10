import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import { HEARD_CHIP_MS, HeardChip } from "@/components/voice/heard-chip"

/** `matchMedia` for GSAP, which jsdom lacks. */
function stubMotionPreference(reduce: boolean) {
  window.matchMedia = ((query: string) => ({
    matches: query.includes("no-preference") ? !reduce : reduce,
    media: query,
    onchange: null,
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    addListener: vi.fn(),
    removeListener: vi.fn(),
    dispatchEvent: vi.fn(),
  })) as typeof window.matchMedia
}

function setup(props: Partial<React.ComponentProps<typeof HeardChip>> = {}) {
  const handlers = {
    onEdit: vi.fn(),
    onSuggest: vi.fn(),
    onDismiss: vi.fn(),
  }
  render(<HeardChip heard="Tech creators" {...handlers} {...props} />)
  return handlers
}

beforeEach(() => stubMotionPreference(true))

afterEach(() => {
  cleanup()
  vi.useRealTimers()
})

describe("HeardChip", () => {
  it("says what was heard, and tapping it hands that text back for editing", async () => {
    const user = userEvent.setup()
    const { onEdit } = setup({ heard: "Tech creators under $2,000" })

    expect(screen.getByText("Heard:")).toBeTruthy()
    await user.click(
      screen.getByRole("button", { name: /Heard: Tech creators under/ })
    )

    expect(onEdit).toHaveBeenCalledExactlyOnceWith("Tech creators under $2,000")
  })

  it("dismisses itself after six seconds", () => {
    vi.useFakeTimers()
    const { onDismiss } = setup()

    act(() => vi.advanceTimersByTime(HEARD_CHIP_MS - 1))
    expect(onDismiss).not.toHaveBeenCalled()

    act(() => vi.advanceTimersByTime(1))
    expect(onDismiss).toHaveBeenCalledTimes(1)
    expect(HEARD_CHIP_MS).toBe(6000)
  })

  it("waits while the pointer is on it, then restarts the clock", () => {
    vi.useFakeTimers()
    const { onDismiss } = setup()
    const chip = screen.getByRole("status")

    act(() => vi.advanceTimersByTime(5000))
    fireEvent.pointerEnter(chip)
    act(() => vi.advanceTimersByTime(20_000))
    expect(onDismiss).not.toHaveBeenCalled()

    fireEvent.pointerLeave(chip)
    act(() => vi.advanceTimersByTime(HEARD_CHIP_MS))
    expect(onDismiss).toHaveBeenCalledTimes(1)
  })

  it("waits while a control inside has keyboard focus", () => {
    vi.useFakeTimers()
    const { onDismiss } = setup()

    act(() => screen.getByRole("button", { name: "Dismiss" }).focus())
    act(() => vi.advanceTimersByTime(20_000))

    expect(onDismiss).not.toHaveBeenCalled()
  })

  it("the close button dismisses at once, and only once", async () => {
    const user = userEvent.setup()
    const { onDismiss } = setup()

    await user.dblClick(screen.getByRole("button", { name: "Dismiss" }))

    expect(onDismiss).toHaveBeenCalledTimes(1)
  })

  it("offers what to say when the command was not understood", async () => {
    const user = userEvent.setup()
    const { onSuggest } = setup({
      suggestions: ["Show me beauty creators", "Select the top ten"],
    })

    expect(screen.getByText("Try saying")).toBeTruthy()
    await user.click(screen.getByRole("button", { name: "Select the top ten" }))

    expect(onSuggest).toHaveBeenCalledExactlyOnceWith("Select the top ten")
  })

  it("shows no suggestions when there are none", () => {
    setup()

    expect(screen.queryByText("Try saying")).toBeNull()
  })

  it("fades out before reporting the dismissal when motion is allowed", async () => {
    stubMotionPreference(false)
    const user = userEvent.setup()
    const { onDismiss } = setup()

    await user.click(screen.getByRole("button", { name: "Dismiss" }))
    // Not instantaneous: the fade-out has to run first.
    expect(onDismiss).not.toHaveBeenCalled()

    await waitFor(() => expect(onDismiss).toHaveBeenCalledTimes(1), {
      timeout: 3000,
    })
  })
})
