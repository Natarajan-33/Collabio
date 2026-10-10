import { PCM_PROCESSOR, PCM_WORKLET_SOURCE } from "@/lib/voice/pcm-worklet"

/** Scribe is told to expect 16 kHz mono 16-bit PCM. */
export const PCM_SAMPLE_RATE = 16000

/**
 * People let go of the key on their last syllable: how long the microphone keeps
 * listening after `stop`.
 */
export const RELEASE_TAIL_MS = 300

/** 100 ms of audio per chunk, so little is still waiting in the worklet at release. */
const CHUNK_SAMPLES = 1600

/** How long `stop` waits for the worklet to hand over the samples it still holds. */
const FLUSH_WAIT_MS = 250

export type Microphone = {
  /** Sends every chunk heard so far to `send`, in order, then each new one as it comes. */
  pipe(send: (chunk: string) => void): void
  /**
   * Listens for {@link RELEASE_TAIL_MS} more, hands on what the worklet still holds,
   * then lets the microphone go.
   */
  stop(): Promise<void>
  /** Lets the microphone go at once. Anything not yet handed on is dropped. */
  close(): void
}

let workletUrl: string | null = null

/** The worklet as a Blob URL, made once: a module URL can be added to many contexts. */
function pcmWorkletUrl() {
  workletUrl ??= URL.createObjectURL(
    new Blob([PCM_WORKLET_SOURCE], { type: "application/javascript" })
  )
  return workletUrl
}

function toBase64(buffer: ArrayBuffer) {
  const bytes = new Uint8Array(buffer)
  let binary = ""
  // In slices: spreading a whole chunk into one call can overflow the stack.
  for (let i = 0; i < bytes.length; i += 0x8000) {
    binary += String.fromCharCode(...bytes.subarray(i, i + 0x8000))
  }
  return btoa(binary)
}

function release(stream: MediaStream, context?: AudioContext) {
  for (const track of stream.getTracks()) track.stop()
  void context?.close()
}

/**
 * Opens the microphone for push-to-talk and starts hearing at once, as base64 PCM
 * chunks for Scribe. Chunks are held until `pipe` takes them, so the words said while
 * Scribe is still connecting are not lost. Rejects with the browser's own error when
 * the microphone cannot be had (a `NotAllowedError` when it is blocked, say).
 */
export async function openMicrophone(): Promise<Microphone> {
  const stream = await navigator.mediaDevices.getUserMedia({
    audio: {
      echoCancellation: true,
      noiseSuppression: true,
      autoGainControl: true,
      channelCount: 1,
      sampleRate: { ideal: PCM_SAMPLE_RATE },
    },
  })

  let context: AudioContext | undefined
  let node: AudioWorkletNode
  try {
    // Firefox refuses to connect a stream to a context running at another rate, so
    // the context takes the microphone's and the worklet resamples.
    const rate = stream.getAudioTracks()[0]?.getSettings().sampleRate
    context = new AudioContext(rate ? { sampleRate: rate } : undefined)
    await context.audioWorklet.addModule(pcmWorkletUrl())
    node = new AudioWorkletNode(context, PCM_PROCESSOR, {
      processorOptions: {
        inputRate: context.sampleRate,
        outputRate: PCM_SAMPLE_RATE,
        chunkSamples: CHUNK_SAMPLES,
      },
    })
    context.createMediaStreamSource(stream).connect(node)
    if (context.state === "suspended") await context.resume()
  } catch (error) {
    release(stream, context)
    throw error
  }

  const held: string[] = []
  let send: ((chunk: string) => void) | null = null
  let flushed: (() => void) | null = null
  let closed = false

  node.port.onmessage = ({ data }) => {
    if (data.audio) {
      const chunk = toBase64(data.audio)
      if (send) send(chunk)
      else held.push(chunk)
    }
    if (data.flushed) flushed?.()
  }

  function close() {
    if (closed) return
    closed = true
    node.port.onmessage = null
    node.disconnect()
    release(stream, context)
    flushed?.()
  }

  return {
    pipe(next) {
      send = next
      for (const chunk of held.splice(0)) next(chunk)
    },
    async stop() {
      if (closed) return
      await new Promise((resolve) => setTimeout(resolve, RELEASE_TAIL_MS))
      if (closed) return
      await new Promise<void>((resolve) => {
        const timer = setTimeout(done, FLUSH_WAIT_MS)
        function done() {
          clearTimeout(timer)
          flushed = null
          resolve()
        }
        flushed = done
        node.port.postMessage("flush")
      })
      close()
    },
    close,
  }
}
