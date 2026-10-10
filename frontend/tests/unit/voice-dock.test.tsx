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
  router: { push: vi.fn() },
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
vi.mock("next/navigation", () => ({ useRouter: () => h.router }))
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

// `navigate` is typed loosely so tests can send routes the API never would.
function intent(
  over: Omit<Partial<VoiceIntent>, "navigate"> & { navigate?: string | null } = {}
): VoiceIntent {
  return {
    kind: "search",
    heard: "Tech creators",
    suggestions: [],
    ...over,
  } as VoiceIntent
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

/**
 * Keys go to whatever has focus, as they do for a person: `document.body` only when
 * nothing does. Aiming them at the body hid a bug (Space after a mouse click).
 */
let user: ReturnType<typeof userEvent.setup>
const hold = () => user.keyboard("[Space>]")
const letGo = () => user.keyboard("[/Space]")

beforeEach(() => {
  user = userEvent.setup()
  h.capture.start.mockReset().mockResolvedValue(undefined)
  h.capture.stop.mockReset()
  h.api.POST.mockReset()
  h.toastError.mockReset()
  h.router.push.mockReset()
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

  it.each<[string, () => HTMLElement]>([
    ["a button", () => document.createElement("button")],
    [
      "a link",
      () => {
        const a = document.createElement("a")
        a.setAttribute("href", "/somewhere")
        return a
      },
    ],
    [
      "a checkbox input",
      () => {
        const input = document.createElement("input")
        input.type = "checkbox"
        return input
      },
    ],
    [
      "a radio input",
      () => {
        const input = document.createElement("input")
        input.type = "radio"
        return input
      },
    ],
    ...[
      "button",
      "checkbox",
      "switch",
      "radio",
      "option",
      "menuitem",
      "tab",
    ].map(
      (role) =>
        [
          `an element with role=${role}`,
          () => {
            const div = document.createElement("div")
            div.setAttribute("role", role)
            div.tabIndex = 0
            return div
          },
        ] satisfies [string, () => HTMLElement]
    ),
  ])("space on %s keeps its own keyboard activation", (_name, make) => {
    renderDock()
    const el = make()
    document.body.append(el)

    // Not claimed: the control still gets Space (checkbox toggles, button clicks).
    expect(fireEvent.keyDown(el, space)).toBe(true)
    expect(fireEvent.keyUp(el, space)).toBe(true)

    expect(h.capture.start).not.toHaveBeenCalled()
    el.remove()
  })

  it("space on a nested part of a control keeps the control's activation", () => {
    renderDock()
    const button = document.createElement("button")
    const icon = document.createElement("span")
    button.append(icon)
    document.body.append(button)

    fireEvent.keyDown(icon, space)

    expect(h.capture.start).not.toHaveBeenCalled()
    button.remove()
  })

  it("space on a non-interactive link (no href) or plain element is still push-to-talk", () => {
    renderDock()
    const a = document.createElement("a")
    document.body.append(a)

    fireEvent.keyDown(a, space)

    expect(h.capture.start).toHaveBeenCalledTimes(1)
    a.remove()
  })

  it("leaves chorded space alone", async () => {
    renderDock()

    await user.keyboard("{Control>}[Space]{/Control}")
    await user.keyboard("{Meta>}[Space]{/Meta}")

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

  it("space on the focused orb is push-to-talk like anywhere else", async () => {
    renderDock()
    const orb = screen.getByRole("button", { name: "Hold to speak" })
    const clicked = vi.fn()
    orb.addEventListener("click", clicked)
    orb.focus()

    await hold()
    expect(h.capture.start).toHaveBeenCalledTimes(1)

    await letGo()
    expect(h.capture.stop).toHaveBeenCalledTimes(1)
    // The release is not also taken as a click on the button.
    expect(clicked).not.toHaveBeenCalled()
  })

  it("ignores a key release that no capture is waiting for", () => {
    renderDock()

    expect(fireEvent.keyUp(document.body, space)).toBe(true)
    expect(h.capture.stop).not.toHaveBeenCalled()
  })

  it("press-and-hold on the orb starts, letting go stops", async () => {
    renderDock()
    const orb = screen.getByRole("button", { name: "Hold to speak" })

    await user.pointer({ keys: "[MouseLeft>]", target: orb })
    expect(h.capture.start).toHaveBeenCalledTimes(1)
    expect(h.capture.stop).not.toHaveBeenCalled()

    await user.pointer({ keys: "[/MouseLeft]" })
    expect(h.capture.stop).toHaveBeenCalledTimes(1)
  })

  it("stops when the window loses focus mid-hold, so the key release is not missed", async () => {
    renderDock()
    await hold()

    fireEvent.blur(window)

    expect(h.capture.stop).toHaveBeenCalledTimes(1)
  })

  it("does not start a second capture while one is running", async () => {
    renderDock()
    await hold()
    act(() => capture().onConnected?.())

    await letGo()
    act(() => capture().onFinal(""))
    await hold()

    // The new press is fine once the first is over...
    expect(h.capture.start).toHaveBeenCalledTimes(2)
    // ...but not while it is still held.
    await hold()
    expect(h.capture.start).toHaveBeenCalledTimes(2)
  })
})

describe("VoiceDock: what it shows", () => {
  it("shows the live transcript while listening", async () => {
    renderDock()
    expect(screen.getByText("Hold Space to speak")).toBeTruthy()

    await hold()
    expect(screen.getByText("Connecting…")).toBeTruthy()

    act(() => capture().onConnected?.())
    expect(screen.getByText("Listening…")).toBeTruthy()

    act(() => capture().onPartial("tech creators"))
    act(() => capture().onPartial("tech creators under two thousand"))
    expect(screen.getByText("tech creators under two thousand")).toBeTruthy()
  })

  it("releasing with nothing heard goes back to idle without routing", async () => {
    renderDock()
    await hold()
    act(() => capture().onConnected?.())
    await letGo()

    act(() => capture().onFinal("  "))

    expect(h.api.POST).not.toHaveBeenCalled()
    expect(screen.getByText("Hold Space to speak")).toBeTruthy()
  })

  it("maps the dock's mode onto the Orb and mounts it only while working", async () => {
    h.reduced.current = false
    renderDock()
    // Idle: a static disc, no WebGL.
    expect(screen.queryByTestId("orb")).toBeNull()

    await hold()
    expect(screen.getByTestId("orb").dataset.agentState).toBe("thinking")

    act(() => capture().onConnected?.())
    expect(screen.getByTestId("orb").dataset.agentState).toBe("listening")
    // The ember --voice ramp, not the Orb's default blue.
    expect(screen.getByTestId("orb").dataset.colors).toBe("#f6623d,#ffaf76")

    h.api.POST.mockReturnValue(new Promise(() => {}))
    await letGo()
    act(() => capture().onFinal("hello"))
    expect(screen.getByTestId("orb").dataset.agentState).toBe("thinking")
  })

  it("never mounts the Orb under reduced motion", async () => {
    h.reduced.current = true
    renderDock()

    await hold()
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
    await hold()
    act(() => capture().onConnected?.())
    act(() => capture().onPartial(text))
    await letGo()
    await act(async () => capture().onFinal(text))
  }

  it("letting go waits for the last words, shows it is working, then routes them all", async () => {
    h.api.POST.mockResolvedValue(ok(intent()))
    renderDock()
    await hold()
    act(() => capture().onConnected?.())
    act(() => capture().onPartial("select the top"))

    await letGo()

    // The speaker is done, but the capture has not reported yet: nothing is sent, and a
    // new press cannot begin until it has.
    expect(screen.getByRole("status").textContent).toBe("Working on it")
    expect(screen.getByText("select the top")).toBeTruthy()
    expect(h.api.POST).not.toHaveBeenCalled()
    await hold()
    expect(h.capture.start).toHaveBeenCalledTimes(1)
    await letGo()

    await act(async () => capture().onFinal("Select the top ten"))

    expect(h.api.POST).toHaveBeenCalledTimes(1)
    expect(h.api.POST.mock.calls[0][1].body.transcript).toBe(
      "Select the top ten"
    )
  })

  it("a failure while the last words are awaited shows the failure", async () => {
    renderDock()
    await hold()
    act(() => capture().onConnected?.())
    await letGo()

    act(() =>
      capture().onError({ reason: "Voice usage limit reached", fatal: true })
    )

    expect(screen.getByRole("alert").textContent).toBe(
      "Voice usage limit reached"
    )
    expect(h.api.POST).not.toHaveBeenCalled()
  })

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

  it("navigates for a navigate intent, on any screen, without bothering the page", async () => {
    const onIntent = vi.fn()
    h.api.POST.mockResolvedValue(
      ok(
        intent({
          kind: "navigate",
          heard: "Go to packages",
          navigate: "/creator/packages",
        })
      )
    )
    renderDock(onIntent)

    await speak("go to my packages")

    expect(h.router.push).toHaveBeenCalledExactlyOnceWith("/creator/packages")
    expect(onIntent).not.toHaveBeenCalled()
    expect(screen.getByText("Go to packages")).toBeTruthy()
  })

  it("navigates when no page has registered either", async () => {
    h.api.POST.mockResolvedValue(
      ok(intent({ kind: "navigate", navigate: "/brand/discover" }))
    )
    render(
      <VoiceScreenProvider>
        <VoiceDock />
      </VoiceScreenProvider>
    )

    await speak("go to discover")

    expect(h.router.push).toHaveBeenCalledExactlyOnceWith("/brand/discover")
  })

  it.each([
    ["another site", "https://evil.example/phish"],
    ["a protocol-relative URL", "//evil.example"],
    ["a script URL", "javascript:alert(1)"],
    ["the sign-in page", "/sign-in"],
    ["nothing", null],
  ])("does not navigate to %s", async (_name, to) => {
    h.api.POST.mockResolvedValue(ok(intent({ kind: "navigate", navigate: to })))
    renderDock()

    await speak("go somewhere")

    expect(h.router.push).not.toHaveBeenCalled()
    // The command was still understood, so the chip still says so.
    expect(screen.getByText("Heard:")).toBeTruthy()
  })

  it("does not navigate for a page that is no longer on screen", async () => {
    let resolve!: (value: unknown) => void
    h.api.POST.mockReturnValue(new Promise((r) => (resolve = r)))
    const withPage = (shown: boolean) => (
      <VoiceScreenProvider>
        {shown ? <Page onIntent={vi.fn()} /> : null}
        <VoiceDock />
      </VoiceScreenProvider>
    )
    const { rerender } = render(withPage(true))
    await speak("go to packages")

    rerender(withPage(false))
    await act(async () =>
      resolve(ok(intent({ kind: "navigate", navigate: "/creator/packages" })))
    )

    expect(h.router.push).not.toHaveBeenCalled()
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
  it("a fatal failure switches to the text box and says why", async () => {
    renderDock()
    await hold()

    act(() => capture().onError({ reason: "Microphone blocked", fatal: true }))

    expect(h.toastError).toHaveBeenCalledWith(
      "Microphone blocked",
      expect.objectContaining({ description: expect.any(String) })
    )
    expect(screen.getByLabelText("Type a command")).toBeTruthy()
    expect(screen.getByRole("alert").textContent).toBe("Microphone blocked")
    // Space no longer tries the microphone that just failed.
    await letGo()
    await hold()
    expect(h.capture.start).toHaveBeenCalledTimes(1)
  })

  it("a fatal failure during a press-and-hold does not leave the press stuck", async () => {
    renderDock()
    const orb = screen.getByRole("button", { name: "Hold to speak" })
    await user.pointer({ keys: "[MouseLeft>]", target: orb })
    expect(h.capture.start).toHaveBeenCalledTimes(1)

    // The microphone is refused while the orb is still held: the orb is disabled by
    // the switch to typing, so the pointer-up that would end the press never arrives.
    act(() => capture().onError({ reason: "Microphone blocked", fatal: true }))

    // Back to voice (say, after allowing the microphone): Space works again.
    await user.click(screen.getByRole("button", { name: "Use voice" }))
    await hold()
    expect(h.capture.start).toHaveBeenCalledTimes(2)
  })

  it("a recoverable failure keeps voice and does not toast", async () => {
    renderDock()
    await hold()

    act(() =>
      capture().onError({ reason: "Voice connection dropped", fatal: false })
    )

    expect(h.toastError).not.toHaveBeenCalled()
    expect(screen.queryByLabelText("Type a command")).toBeNull()
    expect(screen.getByRole("alert").textContent).toBe(
      "Voice connection dropped"
    )

    // And the next press tries again.
    await letGo()
    await hold()
    expect(h.capture.start).toHaveBeenCalledTimes(2)
  })

  it("text submit routes like voice", async () => {
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
    renderDock()
    await user.click(
      screen.getByRole("button", { name: "Type a command instead" })
    )
    expect(screen.getByLabelText("Type a command")).toBeTruthy()

    await user.click(screen.getByRole("button", { name: "Use voice" }))

    expect(screen.queryByLabelText("Type a command")).toBeNull()
    // Focus lands on the orb, so Space is push-to-talk and not a second press of the
    // toggle that was just clicked.
    expect(document.activeElement).toBe(
      screen.getByRole("button", { name: "Hold to speak" })
    )
    await hold()
    expect(h.capture.start).toHaveBeenCalledTimes(1)
    await letGo()
    expect(screen.queryByLabelText("Type a command")).toBeNull()
    expect(
      screen.getByRole("button", { name: "Type a command instead" })
    ).toBeTruthy()
  })

  it("leaves focus alone until the user has switched back to voice", async () => {
    renderDock()

    expect(document.activeElement).toBe(document.body)

    await user.click(
      screen.getByRole("button", { name: "Type a command instead" })
    )
    expect(document.activeElement).toBe(screen.getByLabelText("Type a command"))
  })

  it("the orb is not a button to press while typing is chosen", async () => {
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
    h.api.POST.mockResolvedValue(
      ok(intent({ heard: "Tech creators under $2,000" }))
    )
    renderDock()
    await hold()
    act(() => capture().onConnected?.())
    await letGo()
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
    h.api.POST.mockResolvedValue(ok(intent()))
    renderDock()
    await hold()
    act(() => capture().onConnected?.())
    await letGo()
    await act(async () => capture().onFinal("tech creators"))

    await user.click(screen.getByRole("button", { name: "Dismiss" }))

    expect(screen.queryByText("Heard:")).toBeNull()
  })
})

describe("VoiceDock: Space after the mouse", () => {
  const onFilters = vi.fn()

  function renderWithControls() {
    onFilters.mockReset()
    return render(
      <VoiceScreenProvider>
        <Page onIntent={vi.fn()} />
        <input type="checkbox" aria-label="Select Priya" />
        <button type="button" onClick={onFilters}>
          Filters
        </button>
        <VoiceDock />
      </VoiceScreenProvider>
    )
  }
  const checkbox = () =>
    screen.getByRole("checkbox", { name: "Select Priya" }) as HTMLInputElement

  it("after Use voice, Space starts a capture and does not flip the dock back to typing", async () => {
    renderDock()
    await user.click(
      screen.getByRole("button", { name: "Type a command instead" })
    )
    await user.click(screen.getByRole("button", { name: "Use voice" }))

    await hold()

    expect(h.capture.start).toHaveBeenCalledTimes(1)
    expect(screen.queryByLabelText("Type a command")).toBeNull()
  })

  it("after a mouse click on a checkbox, Space is push-to-talk and the checkbox stays as clicked", async () => {
    renderWithControls()
    await user.click(checkbox())
    expect(checkbox().checked).toBe(true)

    await hold()
    expect(h.capture.start).toHaveBeenCalledTimes(1)
    await letGo()

    expect(h.capture.stop).toHaveBeenCalledTimes(1)
    expect(checkbox().checked).toBe(true)
  })

  it("after a mouse click on a button, Space is push-to-talk and does not press it again", async () => {
    renderWithControls()
    await user.click(screen.getByRole("button", { name: "Filters" }))
    expect(onFilters).toHaveBeenCalledTimes(1)

    await hold()
    await letGo()

    expect(h.capture.start).toHaveBeenCalledTimes(1)
    expect(onFilters).toHaveBeenCalledTimes(1)
  })

  it("holding Space again after a capture still speaks, not toggles", async () => {
    renderWithControls()
    await user.click(checkbox())

    await hold()
    await letGo()
    act(() => capture().onFinal(""))
    await hold()
    await letGo()

    expect(h.capture.start).toHaveBeenCalledTimes(2)
    expect(checkbox().checked).toBe(true)
  })

  it("a checkbox reached with the keyboard keeps Space", async () => {
    renderWithControls()
    await user.tab()
    await user.tab()
    expect(document.activeElement).toBe(checkbox())

    await user.keyboard("[Space]")

    expect(checkbox().checked).toBe(true)
    expect(h.capture.start).not.toHaveBeenCalled()
  })

  it("a key press after a click hands Space back to the focused control", async () => {
    renderWithControls()
    await user.click(checkbox())

    // Tab away and back: the keyboard is in charge now.
    await user.tab()
    await user.tab({ shift: true })
    expect(document.activeElement).toBe(checkbox())
    await user.keyboard("[Space]")

    expect(checkbox().checked).toBe(false)
    expect(h.capture.start).not.toHaveBeenCalled()
  })

  it("holding a modifier does not count as keyboard use", async () => {
    renderWithControls()
    await user.click(checkbox())

    await user.keyboard("{Shift>}")
    await hold()
    await letGo()
    await user.keyboard("{/Shift}")

    expect(h.capture.start).toHaveBeenCalledTimes(1)
    expect(checkbox().checked).toBe(true)
  })

  it.each(["text", "search", "email", "number", "password", "date"])(
    "a %s field keeps Space after a click, as it is being typed in",
    async (type) => {
      render(
        <VoiceScreenProvider>
          <input type={type} aria-label="Field" />
          <VoiceDock />
        </VoiceScreenProvider>
      )
      const field = screen.getByLabelText("Field")
      await user.click(field)

      await user.keyboard("[Space]")

      expect(h.capture.start).not.toHaveBeenCalled()
    }
  )

  it("a radio is pressed like a checkbox: Space after a click speaks", async () => {
    render(
      <VoiceScreenProvider>
        <input type="radio" aria-label="Option" />
        <VoiceDock />
      </VoiceScreenProvider>
    )
    await user.click(screen.getByRole("radio", { name: "Option" }))

    await hold()

    expect(h.capture.start).toHaveBeenCalledTimes(1)
  })

  it("typing fields keep Space after a click too", async () => {
    renderWithControls()
    const field = screen.getByLabelText("Page field") as HTMLInputElement
    await user.click(field)

    await user.keyboard("a b")

    expect(field.value).toBe("a b")
    expect(h.capture.start).not.toHaveBeenCalled()
  })
})
