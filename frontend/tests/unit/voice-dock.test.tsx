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

import { VoiceDock } from "@/components/voice/voice-dock"
import {
  VoiceScreenProvider,
  useVoiceScreen,
  type VoiceContext,
  type VoiceIntent,
} from "@/components/voice/voice-screen"
import type { CommandCaptureOptions } from "@/lib/voice/use-command-capture"

const h = vi.hoisted(() => ({
  capture: { start: vi.fn(), stop: vi.fn(), status: "disconnected" },
  options: null as unknown,
  api: { POST: vi.fn() },
  reduced: { current: true },
  toastError: vi.fn(),
}))

/** The options the dock passed to `useCommandCapture`: how tests play the microphone. */
function capture() {
  return h.options as CommandCaptureOptions
}

vi.mock("@/lib/voice/use-command-capture", () => ({
  useCommandCapture: (options: unknown) => {
    h.options = options
    return h.capture
  },
}))
vi.mock("@/hooks/use-api", () => ({ useApi: () => h.api }))
vi.mock("sonner", () => ({ toast: { error: h.toastError } }))
vi.mock("motion/react", () => ({ useReducedMotion: () => h.reduced.current }))
// Never WebGL in unit tests: the dynamic Orb becomes a marker that shows its props.
vi.mock("next/dynamic", () => ({
  default: () =>
    function OrbStub(props: {
      agentState: string | null
      colors: [string, string]
    }) {
      return (
        <div
          data-testid="orb"
          data-agent-state={props.agentState ?? "none"}
          data-colors={props.colors.join(",")}
        />
      )
    },
}))

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

const CREATORS = [
  {
    id: "5b2f7f0e-0000-4000-8000-000000000001",
    name: "Priya",
    handle: "priya",
  },
]
const pageContext: VoiceContext = { visible_creators: CREATORS }

function intent(over: Partial<VoiceIntent> = {}): VoiceIntent {
  return { kind: "search", heard: "Tech creators", suggestions: [], ...over }
}

function ok(data: VoiceIntent) {
  return { data, response: { status: 200 } }
}

function Page({
  onIntent,
  screen: voiceScreen = "discover",
}: {
  onIntent: (intent: VoiceIntent) => void
  screen?: "discover" | "review" | "packages" | "any"
}) {
  useVoiceScreen(voiceScreen, () => pageContext, onIntent)
  return <input aria-label="Page field" />
}

function renderDock(onIntent: (intent: VoiceIntent) => void = vi.fn()) {
  return render(
    <VoiceScreenProvider>
      <Page onIntent={onIntent} />
      <VoiceDock />
    </VoiceScreenProvider>
  )
}

const space = { key: " ", code: "Space" }

beforeEach(() => {
  h.capture.start.mockReset().mockResolvedValue(undefined)
  h.capture.stop.mockReset()
  h.api.POST.mockReset()
  h.toastError.mockReset()
  h.options = null
  h.reduced.current = true
  stubMotionPreference(true)
})

afterEach(cleanup)

describe("VoiceDock: starting and stopping a capture", () => {
  it("holding space outside inputs starts, releasing stops", () => {
    renderDock()

    // Not prevented would scroll the page; the dock takes the key.
    expect(fireEvent.keyDown(document.body, space)).toBe(false)
    expect(h.capture.start).toHaveBeenCalledTimes(1)

    // Auto-repeat of the held key neither restarts nor scrolls.
    expect(fireEvent.keyDown(document.body, { ...space, repeat: true })).toBe(
      false
    )
    expect(h.capture.start).toHaveBeenCalledTimes(1)
    expect(h.capture.stop).not.toHaveBeenCalled()

    expect(fireEvent.keyUp(document.body, space)).toBe(false)
    expect(h.capture.stop).toHaveBeenCalledTimes(1)
  })

  it("space inside input does not start capture", async () => {
    const user = userEvent.setup()
    renderDock()
    const field = screen.getByLabelText("Page field") as HTMLInputElement

    await user.click(field)
    await user.keyboard(" ")

    expect(h.capture.start).not.toHaveBeenCalled()
    expect(field.value).toBe(" ")
  })

  it.each([
    ["a textarea", () => document.createElement("textarea")],
    ["a select", () => document.createElement("select")],
    [
      "an editable region",
      () => {
        const div = document.createElement("div")
        div.setAttribute("contenteditable", "true")
        return div
      },
    ],
  ])("space in %s does not start capture", (_name, make) => {
    renderDock()
    const el = make()
    document.body.append(el)

    fireEvent.keyDown(el, space)

    expect(h.capture.start).not.toHaveBeenCalled()
    el.remove()
  })

  it("leaves chorded space alone", () => {
    renderDock()

    fireEvent.keyDown(document.body, { ...space, ctrlKey: true })
    fireEvent.keyDown(document.body, { ...space, metaKey: true })

    expect(h.capture.start).not.toHaveBeenCalled()
  })

  it("leaves space to the dock's own buttons, so they can still be pressed", () => {
    renderDock()

    fireEvent.keyDown(
      screen.getByRole("button", { name: "Type a command instead" }),
      space
    )

    expect(h.capture.start).not.toHaveBeenCalled()
  })

  it("space on the focused orb is push-to-talk like anywhere else", () => {
    renderDock()
    const orb = screen.getByRole("button", { name: "Hold to speak" })

    fireEvent.keyDown(orb, space)
    expect(h.capture.start).toHaveBeenCalledTimes(1)

    // The release is not also taken as a click on the button.
    expect(fireEvent.keyUp(orb, space)).toBe(false)
    expect(h.capture.stop).toHaveBeenCalledTimes(1)
  })

  it("ignores a key release that no capture is waiting for", () => {
    renderDock()

    expect(fireEvent.keyUp(document.body, space)).toBe(true)
    expect(h.capture.stop).not.toHaveBeenCalled()
  })

  it("press-and-hold on the orb starts, letting go stops", async () => {
    const user = userEvent.setup()
    renderDock()
    const orb = screen.getByRole("button", { name: "Hold to speak" })

    await user.pointer({ keys: "[MouseLeft>]", target: orb })
    expect(h.capture.start).toHaveBeenCalledTimes(1)
    expect(h.capture.stop).not.toHaveBeenCalled()

    await user.pointer({ keys: "[/MouseLeft]" })
    expect(h.capture.stop).toHaveBeenCalledTimes(1)
  })

  it("stops when the window loses focus mid-hold, so the key release is not missed", () => {
    renderDock()
    fireEvent.keyDown(document.body, space)

    fireEvent.blur(window)

    expect(h.capture.stop).toHaveBeenCalledTimes(1)
  })

  it("does not start a second capture while one is running", () => {
    renderDock()
    fireEvent.keyDown(document.body, space)
    act(() => capture().onConnected?.())

    fireEvent.keyUp(document.body, space)
    act(() => capture().onFinal(""))
    fireEvent.keyDown(document.body, space)

    // The new press is fine once the first is over...
    expect(h.capture.start).toHaveBeenCalledTimes(2)
    // ...but not while it is still held.
    fireEvent.keyDown(document.body, space)
    expect(h.capture.start).toHaveBeenCalledTimes(2)
  })
})

describe("VoiceDock: what it shows", () => {
  it("shows the live transcript while listening", () => {
    renderDock()
    expect(screen.getByText("Hold Space to speak")).toBeTruthy()

    fireEvent.keyDown(document.body, space)
    expect(screen.getByText("Connecting…")).toBeTruthy()

    act(() => capture().onConnected?.())
    expect(screen.getByText("Listening…")).toBeTruthy()

    act(() => capture().onPartial("tech creators"))
    act(() => capture().onPartial("tech creators under two thousand"))
    expect(screen.getByText("tech creators under two thousand")).toBeTruthy()
  })

  it("releasing with nothing heard goes back to idle without routing", () => {
    renderDock()
    fireEvent.keyDown(document.body, space)
    act(() => capture().onConnected?.())
    fireEvent.keyUp(document.body, space)

    act(() => capture().onFinal("  "))

    expect(h.api.POST).not.toHaveBeenCalled()
    expect(screen.getByText("Hold Space to speak")).toBeTruthy()
  })

  it("maps the dock's mode onto the Orb and mounts it only while working", () => {
    h.reduced.current = false
    renderDock()
    // Idle: a static disc, no WebGL.
    expect(screen.queryByTestId("orb")).toBeNull()

    fireEvent.keyDown(document.body, space)
    expect(screen.getByTestId("orb").dataset.agentState).toBe("thinking")

    act(() => capture().onConnected?.())
    expect(screen.getByTestId("orb").dataset.agentState).toBe("listening")
    // The ember --voice ramp, not the Orb's default blue.
    expect(screen.getByTestId("orb").dataset.colors).toBe("#f6623d,#ffaf76")

    h.api.POST.mockReturnValue(new Promise(() => {}))
    fireEvent.keyUp(document.body, space)
    act(() => capture().onFinal("hello"))
    expect(screen.getByTestId("orb").dataset.agentState).toBe("thinking")
  })

  it("never mounts the Orb under reduced motion", () => {
    h.reduced.current = true
    renderDock()

    fireEvent.keyDown(document.body, space)
    act(() => capture().onConnected?.())

    expect(screen.queryByTestId("orb")).toBeNull()
    expect(screen.getByText("Listening…")).toBeTruthy()
  })

  it("is visible at once under reduced motion", () => {
    renderDock()

    expect(
      screen.getByRole("group", { name: "Voice commands" }).style.opacity
    ).toBe("1")
  })

  it("rises in with a tween otherwise", async () => {
    stubMotionPreference(false)
    renderDock()
    const dock = screen.getByRole("group", { name: "Voice commands" })

    // It starts transparent and the tween brings it up.
    expect(Number(dock.style.opacity)).toBeLessThan(1)
    await waitFor(() => expect(dock.style.opacity).toBe("1"), { timeout: 3000 })
  })
})

describe("VoiceDock: routing a command", () => {
  async function speak(text: string) {
    fireEvent.keyDown(document.body, space)
    act(() => capture().onConnected?.())
    act(() => capture().onPartial(text))
    fireEvent.keyUp(document.body, space)
    await act(async () => capture().onFinal(text))
  }

  it("routed intent is delivered to the registered screen handler", async () => {
    const onIntent = vi.fn()
    const routed = intent({
      kind: "search",
      heard: "Tech creators under $2,000",
    })
    h.api.POST.mockResolvedValue(ok(routed))
    renderDock(onIntent)

    await speak("tech creators under two thousand")

    // The page's screen and what it shows go along with the words.
    expect(h.api.POST).toHaveBeenCalledWith("/api/v1/voice/command", {
      body: {
        screen: "discover",
        transcript: "tech creators under two thousand",
        context: pageContext,
      },
    })
    expect(onIntent).toHaveBeenCalledExactlyOnceWith(routed)
    expect(screen.getByText("Tech creators under $2,000")).toBeTruthy()
    expect(screen.getByText("Heard:")).toBeTruthy()
  })

  it("asks for the page's context when the command is sent, not when it mounted", async () => {
    let visible = CREATORS
    function Changing() {
      useVoiceScreen("discover", () => ({ visible_creators: visible }), vi.fn())
      return null
    }
    h.api.POST.mockResolvedValue(ok(intent()))
    render(
      <VoiceScreenProvider>
        <Changing />
        <VoiceDock />
      </VoiceScreenProvider>
    )
    visible = []

    await speak("who is here")

    expect(h.api.POST.mock.calls[0][1].body.context.visible_creators).toEqual(
      []
    )
  })

  it("sends the latest screen when pages replace each other", async () => {
    h.api.POST.mockResolvedValue(ok(intent()))
    const { rerender } = render(
      <VoiceScreenProvider>
        <Page onIntent={vi.fn()} screen="discover" />
        <VoiceDock />
      </VoiceScreenProvider>
    )
    rerender(
      <VoiceScreenProvider>
        <Page onIntent={vi.fn()} screen="review" />
        <VoiceDock />
      </VoiceScreenProvider>
    )

    await speak("open review")

    expect(h.api.POST.mock.calls[0][1].body.screen).toBe("review")
  })

  it("routes as 'any' with no context when no page has registered", async () => {
    h.api.POST.mockResolvedValue(
      ok(intent({ kind: "navigate", navigate: "/x" }))
    )
    render(
      <VoiceScreenProvider>
        <VoiceDock />
      </VoiceScreenProvider>
    )

    await speak("go to discover")

    expect(h.api.POST.mock.calls[0][1].body).toMatchObject({
      screen: "any",
      context: { visible_creators: [] },
    })
    expect(screen.getByText("Heard:")).toBeTruthy()
  })

  it("works outside any provider too", async () => {
    h.api.POST.mockResolvedValue(ok(intent()))
    render(<VoiceDock />)

    await speak("hello")

    expect(h.api.POST.mock.calls[0][1].body.screen).toBe("any")
  })

  it("an unclear command is not an error: it shows what was heard and what to say", async () => {
    const onIntent = vi.fn()
    h.api.POST.mockResolvedValue(
      ok(
        intent({
          kind: "unclear",
          heard: "Blue banana",
          suggestions: ["Show me beauty creators", "Select the top ten"],
        })
      )
    )
    renderDock(onIntent)

    await speak("blue banana")

    expect(screen.getByText("Blue banana")).toBeTruthy()
    expect(screen.getByText("Show me beauty creators")).toBeTruthy()
    expect(screen.getByText("Select the top ten")).toBeTruthy()
    expect(screen.queryByRole("alert")).toBeNull()
    expect(h.toastError).not.toHaveBeenCalled()
    // Nothing for the page to do.
    expect(onIntent).not.toHaveBeenCalled()
  })

  it("tapping a suggestion sends it as the command", async () => {
    const user = userEvent.setup()
    const onIntent = vi.fn()
    h.api.POST.mockResolvedValueOnce(
      ok(
        intent({
          kind: "unclear",
          heard: "Blue",
          suggestions: ["Select the top ten"],
        })
      )
    ).mockResolvedValueOnce(
      ok(intent({ kind: "select", heard: "Select the top ten" }))
    )
    renderDock(onIntent)
    await speak("blue")

    await user.click(screen.getByRole("button", { name: "Select the top ten" }))

    await waitFor(() => expect(onIntent).toHaveBeenCalledTimes(1))
    expect(h.api.POST.mock.calls[1][1].body.transcript).toBe(
      "Select the top ten"
    )
  })

  it("does not hand a result to a page that is no longer on screen", async () => {
    const onIntent = vi.fn()
    let resolve!: (value: unknown) => void
    h.api.POST.mockReturnValue(new Promise((r) => (resolve = r)))
    const withPage = (shown: boolean) => (
      <VoiceScreenProvider>
        {shown ? <Page onIntent={onIntent} /> : null}
        <VoiceDock />
      </VoiceScreenProvider>
    )
    const { rerender } = render(withPage(true))
    await speak("tech creators")

    // The user navigates away while the router is thinking.
    rerender(withPage(false))
    await act(async () => resolve(ok(intent())))

    expect(onIntent).not.toHaveBeenCalled()
    expect(screen.getByText("Heard:")).toBeTruthy()
  })

  it("a throwing page does not break the dock", async () => {
    const error = vi.spyOn(console, "error").mockImplementation(() => {})
    h.api.POST.mockResolvedValue(ok(intent()))
    renderDock(() => {
      throw new Error("page bug")
    })

    await speak("tech creators")

    expect(screen.getByText("Heard:")).toBeTruthy()
    expect(error).toHaveBeenCalled()
    error.mockRestore()
  })

  it.each([
    [503, "Voice is unavailable right now"],
    [401, "Your session expired"],
    [422, "Couldn't process that command"],
  ])("a %s from the router is shown as a failure", async (status, message) => {
    h.api.POST.mockResolvedValue({ error: {}, response: { status } })
    renderDock()

    await speak("tech creators")

    expect((await screen.findByRole("alert")).textContent).toBe(message)
    expect(screen.queryByText("Heard:")).toBeNull()
  })

  it("a network failure is shown as a failure", async () => {
    h.api.POST.mockRejectedValue(new TypeError("fetch failed"))
    renderDock()

    await speak("tech creators")

    expect((await screen.findByRole("alert")).textContent).toBe(
      "Couldn't reach Collabio"
    )
  })

  it("keeps the words of a failed command for a retry by typing", async () => {
    const user = userEvent.setup()
    h.api.POST.mockResolvedValue({ error: {}, response: { status: 503 } })
    renderDock()
    await speak("tech creators")
    await screen.findByRole("alert")

    await user.click(
      screen.getByRole("button", { name: "Type a command instead" })
    )

    expect(
      (screen.getByLabelText("Type a command") as HTMLInputElement).value
    ).toBe("tech creators")
  })

  it("the failure clears itself", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    try {
      h.api.POST.mockResolvedValue({ error: {}, response: { status: 503 } })
      renderDock()
      await speak("tech creators")
      await screen.findByRole("alert")

      await act(async () => {
        vi.advanceTimersByTime(6000)
      })

      expect(screen.queryByRole("alert")).toBeNull()
      expect(screen.getByText("Hold Space to speak")).toBeTruthy()
    } finally {
      vi.useRealTimers()
    }
  })

  it("keeps only what the backend accepts", async () => {
    h.api.POST.mockResolvedValue(ok(intent()))
    renderDock()

    await speak("a".repeat(800))

    expect(h.api.POST.mock.calls[0][1].body.transcript).toHaveLength(500)
  })
})

describe("VoiceDock: falling back to typing", () => {
  it("a fatal failure switches to the text box and says why", () => {
    renderDock()
    fireEvent.keyDown(document.body, space)

    act(() => capture().onError({ reason: "Microphone blocked", fatal: true }))

    expect(h.toastError).toHaveBeenCalledWith(
      "Microphone blocked",
      expect.objectContaining({ description: expect.any(String) })
    )
    expect(screen.getByLabelText("Type a command")).toBeTruthy()
    expect(screen.getByRole("alert").textContent).toBe("Microphone blocked")
    // Space no longer tries the microphone that just failed.
    fireEvent.keyUp(document.body, space)
    fireEvent.keyDown(document.body, space)
    expect(h.capture.start).toHaveBeenCalledTimes(1)
  })

  it("a recoverable failure keeps voice and does not toast", () => {
    renderDock()
    fireEvent.keyDown(document.body, space)

    act(() =>
      capture().onError({ reason: "Voice connection dropped", fatal: false })
    )

    expect(h.toastError).not.toHaveBeenCalled()
    expect(screen.queryByLabelText("Type a command")).toBeNull()
    expect(screen.getByRole("alert").textContent).toBe(
      "Voice connection dropped"
    )

    // And the next press tries again.
    fireEvent.keyUp(document.body, space)
    fireEvent.keyDown(document.body, space)
    expect(h.capture.start).toHaveBeenCalledTimes(2)
  })

  it("text submit routes like voice", async () => {
    const user = userEvent.setup()
    const onIntent = vi.fn()
    h.api.POST.mockResolvedValue(
      ok(intent({ kind: "open_review", heard: "Open review" }))
    )
    renderDock(onIntent)

    await user.click(
      screen.getByRole("button", { name: "Type a command instead" })
    )
    await user.type(
      screen.getByLabelText("Type a command"),
      "open review{Enter}"
    )

    expect(h.api.POST.mock.calls[0][1].body).toMatchObject({
      screen: "discover",
      transcript: "open review",
    })
    await waitFor(() => expect(onIntent).toHaveBeenCalledTimes(1))
    expect(onIntent.mock.calls[0][0].kind).toBe("open_review")
    expect(screen.getByText("Open review")).toBeTruthy()
    // The box is empty again for the next command.
    expect(
      (screen.getByLabelText("Type a command") as HTMLInputElement).value
    ).toBe("")
  })

  it("will not send an empty command", async () => {
    const user = userEvent.setup()
    renderDock()
    await user.click(
      screen.getByRole("button", { name: "Type a command instead" })
    )

    await user.type(screen.getByLabelText("Type a command"), "   {Enter}")

    expect(h.api.POST).not.toHaveBeenCalled()
    expect(
      (
        screen.getByRole("button", {
          name: "Send command",
        }) as HTMLButtonElement
      ).disabled
    ).toBe(true)
  })

  it("switches back to voice on request", async () => {
    const user = userEvent.setup()
    renderDock()
    await user.click(
      screen.getByRole("button", { name: "Type a command instead" })
    )
    expect(screen.getByLabelText("Type a command")).toBeTruthy()

    await user.click(screen.getByRole("button", { name: "Use voice" }))

    expect(screen.queryByLabelText("Type a command")).toBeNull()
    fireEvent.keyDown(document.body, space)
    expect(h.capture.start).toHaveBeenCalledTimes(1)
  })

  it("the orb is not a button to press while typing is chosen", async () => {
    const user = userEvent.setup()
    renderDock()
    await user.click(
      screen.getByRole("button", { name: "Type a command instead" })
    )

    expect(
      (
        screen.getByRole("button", {
          name: "Hold to speak",
        }) as HTMLButtonElement
      ).disabled
    ).toBe(true)
  })

  it("tapping the Heard chip puts the text in the box for editing", async () => {
    const user = userEvent.setup()
    h.api.POST.mockResolvedValue(
      ok(intent({ heard: "Tech creators under $2,000" }))
    )
    renderDock()
    fireEvent.keyDown(document.body, space)
    act(() => capture().onConnected?.())
    fireEvent.keyUp(document.body, space)
    await act(async () => capture().onFinal("tech creators"))

    await user.click(
      screen.getByRole("button", { name: /Heard: Tech creators under \$2,000/ })
    )

    const box = screen.getByLabelText("Type a command") as HTMLInputElement
    expect(box.value).toBe("Tech creators under $2,000")
    expect(document.activeElement).toBe(box)
    expect(screen.queryByText("Heard:")).toBeNull()
  })

  it("dismissing the Heard chip removes it", async () => {
    const user = userEvent.setup()
    h.api.POST.mockResolvedValue(ok(intent()))
    renderDock()
    fireEvent.keyDown(document.body, space)
    act(() => capture().onConnected?.())
    fireEvent.keyUp(document.body, space)
    await act(async () => capture().onFinal("tech creators"))

    await user.click(screen.getByRole("button", { name: "Dismiss" }))

    expect(screen.queryByText("Heard:")).toBeNull()
  })
})
