/** The name the PCM worklet registers its processor under. */
export const PCM_PROCESSOR = "collabio-pcm"

/**
 * Audio-thread code that turns microphone audio into 16-bit PCM chunks at the output
 * rate (linear resampling when the input runs faster), posting `{ audio }` per full
 * chunk. Posting `"flush"` to it posts whatever is short of a chunk, then
 * `{ flushed: true }`, so the last words reach Scribe instead of waiting for a chunk
 * that never fills.
 *
 * It runs in the AudioWorklet global scope, so it is plain JavaScript in a string,
 * loaded from a Blob URL. Options arrive as `processorOptions`:
 * `{ inputRate, outputRate, chunkSamples }`.
 */
export const PCM_WORKLET_SOURCE = `
class CollabioPcm extends AudioWorkletProcessor {
  constructor(options) {
    super()
    const { inputRate, outputRate, chunkSamples } = options.processorOptions
    this.step = inputRate / outputRate
    this.chunk = new Int16Array(chunkSamples)
    this.filled = 0
    // Where the next output sample falls, counted in input samples from the last
    // sample of the previous block (index 0).
    this.position = 0
    this.previous = 0
    this.port.onmessage = ({ data }) => {
      if (data !== "flush") return
      this.post()
      this.port.postMessage({ flushed: true })
    }
  }

  push(sample) {
    const clamped = Math.max(-1, Math.min(1, sample))
    this.chunk[this.filled++] = clamped < 0 ? clamped * 32768 : clamped * 32767
    if (this.filled === this.chunk.length) this.post()
  }

  post() {
    if (this.filled === 0) return
    const audio = this.chunk.slice(0, this.filled)
    this.filled = 0
    this.port.postMessage({ audio: audio.buffer }, [audio.buffer])
  }

  process(inputs) {
    const samples = inputs[0] && inputs[0][0]
    if (!samples || samples.length === 0) return true
    if (this.step === 1) {
      for (let i = 0; i < samples.length; i++) this.push(samples[i])
      return true
    }
    const at = (index) => (index === 0 ? this.previous : samples[index - 1])
    while (this.position < samples.length) {
      const index = Math.floor(this.position)
      const fraction = this.position - index
      const from = at(index)
      this.push(from + (at(index + 1) - from) * fraction)
      this.position += this.step
    }
    this.position -= samples.length
    this.previous = samples[samples.length - 1]
    return true
  }
}

registerProcessor("${PCM_PROCESSOR}", CollabioPcm)
`
