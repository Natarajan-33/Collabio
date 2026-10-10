import { act, cleanup, renderHook } from "@testing-library/react"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import {
  COMMIT_WAIT_MS,
  CONNECT_WAIT_MS,
  useCommandCapture,
} from "@/lib/voice/use-command-capture"

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
    commit: vi.fn(),
    sendAudio: vi.fn(),
  },
  options: null as unknown,
  api: { POST: vi.fn() },
  mic: { pipe: vi.fn(), stop: vi.fn(), close: vi.fn() },
  openMicrophone: vi.fn(),
}))

/** The callbacks the hook gave `useScribe`: how tests play Scribe's side. */
function scribe() {
  return h.options as ScribeOptions
}

/** The microphone handing `chunks` to whatever the hook piped it to. */
function hear(...chunks: string[]) {
  const send = h.mic.pipe.mock.lastCall?.[0] as (chunk: string) => void
  for (const chunk of chunks) send(chunk)
}

vi.mock("@elevenlabs/react", () => ({
  AudioFormat: { PCM_16000: "pcm_16000" },
  useScribe: (options: unknown) => {
    h.options = options
    return h.scribe
  },
}))
vi.mock("@/hooks/use-api", () => ({ useApi: () => h.api }))
vi.mock("@/lib/voice/microphone", () => ({
  PCM_SAMPLE_RATE: 16000,
  openMicrophone: h.openMicrophone,
}))

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

/**
 * Lets go and waits for the command. By default Scribe answers the commit at once with
 * `commit` (nothing new when omitted); `null` leaves the commit unanswered.
 */
async function released(
  hook: ReturnType<typeof setup>,
  commit: string | null = ""
) {
  h.scribe.commit.mockImplementation(() => {
    if (commit !== null) scribe().onCommittedTranscript?.({ text: commit })
  })
  await act(async () => {
    await hook.result.current.stop()
  })
}

/** Presses: the microphone opens, the token and the connection settle. */
async function pressed(hook: ReturnType<typeof setup>) {
  await act(async () => {
    await hook.result.current.start()
  })
}

/** Presses and lets Scribe start, so what is heard streams to it. */
async function started(hook: ReturnType<typeof setup>) {
  await pressed(hook)
  act(() => scribe().onSessionStarted?.())
}

beforeEach(() => {
  h.scribe.connect.mockReset().mockResolvedValue(undefined)
  h.scribe.disconnect.mockReset()
  h.scribe.commit.mockReset()
  h.scribe.sendAudio.mockReset()
  h.api.POST.mockReset().mockResolvedValue(token("tok-1"))
  h.mic.pipe.mockReset()
  h.mic.stop.mockReset().mockResolvedValue(undefined)
  h.mic.close.mockReset()
  h.openMicrophone.mockReset().mockResolvedValue(h.mic)
  h.options = null
})

afterEach(cleanup)

describe("useCommandCapture", () => {
  it("mints a fresh token for each capture and connects with it for 16 kHz PCM", async () => {
    h.api.POST.mockResolvedValueOnce(token("tok-1")).mockResolvedValueOnce(
      token("tok-2")
    )
    const hook = setup()

    await started(hook)
    await released(hook)
    await started(hook)

    expect(h.api.POST).toHaveBeenCalledTimes(2)
    expect(h.api.POST).toHaveBeenCalledWith("/api/v1/voice/scribe-token")
    expect(h.scribe.connect).toHaveBeenNthCalledWith(1, {
      token: "tok-1",
      audioFormat: "pcm_16000",
      sampleRate: 16000,
    })
    expect(h.scribe.connect).toHaveBeenNthCalledWith(2, {
      token: "tok-2",
      audioFormat: "pcm_16000",
      sampleRate: 16000,
    })
    expect(h.openMicrophone).toHaveBeenCalledTimes(2)
  })

  it("uses the realtime Scribe model", () => {
    setup()

    expect(scribe().modelId).toBe("scribe_v2_realtime")
  })

  it("opens the microphone at once, without waiting for the token", async () => {
    h.api.POST.mockReturnValue(new Promise(() => {}))
    const hook = setup()

    await act(async () => {
      void hook.result.current.start()
      await Promise.resolve()
    })

    expect(h.openMicrophone).toHaveBeenCalledTimes(1)
    // Listening from here on, though Scribe is not up yet.
    expect(hook.handlers.onConnected).toHaveBeenCalledTimes(1)
    expect(h.scribe.connect).not.toHaveBeenCalled()
  })

  it("sends what was heard while connecting once Scribe starts, then the rest as it comes", async () => {
    const hook = setup()
    await pressed(hook)
    expect(h.mic.pipe).not.toHaveBeenCalled()

    act(() => scribe().onSessionStarted?.())
    hear("chunk-1", "chunk-2")

    expect(h.mic.pipe).toHaveBeenCalledTimes(1)
    expect(h.scribe.sendAudio.mock.calls).toEqual([["chunk-1"], ["chunk-2"]])
  })

  it("a chunk for a socket that has closed is dropped", async () => {
    const hook = setup()
    await started(hook)
    h.scribe.sendAudio.mockImplementation(() => {
      throw new Error("WebSocket is not open")
    })

    expect(() => hear("chunk")).not.toThrow()
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

    await released(hook)

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
    await released(hook)

    expect(hook.handlers.onFinal).toHaveBeenCalledWith("Tech creators")
  })

  it("stop with nothing heard reports an empty command", async () => {
    const hook = setup()
    await started(hook)

    await released(hook)

    expect(hook.handlers.onFinal).toHaveBeenCalledExactlyOnceWith("")
  })

  it("stop without a capture does nothing", async () => {
    const hook = setup()

    await act(async () => hook.result.current.stop())

    expect(hook.handlers.onFinal).not.toHaveBeenCalled()
    expect(h.scribe.disconnect).not.toHaveBeenCalled()
    expect(h.scribe.commit).not.toHaveBeenCalled()
  })

  it("words said before the token arrives are still heard once Scribe starts", async () => {
    let release!: (value: unknown) => void
    h.api.POST.mockReturnValue(new Promise((resolve) => (release = resolve)))
    const hook = setup()
    let starting!: Promise<void>
    await act(async () => {
      starting = hook.result.current.start()
      await Promise.resolve()
    })
    expect(hook.handlers.onConnected).toHaveBeenCalledTimes(1)

    // A quick command: let go while the token is still on its way.
    let stopping!: Promise<void>
    act(() => {
      stopping = hook.result.current.stop()
    })
    await act(async () => {
      release(token("late"))
      await starting
    })
    expect(h.mic.stop).toHaveBeenCalledTimes(1)
    expect(h.scribe.connect).toHaveBeenCalledTimes(1)
    expect(hook.handlers.onFinal).not.toHaveBeenCalled()

    h.scribe.commit.mockImplementation(() =>
      scribe().onCommittedTranscript?.({ text: "Go to packages." })
    )
    act(() => scribe().onSessionStarted?.())
    hear("held-1", "held-2")
    await act(async () => stopping)

    expect(h.scribe.sendAudio.mock.calls).toEqual([["held-1"], ["held-2"]])
    expect(h.scribe.commit).toHaveBeenCalledTimes(1)
    expect(hook.handlers.onFinal).toHaveBeenCalledExactlyOnceWith(
      "Go to packages."
    )
    expect(hook.handlers.onError).not.toHaveBeenCalled()
  })

  it("a press let go before the microphone opens is simply over", async () => {
    let open!: (mic: unknown) => void
    h.openMicrophone.mockReturnValue(new Promise((resolve) => (open = resolve)))
    const hook = setup()

    let starting!: Promise<void>
    act(() => {
      starting = hook.result.current.start()
    })
    await act(async () => hook.result.current.stop())
    await act(async () => {
      open(h.mic)
      await starting
    })

    expect(hook.handlers.onFinal).toHaveBeenCalledExactlyOnceWith("")
    // The microphone that opened late is let go, and nothing connects.
    expect(h.mic.close).toHaveBeenCalled()
    expect(hook.handlers.onConnected).not.toHaveBeenCalled()
    expect(h.scribe.connect).not.toHaveBeenCalled()
    expect(h.scribe.commit).not.toHaveBeenCalled()
  })

  it("gives up on a Scribe that never starts after the press is let go", async () => {
    vi.useFakeTimers()
    try {
      const hook = setup()
      await pressed(hook)

      let stopping!: Promise<void>
      act(() => {
        stopping = hook.result.current.stop()
      })
      await act(async () => {
        await vi.advanceTimersByTimeAsync(CONNECT_WAIT_MS - 1)
      })
      expect(hook.handlers.onError).not.toHaveBeenCalled()

      await act(async () => {
        await vi.advanceTimersByTimeAsync(1)
        await stopping
      })

      expect(hook.handlers.onError).toHaveBeenCalledExactlyOnceWith({
        reason: "Voice connection failed",
        fatal: false,
      })
      expect(hook.handlers.onFinal).not.toHaveBeenCalled()
      expect(h.mic.close).toHaveBeenCalled()
      expect(h.scribe.commit).not.toHaveBeenCalled()
    } finally {
      vi.useRealTimers()
    }
  })

  it("ignores events that arrive after stop", async () => {
    const hook = setup()
    await started(hook)
    await released(hook)
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
    await released(hook)

    await started(hook)
    act(() => scribe().onPartialTranscript?.({ text: "second" }))
    await released(hook)

    expect(hook.handlers.onFinal).toHaveBeenLastCalledWith("second")
  })

  it("only one capture runs at a time", async () => {
    const hook = setup()

    await started(hook)
    await started(hook)

    expect(h.api.POST).toHaveBeenCalledTimes(1)
    expect(h.openMicrophone).toHaveBeenCalledTimes(1)
    expect(h.scribe.connect).toHaveBeenCalledTimes(1)
  })

  it("going away lets the microphone go", async () => {
    const hook = setup()
    await started(hook)

    hook.unmount()

    expect(h.mic.close).toHaveBeenCalled()
  })

  describe("releasing", () => {
    /**
     * Lets go, lets the microphone finish its tail (at once here), and leaves the
     * commit unanswered, as Scribe does until it has caught up.
     */
    async function letGo(hook: ReturnType<typeof setup>) {
      h.scribe.commit.mockReset()
      let stopping!: Promise<void>
      await act(async () => {
        stopping = hook.result.current.stop()
        for (let tick = 0; tick < 5; tick++) await Promise.resolve()
      })
      return { stopping }
    }

    it("lets the microphone hear the last syllable before committing", async () => {
      let finish!: () => void
      h.mic.stop.mockReturnValue(
        new Promise<void>((resolve) => (finish = resolve))
      )
      const hook = setup()
      await started(hook)

      const { stopping } = await letGo(hook)
      expect(h.mic.stop).toHaveBeenCalledTimes(1)
      expect(h.scribe.commit).not.toHaveBeenCalled()

      h.scribe.commit.mockImplementation(() =>
        scribe().onCommittedTranscript?.({ text: "Select the top ten." })
      )
      await act(async () => {
        finish()
        await stopping
      })

      expect(h.scribe.commit).toHaveBeenCalledTimes(1)
      expect(hook.handlers.onFinal).toHaveBeenCalledExactlyOnceWith(
        "Select the top ten."
      )
    })

    it("commits what was said and waits for it instead of dropping the last words", async () => {
      const hook = setup()
      await started(hook)
      act(() => scribe().onPartialTranscript?.({ text: "select the top" }))

      const { stopping } = await letGo(hook)

      expect(h.scribe.commit).toHaveBeenCalledTimes(1)
      // Still listening for the committed words: nothing is reported or cut off yet.
      expect(hook.handlers.onFinal).not.toHaveBeenCalled()
      expect(h.scribe.disconnect).not.toHaveBeenCalled()

      act(() =>
        scribe().onCommittedTranscript?.({ text: "Select the top ten." })
      )
      await act(async () => stopping)

      // The committed text carries the words that were still in flight.
      expect(hook.handlers.onFinal).toHaveBeenCalledExactlyOnceWith(
        "Select the top ten."
      )
      expect(h.scribe.disconnect).toHaveBeenCalledTimes(1)
    })

    it("keeps the words committed earlier in front of the final commit", async () => {
      const hook = setup()
      await started(hook)
      act(() => scribe().onCommittedTranscript?.({ text: "Tech creators." }))
      act(() => scribe().onPartialTranscript?.({ text: "under two" }))

      const { stopping } = await letGo(hook)
      act(() =>
        scribe().onCommittedTranscript?.({ text: "Under two thousand." })
      )
      await act(async () => stopping)

      expect(hook.handlers.onFinal).toHaveBeenCalledExactlyOnceWith(
        "Tech creators. Under two thousand."
      )
    })

    it("falls back to what was heard if the commit never arrives", async () => {
      vi.useFakeTimers()
      try {
        const hook = setup()
        await started(hook)
        act(() => scribe().onPartialTranscript?.({ text: "select the top" }))

        const { stopping } = await letGo(hook)
        await act(async () => {
          await vi.advanceTimersByTimeAsync(COMMIT_WAIT_MS - 1)
        })
        expect(hook.handlers.onFinal).not.toHaveBeenCalled()

        await act(async () => {
          await vi.advanceTimersByTimeAsync(1)
          await stopping
        })

        expect(hook.handlers.onFinal).toHaveBeenCalledExactlyOnceWith(
          "select the top"
        )
        expect(h.scribe.disconnect).toHaveBeenCalledTimes(1)
        expect(hook.handlers.onError).not.toHaveBeenCalled()
      } finally {
        vi.useRealTimers()
      }
    })

    it("does not wait out the clock once the commit is in", async () => {
      vi.useFakeTimers()
      try {
        const hook = setup()
        await started(hook)

        const { stopping } = await letGo(hook)
        act(() => scribe().onCommittedTranscript?.({ text: "Go to packages" }))
        await act(async () => stopping)

        expect(hook.handlers.onFinal).toHaveBeenCalledExactlyOnceWith(
          "Go to packages"
        )
        // A leftover timer would fire a second report later.
        expect(vi.getTimerCount()).toBe(0)
      } finally {
        vi.useRealTimers()
      }
    })

    it("an empty commit does not erase what was heard", async () => {
      const hook = setup()
      await started(hook)
      act(() => scribe().onPartialTranscript?.({ text: "open review" }))

      const { stopping } = await letGo(hook)
      act(() => scribe().onCommittedTranscript?.({ text: "" }))
      await act(async () => stopping)

      expect(hook.handlers.onFinal).toHaveBeenCalledExactlyOnceWith(
        "open review"
      )
    })

    it("a press too short to commit is simply over", async () => {
      const hook = setup()
      await started(hook)
      h.scribe.commit.mockReset().mockImplementation(() => {
        throw new Error("WebSocket is not connected")
      })

      await act(async () => hook.result.current.stop())

      expect(hook.handlers.onFinal).toHaveBeenCalledExactlyOnceWith("")
      expect(h.scribe.disconnect).toHaveBeenCalledTimes(1)
      expect(hook.handlers.onError).not.toHaveBeenCalled()
    })

    it("a hiccup from Scribe while waiting still delivers what was heard", async () => {
      const hook = setup()
      await started(hook)
      act(() => scribe().onPartialTranscript?.({ text: "select the top" }))

      const { stopping } = await letGo(hook)
      // Say, a commit with too little audio behind it.
      act(() => scribe().onError?.(new Error("insufficient audio activity")))
      await act(async () => stopping)

      expect(hook.handlers.onFinal).toHaveBeenCalledExactlyOnceWith(
        "select the top"
      )
      expect(hook.handlers.onError).not.toHaveBeenCalled()
    })

    it("the socket closing while waiting delivers what was heard", async () => {
      const hook = setup()
      await started(hook)
      act(() => scribe().onPartialTranscript?.({ text: "select the top" }))

      const { stopping } = await letGo(hook)
      act(() => scribe().onDisconnect?.())
      await act(async () => stopping)

      expect(hook.handlers.onFinal).toHaveBeenCalledExactlyOnceWith(
        "select the top"
      )
      expect(hook.handlers.onError).not.toHaveBeenCalled()
    })

    it("a fatal failure while waiting is still a failure, not a command", async () => {
      const hook = setup()
      await started(hook)
      act(() => scribe().onPartialTranscript?.({ text: "select the top" }))

      const { stopping } = await letGo(hook)
      act(() => scribe().onQuotaExceededError?.({ error: "quota" }))
      act(() => scribe().onError?.(new Error("quota")))
      await act(async () => stopping)

      expect(hook.handlers.onError).toHaveBeenCalledExactlyOnceWith({
        reason: "Voice usage limit reached",
        fatal: true,
      })
      expect(hook.handlers.onFinal).not.toHaveBeenCalled()
    })

    it("letting go twice reports the command once", async () => {
      const hook = setup()
      await started(hook)

      const { stopping: first } = await letGo(hook)
      const second = hook.result.current.stop()
      act(() => scribe().onCommittedTranscript?.({ text: "Hello" }))
      await act(async () => {
        await first
        await second
      })

      expect(h.scribe.commit).toHaveBeenCalledTimes(1)
      expect(hook.handlers.onFinal).toHaveBeenCalledExactlyOnceWith("Hello")
    })

    it("ignores words that arrive after the report", async () => {
      const hook = setup()
      await started(hook)
      await released(hook, "Hello")
      hook.handlers.onPartial.mockClear()

      act(() => scribe().onCommittedTranscript?.({ text: "Hello again" }))

      expect(hook.handlers.onPartial).not.toHaveBeenCalled()
      expect(hook.handlers.onFinal).toHaveBeenCalledTimes(1)
    })
  })

  describe("failures", () => {
    it.each([503, 401])(
      "a %s from the token endpoint is fatal and lets the microphone go",
      async (status) => {
        h.api.POST.mockResolvedValue({ error: {}, response: { status } })
        const hook = setup()

        await pressed(hook)

        expect(hook.handlers.onError).toHaveBeenCalledExactlyOnceWith({
          reason: "Voice is unavailable",
          fatal: true,
        })
        expect(h.mic.close).toHaveBeenCalled()
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
      ["NotAllowedError", "Microphone blocked"],
      ["SecurityError", "Microphone blocked"],
      ["NotFoundError", "No microphone found"],
      ["OverconstrainedError", "No microphone found"],
      ["NotReadableError", "Microphone unavailable"],
      ["TypeError", "Microphone unavailable"],
    ])("a microphone that fails with %s is fatal", async (name, reason) => {
      h.openMicrophone.mockRejectedValue(new DOMException("No", name))
      const hook = setup()

      await pressed(hook)

      expect(hook.handlers.onError).toHaveBeenCalledExactlyOnceWith({
        reason,
        fatal: true,
      })
      expect(hook.handlers.onConnected).not.toHaveBeenCalled()
      expect(h.scribe.connect).not.toHaveBeenCalled()
    })

    it("a failure lets the microphone go", async () => {
      const hook = setup()
      await started(hook)

      act(() => scribe().onError?.(new Error("WebSocket error")))

      expect(h.mic.close).toHaveBeenCalled()
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
