import { describe, expect, it } from "vitest"

import { PCM_PROCESSOR, PCM_WORKLET_SOURCE } from "@/lib/voice/pcm-worklet"

type Message = { audio?: ArrayBuffer; flushed?: true }

type Processor = {
  port: { onmessage: ((event: { data: unknown }) => void) | null }
  process(inputs: Float32Array[][]): boolean
}

/**
 * Runs the worklet source the way the audio thread would, with stand-ins for the two
 * globals it uses, and returns a processor built with `options` plus what it posted.
 */
function load(options: {
  inputRate: number
  outputRate: number
  chunkSamples: number
}) {
  const posted: Message[] = []
  class FakeAudioWorkletProcessor {
    port = {
      onmessage: null,
      postMessage: (message: Message) => posted.push(message),
    }
  }
  let registered: { name: string; ctor: new (options: unknown) => Processor } =
    null!
  new Function(
    "AudioWorkletProcessor",
    "registerProcessor",
    PCM_WORKLET_SOURCE
  )(
    FakeAudioWorkletProcessor,
    (name: string, ctor: new (options: unknown) => Processor) => {
      registered = { name, ctor }
    }
  )
  const processor = new registered.ctor({ processorOptions: options })
  const flush = () => processor.port.onmessage!({ data: "flush" })
  const feed = (...samples: number[]) =>
    processor.process([[Float32Array.from(samples)]])
  const chunks = () =>
    posted
      .filter((message) => message.audio)
      .map((message) => Array.from(new Int16Array(message.audio!)))
  return { registered, posted, flush, feed, chunks, processor }
}

const SAME_RATE = { inputRate: 16000, outputRate: 16000, chunkSamples: 4 }

describe("the PCM worklet", () => {
  it("registers under the name the microphone asks for", () => {
    expect(load(SAME_RATE).registered.name).toBe(PCM_PROCESSOR)
  })

  it("posts 16-bit chunks of the configured size", () => {
    const worklet = load(SAME_RATE)

    worklet.feed(0.5, -0.5, 1, -1, 0.25)

    expect(worklet.chunks()).toEqual([[16383, -16384, 32767, -32768]])
  })

  it("clamps samples outside -1..1", () => {
    const worklet = load(SAME_RATE)

    worklet.feed(2, -3, 0, 0)

    expect(worklet.chunks()).toEqual([[32767, -32768, 0, 0]])
  })

  it("keeps running when the input has no channels", () => {
    const worklet = load(SAME_RATE)

    expect(worklet.processor.process([[]])).toBe(true)
    expect(worklet.processor.process([])).toBe(true)
    expect(worklet.posted).toEqual([])
  })

  it("a flush posts the samples short of a chunk, then says it is done", () => {
    const worklet = load(SAME_RATE)
    worklet.feed(0.25, 0.25)

    worklet.flush()

    expect(worklet.chunks()).toEqual([[8191, 8191]])
    expect(worklet.posted.at(-1)).toEqual({ flushed: true })
  })

  it("a flush with nothing held only says it is done", () => {
    const worklet = load(SAME_RATE)
    worklet.feed(0, 0, 0, 0)

    worklet.flush()

    expect(worklet.chunks()).toHaveLength(1)
    expect(worklet.posted.at(-1)).toEqual({ flushed: true })
  })

  it("resamples to the output rate across process calls", () => {
    const worklet = load({
      inputRate: 48000,
      outputRate: 16000,
      chunkSamples: 1000,
    })
    // 48 kHz audio arrives 128 frames at a time; three blocks are 8 ms of sound.
    const ramp = Array.from({ length: 384 }, (_, i) => i / 384)
    for (let block = 0; block < 3; block++) {
      worklet.feed(...ramp.slice(block * 128, (block + 1) * 128))
    }
    worklet.flush()

    const [samples] = worklet.chunks()
    expect(samples).toHaveLength(128)
    // Every third input sample, in order: the ramp still rises evenly.
    for (let i = 2; i < samples.length; i++) {
      expect(samples[i] - samples[i - 1]).toBeGreaterThan(200)
      expect(samples[i] - samples[i - 1]).toBeLessThan(310)
    }
  })
})
