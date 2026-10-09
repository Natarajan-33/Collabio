import { act, cleanup, renderHook } from "@testing-library/react"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import { useCommandCapture } from "@/lib/voice/use-command-capture"

type ScribeOptions = {
  modelId?: string
  onSessionStarted?: () => void
  onPartialTranscript?: (data: { text: string }) => void
  onCommittedTranscript?: (data: { text: string }) => void
  onError?: (error: Error | Event) => void
  onAuthError?: (data: { error: string }) => void
  onQuotaExceededError?: (data: { error: string }) => void
  onUnacceptedTermsError?: (data: { error: string }) => void
  onDisconnect?: () => void
}

const h = vi.hoisted(() => ({
  scribe: {
    status: "disconnected",
    connect: vi.fn(),
    disconnect: vi.fn(),
  },
  options: null as unknown,
  api: { POST: vi.fn() },
}))

/** The callbacks the hook gave `useScribe`: how tests play Scribe's side. */
function scribe() {
  return h.options as ScribeOptions
}

vi.mock("@elevenlabs/react", () => ({
  useScribe: (options: unknown) => {
    h.options = options
    return h.scribe
  },
}))
vi.mock("@/hooks/use-api", () => ({ useApi: () => h.api }))

const token = (value: string) => ({
  data: { token: value, expires_at: "2099-01-01T00:00:00Z" },
  response: { status: 200 },
})

function setup() {
  const handlers = {
    onConnected: vi.fn(),
    onPartial: vi.fn(),
    onFinal: vi.fn(),
    onError: vi.fn(),
  }
  const hook = renderHook(() => useCommandCapture(handlers))
  return { ...hook, handlers }
}

/** Starts a capture and lets the token and the connection settle. */
async function started(hook: ReturnType<typeof setup>) {
  await act(async () => {
    await hook.result.current.start()
  })
}

beforeEach(() => {
  h.scribe.connect.mockReset().mockResolvedValue(undefined)
  h.scribe.disconnect.mockReset()
  h.api.POST.mockReset().mockResolvedValue(token("tok-1"))
  h.options = null
})

afterEach(cleanup)

describe("useCommandCapture", () => {
  it("mints a fresh token for each capture and opens the microphone with it", async () => {
    h.api.POST.mockResolvedValueOnce(token("tok-1")).mockResolvedValueOnce(
      token("tok-2")
    )
    const hook = setup()

    await started(hook)
    act(() => hook.result.current.stop())
    await started(hook)

    expect(h.api.POST).toHaveBeenCalledTimes(2)
    expect(h.api.POST).toHaveBeenCalledWith("/api/v1/voice/scribe-token")
    expect(h.scribe.connect).toHaveBeenNthCalledWith(1, {
      token: "tok-1",
      microphone: { echoCancellation: true, noiseSuppression: true },
    })
    expect(h.scribe.connect).toHaveBeenNthCalledWith(2, {
      token: "tok-2",
      microphone: { echoCancellation: true, noiseSuppression: true },
    })
  })

  it("uses the realtime Scribe model", () => {
    setup()

    expect(scribe().modelId).toBe("scribe_v2_realtime")
  })

  it("reports when the session is live", async () => {
    const hook = setup()
    await started(hook)

    act(() => scribe().onSessionStarted?.())

    expect(hook.handlers.onConnected).toHaveBeenCalledTimes(1)
  })

  it("reports what is heard as it forms", async () => {
    const hook = setup()
    await started(hook)

    act(() => scribe().onPartialTranscript?.({ text: "tech" }))
    act(() => scribe().onPartialTranscript?.({ text: "tech creators" }))

    expect(hook.handlers.onPartial).toHaveBeenLastCalledWith("tech creators")
  })

  it("stop reports committed transcripts plus the current partial, then disconnects", async () => {
    const hook = setup()
    await started(hook)
    act(() => scribe().onCommittedTranscript?.({ text: "Tech creators." }))
    act(() => scribe().onCommittedTranscript?.({ text: "Doing reviews" }))
    act(() => scribe().onPartialTranscript?.({ text: " under two thousand" }))
    // The partial counts into the live text alongside what is committed.
    expect(hook.handlers.onPartial).toHaveBeenLastCalledWith(
      "Tech creators. Doing reviews under two thousand"
    )

    act(() => hook.result.current.stop())

    expect(hook.handlers.onFinal).toHaveBeenCalledExactlyOnceWith(
      "Tech creators. Doing reviews under two thousand"
    )
    expect(h.scribe.disconnect).toHaveBeenCalledTimes(1)
  })

  it("a committed segment replaces the partial it came from", async () => {
    const hook = setup()
    await started(hook)

    act(() => scribe().onPartialTranscript?.({ text: "tech creat" }))
    act(() => scribe().onCommittedTranscript?.({ text: "Tech creators" }))
    act(() => hook.result.current.stop())

    expect(hook.handlers.onFinal).toHaveBeenCalledWith("Tech creators")
  })

  it("stop with nothing heard reports an empty command", async () => {
    const hook = setup()
    await started(hook)

    act(() => hook.result.current.stop())

    expect(hook.handlers.onFinal).toHaveBeenCalledExactlyOnceWith("")
  })

  it("stop without a capture does nothing", () => {
    const hook = setup()

    act(() => hook.result.current.stop())

    expect(hook.handlers.onFinal).not.toHaveBeenCalled()
    expect(h.scribe.disconnect).not.toHaveBeenCalled()
  })

  it("releasing before the token arrives cancels the capture", async () => {
    let release!: (value: unknown) => void
    h.api.POST.mockReturnValue(new Promise((resolve) => (release = resolve)))
    const hook = setup()

    let starting!: Promise<void>
    act(() => {
      starting = hook.result.current.start()
    })
    act(() => hook.result.current.stop())
    await act(async () => {
      release(token("late"))
      await starting
    })

    expect(hook.handlers.onFinal).toHaveBeenCalledExactlyOnceWith("")
    // The microphone is never opened for a press that is already over.
    expect(h.scribe.connect).not.toHaveBeenCalled()
    expect(hook.handlers.onError).not.toHaveBeenCalled()
  })

  it("ignores events that arrive after stop", async () => {
    const hook = setup()
    await started(hook)
    act(() => hook.result.current.stop())
    hook.handlers.onPartial.mockClear()

    act(() => scribe().onPartialTranscript?.({ text: "late words" }))
    act(() => scribe().onCommittedTranscript?.({ text: "late words" }))
    act(() => scribe().onError?.(new Error("WebSocket error")))
    act(() => scribe().onDisconnect?.())

    expect(hook.handlers.onPartial).not.toHaveBeenCalled()
    expect(hook.handlers.onError).not.toHaveBeenCalled()
    expect(hook.handlers.onFinal).toHaveBeenCalledTimes(1)
  })

  it("the next capture starts clean", async () => {
    const hook = setup()
    await started(hook)
    act(() => scribe().onCommittedTranscript?.({ text: "first" }))
    act(() => hook.result.current.stop())

    await started(hook)
    act(() => scribe().onPartialTranscript?.({ text: "second" }))
    act(() => hook.result.current.stop())

    expect(hook.handlers.onFinal).toHaveBeenLastCalledWith("second")
  })

  it("only one capture runs at a time", async () => {
    const hook = setup()

    await started(hook)
    await started(hook)

    expect(h.api.POST).toHaveBeenCalledTimes(1)
    expect(h.scribe.connect).toHaveBeenCalledTimes(1)
  })

  describe("failures", () => {
    it.each([503, 401])(
      "a %s from the token endpoint is fatal and never opens the microphone",
      async (status) => {
        h.api.POST.mockResolvedValue({ error: {}, response: { status } })
        const hook = setup()

        await started(hook)

        expect(hook.handlers.onError).toHaveBeenCalledExactlyOnceWith({
          reason: "Voice is unavailable",
          fatal: true,
        })
        expect(h.scribe.connect).not.toHaveBeenCalled()
        expect(hook.handlers.onFinal).not.toHaveBeenCalled()
      }
    )

    it("a network error fetching the token is fatal", async () => {
      h.api.POST.mockRejectedValue(new TypeError("fetch failed"))
      const hook = setup()

      await started(hook)

      expect(hook.handlers.onError).toHaveBeenCalledWith({
        reason: "Voice is unavailable",
        fatal: true,
      })
    })

    it("a start that throws is fatal", async () => {
      h.scribe.connect.mockRejectedValue(new Error("Token is required"))
      const hook = setup()

      await started(hook)

      expect(hook.handlers.onError).toHaveBeenCalledExactlyOnceWith({
        reason: "Voice connection failed",
        fatal: true,
      })
    })

    it.each([
      ["Permission denied", "Microphone blocked"],
      ["NotAllowedError: Permission dismissed", "Microphone blocked"],
      ["The request is not allowed by the user agent", "Microphone blocked"],
      ["Requested device not found", "No microphone found"],
    ])("a microphone error (%s) is fatal", async (message, reason) => {
      const hook = setup()
      await started(hook)

      act(() => scribe().onError?.(new Error(message)))

      expect(hook.handlers.onError).toHaveBeenCalledExactlyOnceWith({
        reason,
        fatal: true,
      })
      expect(h.scribe.disconnect).toHaveBeenCalled()
    })

    it("a dropped connection is not fatal", async () => {
      const hook = setup()
      await started(hook)

      act(() => scribe().onError?.(new Error("WebSocket error")))

      expect(hook.handlers.onError).toHaveBeenCalledExactlyOnceWith({
        reason: "Voice connection failed",
        fatal: false,
      })
    })

    it.each([
      ["onAuthError", "Voice sign-in failed"],
      ["onQuotaExceededError", "Voice usage limit reached"],
      ["onUnacceptedTermsError", "Voice terms not accepted"],
    ] as const)(
      "%s is fatal and is reported once",
      async (callback, reason) => {
        const hook = setup()
        await started(hook)

        // Scribe follows each of these with the generic error event.
        act(() => scribe()[callback]?.({ error: "x" }))
        act(() => scribe().onError?.(new Error("x")))

        expect(hook.handlers.onError).toHaveBeenCalledExactlyOnceWith({
          reason,
          fatal: true,
        })
      }
    )

    it("the socket closing under a live capture is a failure, not a command", async () => {
      const hook = setup()
      await started(hook)

      act(() => scribe().onDisconnect?.())

      expect(hook.handlers.onError).toHaveBeenCalledExactlyOnceWith({
        reason: "Voice connection closed",
        fatal: false,
      })
      expect(hook.handlers.onFinal).not.toHaveBeenCalled()
    })

    it("a close from the previous socket does not fail a capture still starting", async () => {
      let release!: (value: unknown) => void
      h.api.POST.mockReturnValue(new Promise((resolve) => (release = resolve)))
      const hook = setup()

      let starting!: Promise<void>
      act(() => {
        starting = hook.result.current.start()
      })
      // The earlier press's socket finishes closing while this one fetches a token.
      act(() => scribe().onDisconnect?.())
      await act(async () => {
        release(token("tok"))
        await starting
      })

      expect(hook.handlers.onError).not.toHaveBeenCalled()
      expect(h.scribe.connect).toHaveBeenCalledTimes(1)
    })

    it("a failed capture can be followed by a new one", async () => {
      const hook = setup()
      await started(hook)
      act(() => scribe().onError?.(new Error("Permission denied")))

      await started(hook)

      expect(h.scribe.connect).toHaveBeenCalledTimes(2)
    })
  })

  it("exposes Scribe's status", () => {
    h.scribe.status = "transcribing"
    const hook = setup()

    expect(hook.result.current.status).toBe("transcribing")
    h.scribe.status = "disconnected"
  })
})
