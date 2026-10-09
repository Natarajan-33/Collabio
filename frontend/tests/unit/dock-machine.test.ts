import { describe, expect, it } from "vitest"

import {
  type DockEvent,
  type DockState,
  dockReducer,
  initialDockState,
} from "@/lib/voice/dock-machine"

function run(events: DockEvent[], from: DockState = initialDockState) {
  return events.reduce(dockReducer, from)
}

describe("dockReducer", () => {
  it("starts idle with voice input", () => {
    expect(initialDockState).toEqual({
      mode: "idle",
      input: "voice",
      partial: "",
      heard: null,
      error: null,
    })
  })

  it("press → connecting → listening shows partial", () => {
    const connecting = run([{ type: "PRESS" }])
    expect(connecting.mode).toBe("connecting")

    const listening = run(
      [
        { type: "CONNECTED" },
        { type: "PARTIAL", text: "tech creators" },
        { type: "PARTIAL", text: "tech creators under two thousand" },
      ],
      connecting
    )
    expect(listening.mode).toBe("listening")
    expect(listening.partial).toBe("tech creators under two thousand")
  })

  it("a partial that beats the connected event still starts listening", () => {
    const s = run([{ type: "PRESS" }, { type: "PARTIAL", text: "hello" }])
    expect(s.mode).toBe("listening")
    expect(s.partial).toBe("hello")
  })

  it("press clears the previous result", () => {
    const heard = run([
      { type: "TEXT_SUBMIT", text: "select the top ten" },
      { type: "ROUTED", heard: "select the top ten" },
    ])
    expect(heard.heard).toBe("select the top ten")

    const s = dockReducer(heard, { type: "PRESS" })
    expect(s.mode).toBe("connecting")
    expect(s.heard).toBeNull()
    expect(s.partial).toBe("")
  })

  it("release with empty text returns to idle without routing", () => {
    const s = run([
      { type: "PRESS" },
      { type: "CONNECTED" },
      { type: "RELEASE", finalText: "   " },
    ])
    expect(s.mode).toBe("idle")
    expect(s.partial).toBe("")
  })

  it("release before the connection is up also returns to idle", () => {
    const s = run([{ type: "PRESS" }, { type: "RELEASE", finalText: "" }])
    expect(s.mode).toBe("idle")
  })

  it("late connected and partial events after a release are ignored", () => {
    const s = run([
      { type: "PRESS" },
      { type: "RELEASE", finalText: "" },
      { type: "CONNECTED" },
      { type: "PARTIAL", text: "too late" },
    ])
    expect(s).toEqual(initialDockState)
  })

  it("release → routing → heard", () => {
    const routing = run([
      { type: "PRESS" },
      { type: "CONNECTED" },
      { type: "PARTIAL", text: "hello" },
      { type: "RELEASE", finalText: " hello there " },
    ])
    expect(routing.mode).toBe("routing")
    expect(routing.partial).toBe("hello there")

    const heard = dockReducer(routing, { type: "ROUTED", heard: "Hello there" })
    expect(heard.mode).toBe("heard")
    expect(heard.heard).toBe("Hello there")
    expect(heard.partial).toBe("")
  })

  it("routed is ignored unless a command is being routed", () => {
    expect(dockReducer(initialDockState, { type: "ROUTED", heard: "x" })).toBe(
      initialDockState
    )
  })

  it("error falls back to typing", () => {
    const s = dockReducer(
      { ...initialDockState, mode: "connecting" },
      { type: "FAIL", reason: "Microphone blocked", fatal: true }
    )
    expect(s.mode).toBe("error")
    expect(s.input).toBe("text")
    expect(s.error).toBe("Microphone blocked")
  })

  it("a recoverable failure keeps voice input and the words that were said", () => {
    const routing = run([{ type: "TEXT_SUBMIT", text: "tech creators" }])
    const s = dockReducer(routing, {
      type: "FAIL",
      reason: "Couldn't reach Collabio",
      fatal: false,
    })
    expect(s.mode).toBe("error")
    expect(s.input).toBe("voice")
    expect(s.error).toBe("Couldn't reach Collabio")
    expect(s.partial).toBe("tech creators")
  })

  it("a capture failure drops the half-heard words", () => {
    const s = run([
      { type: "PRESS" },
      { type: "PARTIAL", text: "tech cre" },
      { type: "FAIL", reason: "Voice connection dropped", fatal: false },
    ])
    expect(s.partial).toBe("")
  })

  it("text submit routes like voice", () => {
    const routing = dockReducer(
      { ...initialDockState, input: "text" },
      { type: "TEXT_SUBMIT", text: "  open review " }
    )
    expect(routing.mode).toBe("routing")
    expect(routing.input).toBe("text")
    expect(routing.partial).toBe("open review")

    const heard = dockReducer(routing, { type: "ROUTED", heard: "Open review" })
    expect(heard.mode).toBe("heard")
    expect(heard.heard).toBe("Open review")
  })

  it("empty text submit does nothing", () => {
    expect(
      dockReducer(initialDockState, { type: "TEXT_SUBMIT", text: " " })
    ).toBe(initialDockState)
  })

  it("text cannot be submitted while a command is in flight", () => {
    const routing = dockReducer(initialDockState, {
      type: "TEXT_SUBMIT",
      text: "first",
    })
    expect(dockReducer(routing, { type: "TEXT_SUBMIT", text: "second" })).toBe(
      routing
    )
  })

  it("press is ignored while text input is chosen", () => {
    const s = { ...initialDockState, input: "text" as const }
    expect(dockReducer(s, { type: "PRESS" })).toBe(s)
  })

  it("press is ignored while a command is in flight", () => {
    const routing = dockReducer(initialDockState, {
      type: "TEXT_SUBMIT",
      text: "first",
    })
    expect(dockReducer(routing, { type: "PRESS" })).toBe(routing)

    const listening = run([{ type: "PRESS" }, { type: "CONNECTED" }])
    expect(dockReducer(listening, { type: "PRESS" })).toBe(listening)
  })

  it("press recovers from an error when voice input is still chosen", () => {
    const failed = dockReducer(initialDockState, {
      type: "FAIL",
      reason: "Voice connection dropped",
      fatal: false,
    })
    const s = dockReducer(failed, { type: "PRESS" })
    expect(s.mode).toBe("connecting")
    expect(s.error).toBeNull()
  })

  it("dismiss clears the heard chip and any error", () => {
    const heard = run([
      { type: "TEXT_SUBMIT", text: "x" },
      { type: "ROUTED", heard: "x" },
    ])
    expect(dockReducer(heard, { type: "DISMISS" })).toEqual(initialDockState)

    const failed = dockReducer(initialDockState, {
      type: "FAIL",
      reason: "nope",
      fatal: false,
    })
    expect(dockReducer(failed, { type: "DISMISS" })).toEqual(initialDockState)
  })

  it("dismiss does not interrupt a capture", () => {
    const listening = run([{ type: "PRESS" }, { type: "CONNECTED" }])
    expect(dockReducer(listening, { type: "DISMISS" })).toBe(listening)
  })

  it("switching input starts from a clean idle dock", () => {
    const failed = dockReducer(initialDockState, {
      type: "FAIL",
      reason: "Microphone blocked",
      fatal: true,
    })
    const voice = dockReducer(failed, { type: "SET_INPUT", input: "voice" })
    expect(voice).toEqual(initialDockState)

    const text = dockReducer(initialDockState, {
      type: "SET_INPUT",
      input: "text",
    })
    expect(text).toEqual({ ...initialDockState, input: "text" })
  })

  it("switching input is ignored mid-command", () => {
    const listening = run([{ type: "PRESS" }, { type: "CONNECTED" }])
    expect(dockReducer(listening, { type: "SET_INPUT", input: "text" })).toBe(
      listening
    )
  })
})
