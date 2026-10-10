import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import {
  openMicrophone,
  PCM_SAMPLE_RATE,
  RELEASE_TAIL_MS,
} from "@/lib/voice/microphone"
import { PCM_PROCESSOR } from "@/lib/voice/pcm-worklet"

type Port = {
  onmessage: ((event: { data: unknown }) => void) | null
  postMessage: ReturnType<typeof vi.fn>
}

const h = vi.hoisted(() => ({
  track: { stop: vi.fn(), getSettings: vi.fn() },
  getUserMedia: vi.fn(),
  contexts: [] as FakeContext[],
  nodes: [] as { options: unknown; port: Port; disconnect: () => void }[],
  addModule: vi.fn(),
}))

type FakeContext = {
  options: unknown
  sampleRate: number
  state: string
  close: ReturnType<typeof vi.fn>
  resume: ReturnType<typeof vi.fn>
  source: { connect: ReturnType<typeof vi.fn> }
}

class FakeAudioContext {
  options: unknown
  sampleRate: number
  state = "suspended"
  close = vi.fn(() => Promise.resolve())
  resume = vi.fn(() => Promise.resolve())
  source = { connect: vi.fn() }
  audioWorklet = { addModule: h.addModule }
  constructor(options?: { sampleRate?: number }) {
    this.options = options
    this.sampleRate = options?.sampleRate ?? 48000
    h.contexts.push(this as unknown as FakeContext)
  }
  createMediaStreamSource() {
    return this.source
  }
}

class FakeAudioWorkletNode {
  port: Port = { onmessage: null, postMessage: vi.fn() }
  disconnect = vi.fn()
  constructor(
    _context: unknown,
    readonly name: string,
    readonly options: unknown
  ) {
    h.nodes.push(this)
  }
}

/** The worklet posting audio, as the audio thread would. */
function post(data: unknown) {
  h.nodes[0].port.onmessage?.({ data })
}

function pcm(...samples: number[]) {
  return { audio: Int16Array.from(samples).buffer }
}

function base64(...samples: number[]) {
  const bytes = new Uint8Array(Int16Array.from(samples).buffer)
  return btoa(String.fromCharCode(...bytes))
}

beforeEach(() => {
  h.contexts.length = 0
  h.nodes.length = 0
  h.track.stop.mockReset()
  h.track.getSettings.mockReset().mockReturnValue({ sampleRate: 48000 })
  h.addModule.mockReset().mockResolvedValue(undefined)
  h.getUserMedia.mockReset().mockResolvedValue({
    getTracks: () => [h.track],
    getAudioTracks: () => [h.track],
  })
  vi.stubGlobal("navigator", { mediaDevices: { getUserMedia: h.getUserMedia } })
  vi.stubGlobal("AudioContext", FakeAudioContext)
  vi.stubGlobal("AudioWorkletNode", FakeAudioWorkletNode)
  URL.createObjectURL ??= () => "blob:worklet"
})

afterEach(() => {
  vi.unstubAllGlobals()
  vi.useRealTimers()
})

describe("openMicrophone", () => {
  it("asks for one cleaned-up voice channel", async () => {
    await openMicrophone()

    expect(h.getUserMedia).toHaveBeenCalledExactlyOnceWith({
      audio: {
        echoCancellation: true,
        noiseSuppression: true,
        autoGainControl: true,
        channelCount: 1,
        sampleRate: { ideal: PCM_SAMPLE_RATE },
      },
    })
  })

  it("runs the audio at the microphone's own rate and resamples it to Scribe's", async () => {
    await openMicrophone()

    // Firefox refuses to connect a stream to a context at a different rate.
    expect(h.contexts[0].options).toEqual({ sampleRate: 48000 })
    expect(h.addModule).toHaveBeenCalledTimes(1)
    expect(h.nodes[0]).toMatchObject({
      name: PCM_PROCESSOR,
      options: {
        processorOptions: {
          inputRate: 48000,
          outputRate: PCM_SAMPLE_RATE,
          chunkSamples: 1600,
        },
      },
    })
    expect(h.contexts[0].source.connect).toHaveBeenCalledWith(h.nodes[0])
    expect(h.contexts[0].resume).toHaveBeenCalled()
  })

  it("holds what it hears until something takes it, then passes it on as it comes", async () => {
    const mic = await openMicrophone()
    post(pcm(1, 2))
    post(pcm(3))

    const send = vi.fn()
    mic.pipe(send)
    expect(send.mock.calls).toEqual([[base64(1, 2)], [base64(3)]])

    post(pcm(4))
    expect(send).toHaveBeenLastCalledWith(base64(4))
    expect(send).toHaveBeenCalledTimes(3)
  })

  it("stop keeps listening for the tail, hands on what is left, then lets the microphone go", async () => {
    vi.useFakeTimers()
    const mic = await openMicrophone()
    const send = vi.fn()
    mic.pipe(send)

    let stopped = false
    const stopping = mic.stop().then(() => (stopped = true))
    await vi.advanceTimersByTimeAsync(RELEASE_TAIL_MS - 1)
    // The last syllable is still being heard.
    expect(h.nodes[0].port.postMessage).not.toHaveBeenCalled()
    post(pcm(5))

    await vi.advanceTimersByTimeAsync(1)
    expect(h.nodes[0].port.postMessage).toHaveBeenCalledExactlyOnceWith("flush")
    expect(stopped).toBe(false)
    post(pcm(6))
    post({ flushed: true })
    await stopping

    expect(send.mock.calls).toEqual([[base64(5)], [base64(6)]])
    expect(h.track.stop).toHaveBeenCalled()
    expect(h.contexts[0].close).toHaveBeenCalled()
  })

  it("stop does not wait forever for a worklet that never answers", async () => {
    vi.useFakeTimers()
    const mic = await openMicrophone()

    const stopping = mic.stop()
    await vi.advanceTimersByTimeAsync(RELEASE_TAIL_MS + 1000)
    await stopping

    expect(h.track.stop).toHaveBeenCalled()
    expect(vi.getTimerCount()).toBe(0)
  })

  it("close lets the microphone go at once and drops what comes after", async () => {
    const mic = await openMicrophone()
    const send = vi.fn()
    mic.pipe(send)

    mic.close()
    post(pcm(7))

    expect(h.track.stop).toHaveBeenCalled()
    expect(h.contexts[0].close).toHaveBeenCalled()
    expect(send).not.toHaveBeenCalled()
  })

  it("close during a stop ends the stop without leaving a timer behind", async () => {
    vi.useFakeTimers()
    const mic = await openMicrophone()

    const stopping = mic.stop()
    await vi.advanceTimersByTimeAsync(RELEASE_TAIL_MS)
    mic.close()
    await stopping

    expect(vi.getTimerCount()).toBe(0)
  })

  it("lets the microphone go when the audio setup fails after it opened", async () => {
    h.addModule.mockRejectedValue(new Error("worklet failed"))

    await expect(openMicrophone()).rejects.toThrow("worklet failed")

    expect(h.track.stop).toHaveBeenCalled()
    expect(h.contexts[0].close).toHaveBeenCalled()
  })

  it("passes on the browser's refusal", async () => {
    const denied = new DOMException("Permission denied", "NotAllowedError")
    h.getUserMedia.mockRejectedValue(denied)

    await expect(openMicrophone()).rejects.toBe(denied)
    expect(h.contexts).toHaveLength(0)
  })
})
