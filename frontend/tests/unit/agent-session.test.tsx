import { act, cleanup, render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import { AgentSession } from "@/components/brief/agent-session"
import {
  VoiceScreenProvider,
  useVoicePausedReason,
} from "@/components/voice/voice-screen"
import type { components } from "@/lib/api/schema"
import type { BriefFieldKey } from "@/lib/brief/state"

type DealBrief = components["schemas"]["DealBrief"]
type Preview = components["schemas"]["BriefCreatorPreview"]

type SessionOptions = {
  conversationToken: string
  connectionType: string
  dynamicVariables: Record<string, string>
  onConnect: (props: { conversationId: string }) => void
  onDisconnect: (details: { reason: string }) => void
  onError: (message: string, context?: unknown) => void
  onMessage: (props: { message: string; role: "user" | "agent" }) => void
}

const h = vi.hoisted(() => {
  type State = { status: string; isSpeaking: boolean }
  let state: State = { status: "disconnected", isSpeaking: false }
  const listeners = new Set<() => void>()
  return {
    api: { PATCH: vi.fn(), POST: vi.fn() },
    toastError: vi.fn(),
    reduced: { current: false },
    tools: {} as Record<string, (params: Record<string, unknown>) => unknown>,
    startSession: vi.fn(),
    endSession: vi.fn(),
    sendContextualUpdate: vi.fn(),
    store: {
      get: () => state,
      set(next: Partial<State>) {
        state = { ...state, ...next }
        listeners.forEach((listener) => listener())
      },
      subscribe(listener: () => void) {
        listeners.add(listener)
        return () => {
          listeners.delete(listener)
        }
      },
    },
  }
})

vi.mock("@/hooks/use-api", () => ({ useApi: () => h.api }))
vi.mock("sonner", () => ({ toast: { error: h.toastError } }))
vi.mock("motion/react", () => ({ useReducedMotion: () => h.reduced.current }))
// Never WebGL in unit tests: the dynamic Orb becomes a marker that shows its state.
vi.mock("next/dynamic", () => ({
  default: () =>
    function OrbStub(props: { agentState: string | null }) {
      return (
        <div data-testid="orb" data-agent-state={props.agentState ?? "none"} />
      )
    },
}))
vi.mock("@elevenlabs/react", async () => {
  const React = await import("react")
  return {
    ConversationProvider: ({ children }: { children: React.ReactNode }) =>
      children,
    useConversation: () => {
      const state = React.useSyncExternalStore(
        h.store.subscribe,
        h.store.get,
        h.store.get
      )
      return {
        ...state,
        startSession: h.startSession,
        endSession: h.endSession,
        sendContextualUpdate: h.sendContextualUpdate,
      }
    },
    useConversationClientTool: (
      name: string,
      handler: (params: Record<string, unknown>) => unknown
    ) => {
      h.tools[name] = handler
    },
  }
})

const BRIEF_PATH = "/api/v1/briefs/{brief_id}"
const SESSION_PATH = "/api/v1/briefs/{brief_id}/voice-session"
const PARAMS = { params: { path: { brief_id: "brief-1" } } }
const PAUSE = "Voice is in the brief conversation"

function brief(over: Partial<DealBrief> = {}): DealBrief {
  return {
    id: "brief-1",
    status: "draft",
    creator_ids: ["arjun", "priya"],
    approved_at: null,
    batch_id: null,
    missing: ["go_live_by", "ask_price_cents"],
    violations: [],
    brand_name: "Lumen",
    product_name: "Lumen Lamp",
    deliverables_count: 3,
    deliverables_format: "short_video",
    flexibility: [],
    hires_target: 1,
    ...over,
  }
}

function creator(id: string, name: string): Preview {
  return { creator_id: id, name, handle: `${id}_handle` } as Preview
}

const CREATORS = [creator("arjun", "Arjun Rao"), creator("priya", "Priya Shah")]
const NONE: ReadonlySet<BriefFieldKey> = new Set()

const callbacks = {
  onSaved: vi.fn(),
  onHighlight: vi.fn(),
  onReady: vi.fn(),
}

function Paused() {
  return <output data-testid="paused">{useVoicePausedReason() ?? ""}</output>
}

function ui(props: { brief?: DealBrief; edited?: ReadonlySet<BriefFieldKey> }) {
  return (
    <VoiceScreenProvider>
      <Paused />
      <AgentSession
        briefId="brief-1"
        brief={props.brief ?? brief()}
        preview={CREATORS}
        edited={props.edited ?? NONE}
        {...callbacks}
      />
    </VoiceScreenProvider>
  )
}

/** Opens a session and returns the options the page handed to `startSession`. */
async function start(): Promise<SessionOptions> {
  const user = userEvent.setup()
  await user.click(screen.getByRole("button", { name: "Talk it through" }))
  await waitFor(() => expect(h.startSession).toHaveBeenCalled())
  return h.startSession.mock.calls.at(-1)?.[0] as SessionOptions
}

/** The call is up: the library reports it through `onConnect`. */
function connect(options: SessionOptions) {
  act(() => options.onConnect({ conversationId: "conv_1" }))
}

beforeEach(() => {
  h.api.PATCH.mockReset()
  h.api.POST.mockReset()
  h.toastError.mockReset()
  h.startSession.mockReset()
  h.endSession.mockReset()
  h.sendContextualUpdate.mockReset()
  callbacks.onSaved.mockReset()
  callbacks.onHighlight.mockReset()
  callbacks.onReady.mockReset()
  h.reduced.current = false
  h.store.set({ status: "disconnected", isSpeaking: false })
  h.api.POST.mockResolvedValue({
    data: {
      conversation_token: "tok_1",
      dynamic_variables: { brand_name: "Lumen" },
    },
    response: { status: 200 },
  })
})

afterEach(cleanup)

describe("AgentSession", () => {
  it("starts a WebRTC session with the minted token and variables", async () => {
    render(ui({}))

    const options = await start()

    expect(h.api.POST).toHaveBeenCalledWith(SESSION_PATH, PARAMS)
    expect(options).toMatchObject({
      conversationToken: "tok_1",
      connectionType: "webrtc",
      dynamicVariables: { brand_name: "Lumen" },
    })
  })

  it("says so, and starts nothing, when the session cannot be minted", async () => {
    const user = userEvent.setup()
    h.api.POST.mockResolvedValue({ error: {}, response: { status: 503 } })
    render(ui({}))

    await user.click(screen.getByRole("button", { name: "Talk it through" }))

    await waitFor(() => expect(h.toastError).toHaveBeenCalled())
    expect(h.startSession).not.toHaveBeenCalled()
    expect(screen.getByRole("button", { name: "Talk it through" })).toBeTruthy()
  })

  it("records the conversation id on connect", async () => {
    h.api.PATCH.mockResolvedValue({ data: brief(), response: { status: 200 } })
    render(ui({}))
    const options = await start()

    act(() => options.onConnect({ conversationId: "conv_b" }))

    expect(h.api.PATCH).toHaveBeenCalledWith(BRIEF_PATH, {
      ...PARAMS,
      body: { intake_conversation_id: "conv_b" },
    })
  })

  it("update_brief saves and reports what is still missing", async () => {
    const saved = brief({
      missing: ["go_live_by", "ask_price_cents"],
      deliverables_count: 5,
    })
    h.api.PATCH.mockResolvedValue({ data: saved, response: { status: 200 } })
    render(ui({}))

    const reply = await h.tools.update_brief({
      field: "deliverables_count",
      value: "5",
    })

    expect(h.api.PATCH).toHaveBeenCalledWith(BRIEF_PATH, {
      ...PARAMS,
      body: { deliverables_count: 5 },
    })
    expect(callbacks.onSaved).toHaveBeenCalledWith(saved)
    expect(reply).toBe("Saved. Still missing: go-live date, opening ask")
  })

  it("update_brief says when nothing is missing and converts dollars to cents", async () => {
    h.api.PATCH.mockResolvedValue({
      data: brief({ missing: [] }),
      response: { status: 200 },
    })
    render(ui({}))

    const reply = await h.tools.update_brief({
      field: "ask_price_usd",
      value: "$1,200",
    })

    expect(h.api.PATCH).toHaveBeenCalledWith(BRIEF_PATH, {
      ...PARAMS,
      body: { ask_price_cents: 120000 },
    })
    expect(reply).toBe("Saved. Nothing is missing.")
  })

  it("update_brief returns the server's message on a 422", async () => {
    h.api.PATCH.mockResolvedValue({
      error: {
        detail: {
          error: "invalid_field",
          field: "go_live_by",
          message: "Go-live must be in the future.",
        },
      },
      response: { status: 422 },
    })
    render(ui({}))

    const reply = await h.tools.update_brief({
      field: "go_live_by",
      value: "2020-01-01",
    })

    expect(reply).toBe("Go-live must be in the future.")
    expect(callbacks.onSaved).not.toHaveBeenCalled()
  })

  it("update_brief says so when the save cannot reach the server", async () => {
    h.api.PATCH.mockRejectedValue(new Error("offline"))
    render(ui({}))

    const reply = await h.tools.update_brief({
      field: "deliverables_count",
      value: "2",
    })

    expect(reply).toBe("Couldn't save that. Ask the brand to edit the card.")
  })

  it("update_brief returns the parse error without calling the API", async () => {
    render(ui({}))

    expect(
      await h.tools.update_brief({
        field: "ask_price_usd",
        value: "twelve hundred",
      })
    ).toBe("Give the amount in digits, for example 1200.")
    expect(
      await h.tools.update_brief({ field: "go_live_by", value: "next friday" })
    ).toBe("Give the date as YYYY-MM-DD.")
    expect(h.api.PATCH).not.toHaveBeenCalled()
  })

  it("show_creator highlights a match and says so", () => {
    render(ui({}))

    expect(h.tools.show_creator({ creator_ref: "priya" })).toBe("Shown.")
    expect(callbacks.onHighlight).toHaveBeenCalledWith("priya")

    callbacks.onHighlight.mockReset()
    expect(h.tools.show_creator({ creator_ref: "Zed" })).toBe(
      "No creator by that name in this brief."
    )
    expect(callbacks.onHighlight).not.toHaveBeenCalled()
  })

  it("ready_to_launch reports missing fields or ready", () => {
    const { rerender } = render(ui({}))

    expect(h.tools.ready_to_launch({})).toBe(
      "Still missing: go-live date, opening ask"
    )
    expect(callbacks.onReady).not.toHaveBeenCalled()

    rerender(ui({ brief: brief({ missing: [] }) }))
    expect(h.tools.ready_to_launch({})).toBe("ready")
    expect(callbacks.onReady).toHaveBeenCalledTimes(1)
  })

  it("ready_to_launch does not say ready while a rule is broken", () => {
    render(
      ui({
        brief: brief({
          missing: [],
          violations: [
            {
              field: "ask_price_cents",
              message: "The ask is over the ceiling.",
            },
          ] as DealBrief["violations"],
        }),
      })
    )

    expect(h.tools.ready_to_launch({})).toBe(
      "Not ready: The ask is over the ceiling."
    )
    expect(callbacks.onReady).not.toHaveBeenCalled()
  })

  it("pauses the voice dock while connected, and lets go after", async () => {
    render(ui({}))
    expect(screen.getByTestId("paused").textContent).toBe("")

    const options = await start()
    expect(screen.getByTestId("paused").textContent).toBe(PAUSE)
    connect(options)
    expect(screen.getByTestId("paused").textContent).toBe(PAUSE)

    act(() => options.onDisconnect({ reason: "agent" }))
    expect(screen.getByTestId("paused").textContent).toBe("")
  })

  it("stays in the call when the library reports an error the call survives", async () => {
    const user = userEvent.setup()
    render(ui({}))
    const options = await start()
    connect(options)
    h.startSession.mockClear()
    h.toastError.mockClear()

    // A client tool threw: the library flips its status to "error", the call goes on.
    act(() => {
      h.store.set({ status: "error" })
      options.onError("Client tool execution failed", { name: "Error" })
    })

    expect(screen.getByTestId("paused").textContent).toBe(PAUSE)
    expect(
      screen.getByRole("button", { name: "End conversation" })
    ).toBeTruthy()
    expect(screen.queryByRole("button", { name: "Talk it through" })).toBeNull()
    expect(screen.getByText("Listening")).toBeTruthy()
    expect(h.toastError).not.toHaveBeenCalled()
    await user.click(screen.getByRole("button", { name: "End conversation" }))
    expect(h.startSession).not.toHaveBeenCalled()

    // Only the end of the call releases the dock.
    expect(screen.getByTestId("paused").textContent).toBe("")
  })

  it("holds the dock after an error until the call itself disconnects", async () => {
    render(ui({}))
    const options = await start()
    connect(options)

    act(() => h.store.set({ status: "error" }))
    expect(screen.getByTestId("paused").textContent).toBe(PAUSE)
    expect(h.startSession).toHaveBeenCalledTimes(1)

    act(() => options.onDisconnect({ reason: "error" }))
    expect(screen.getByTestId("paused").textContent).toBe("")
  })

  it("ending and talking again while the token is pending starts only the new session", async () => {
    const user = userEvent.setup()
    const pending: ((reply: unknown) => void)[] = []
    h.api.POST.mockImplementation(
      () => new Promise((resolve) => pending.push(resolve))
    )
    const mint = (token: string) => ({
      data: { conversation_token: token, dynamic_variables: {} },
      response: { status: 200 },
    })
    render(ui({}))

    await user.click(screen.getByRole("button", { name: "Talk it through" }))
    await user.click(screen.getByRole("button", { name: "End conversation" }))
    await user.click(screen.getByRole("button", { name: "Resume" }))
    expect(pending).toHaveLength(2)

    // The first token arrives late, after the second attempt began.
    await act(async () => pending[0](mint("stale")))
    expect(h.startSession).not.toHaveBeenCalled()

    await act(async () => pending[1](mint("fresh")))
    expect(h.startSession).toHaveBeenCalledTimes(1)
    expect(h.startSession.mock.calls[0][0]).toMatchObject({
      conversationToken: "fresh",
    })
  })

  it("sends a contextual update when the card is edited during a call", async () => {
    const { rerender } = render(ui({}))
    const options = await start()
    connect(options)

    rerender(
      ui({
        brief: brief({ ask_price_cents: 120000 }),
        edited: new Set<BriefFieldKey>(["ask_price_cents"]),
      })
    )

    expect(h.sendContextualUpdate).toHaveBeenCalledTimes(1)
    expect(h.sendContextualUpdate).toHaveBeenCalledWith(
      "The brand set opening ask to $1,200 on the card."
    )
  })

  it("stays quiet about card edits made outside a call", () => {
    const { rerender } = render(ui({}))

    rerender(
      ui({
        brief: brief({ ask_price_cents: 120000 }),
        edited: new Set<BriefFieldKey>(["ask_price_cents"]),
      })
    )

    expect(h.sendContextualUpdate).not.toHaveBeenCalled()
  })

  it("a blocked microphone shows a toast and keeps the card editable", async () => {
    render(ui({}))
    const options = await start()

    act(() => options.onError("Permission denied", { name: "NotAllowedError" }))

    expect(h.toastError).toHaveBeenCalledWith(
      "Microphone blocked — edit the card instead"
    )
    // Nothing locks: the button to try again is still there.
    expect(screen.getByRole("button", { name: "Talk it through" })).toBeTruthy()
  })

  it("any other failure also points back to the card", async () => {
    render(ui({}))
    const options = await start()

    act(() => options.onError("Connection lost"))

    expect(h.toastError).toHaveBeenCalledWith(
      "The conversation hit a problem — edit the card instead"
    )
  })

  it("shows the live state: orb, status line, captions and End", async () => {
    const user = userEvent.setup()
    render(ui({}))
    const options = await start()

    expect(screen.getByText("Connecting…")).toBeTruthy()
    expect(screen.getByTestId("orb").dataset.agentState).toBe("thinking")

    connect(options)
    expect(screen.getByText("Listening")).toBeTruthy()
    expect(screen.getByTestId("orb").dataset.agentState).toBe("listening")

    act(() => h.store.set({ isSpeaking: true }))
    expect(screen.getByText("Speaking")).toBeTruthy()
    expect(screen.getByTestId("orb").dataset.agentState).toBe("talking")

    act(() => {
      options.onMessage({ role: "agent", message: "How many videos?" })
      options.onMessage({ role: "user", message: "Three." })
    })
    const captions = screen.getByRole("log", { name: "Captions" })
    expect(captions.getAttribute("aria-live")).toBe("polite")
    expect(captions.textContent).toContain("AgentHow many videos?")
    expect(captions.textContent).toContain("YouThree.")

    await user.click(screen.getByRole("button", { name: "End conversation" }))
    expect(h.endSession).toHaveBeenCalled()
  })

  it("offers Resume once a session has ended", async () => {
    render(ui({}))
    const options = await start()
    connect(options)

    act(() => options.onDisconnect({ reason: "agent" }))

    expect(screen.getByText("Ended")).toBeTruthy()
    expect(screen.getByRole("button", { name: "Resume" })).toBeTruthy()
  })

  it("draws no moving orb when the user prefers reduced motion", async () => {
    h.reduced.current = true
    render(ui({}))
    const options = await start()
    connect(options)

    expect(screen.queryByTestId("orb")).toBeNull()
    expect(screen.getByText("Listening")).toBeTruthy()
  })
})
