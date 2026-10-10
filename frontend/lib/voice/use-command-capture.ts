"use client"

import { AudioFormat, useScribe, type UseScribeReturn } from "@elevenlabs/react"
import { useCallback, useEffect, useRef } from "react"

import { useApi } from "@/hooks/use-api"
import type { ApiClient } from "@/lib/api/client"
import {
  type Microphone,
  openMicrophone,
  PCM_SAMPLE_RATE,
} from "@/lib/voice/microphone"

/** Why a capture ended without a command. `fatal` means voice itself cannot be used. */
export type CaptureFailure = { reason: string; fatal: boolean }

export type CommandCaptureOptions = {
  /** The microphone is open: what is said from now on is heard. */
  onConnected?: () => void
  /** Everything heard so far, as it changes. */
  onPartial: (text: string) => void
  /** The whole command, once `stop` has let Scribe finish. Empty when nothing was heard. */
  onFinal: (text: string) => void
  /** The session ended in failure. `onFinal` does not follow. */
  onError: (failure: CaptureFailure) => void
}

/**
 * How long `stop` waits for Scribe to commit the last words before it settles for what
 * it has. The commit normally comes back within a few hundred milliseconds.
 */
export const COMMIT_WAIT_MS = 1500

/**
 * How long a press let go before Scribe has started waits for it, so the words the
 * microphone held can still be heard. A token and a connection take about a second.
 */
export const CONNECT_WAIT_MS = 5000

type Session = {
  committed: string[]
  partial: string
  /** The microphone, once open. Until Scribe starts, it holds what it hears. */
  mic: Microphone | null
  /** The Scribe connection exists. Before that, a close belongs to an earlier session. */
  connected: boolean
  /** Scribe has started and is being sent the audio. */
  streaming: boolean
  /** The speaker let go. */
  releasing: boolean
  /** Ends the wait for the final commit early. Only set while that wait runs. */
  settle: (() => void) | null
  /** Ends a released press's wait for Scribe to start. Only set while that wait runs. */
  wake: (() => void) | null
}

/** What the speaker has said: committed segments, then the one still forming. */
function joinTranscript(committed: string[], partial: string): string {
  return [...committed, partial]
    .map((part) => part.trim())
    .filter(Boolean)
    .join(" ")
}

/** Why the microphone could not be opened, from the browser's error. */
function micFailure(error: unknown): CaptureFailure {
  const name =
    typeof error === "object" && error !== null && "name" in error
      ? String(error.name)
      : ""
  if (name === "NotAllowedError" || name === "SecurityError")
    return { reason: "Microphone blocked", fatal: true }
  if (name === "NotFoundError" || name === "OverconstrainedError")
    return { reason: "No microphone found", fatal: true }
  // In use by another app, or no audio pipeline in this browser.
  return { reason: "Microphone unavailable", fatal: true }
}

/**
 * Asks Scribe to commit the audio it has not committed yet, then waits for the answer
 * (or `COMMIT_WAIT_MS`, or anything that makes waiting pointless). Whatever arrives
 * lands in `session` through the transcript handlers.
 */
function commitLastWords(
  session: Session,
  scribe: { current: UseScribeReturn | null }
): Promise<void> {
  return new Promise((resolve) => {
    const timer = setTimeout(settle, COMMIT_WAIT_MS)
    function settle() {
      clearTimeout(timer)
      session.settle = null
      resolve()
    }
    session.settle = settle
    try {
      scribe.current?.commit()
    } catch {
      // The socket is not open: nothing to wait for.
      settle()
    }
  })
}

/**
 * Waits for Scribe to start (true), for the session to fail, or `CONNECT_WAIT_MS`
 * (false).
 */
function scribeStarted(session: Session): Promise<boolean> {
  return new Promise((resolve) => {
    const timer = setTimeout(wake, CONNECT_WAIT_MS)
    function wake() {
      clearTimeout(timer)
      session.wake = null
      resolve(session.streaming)
    }
    session.wake = wake
  })
}

async function mintScribeToken(api: ApiClient): Promise<string> {
  const { data } = await api.POST("/api/v1/voice/scribe-token")
  // Any non-2xx (the backend answers 503 when voice is down) leaves `data` empty.
  if (!data) throw new Error("Could not get a Scribe token")
  return data.token
}

/**
 * Push-to-talk speech capture on ElevenLabs Scribe realtime.
 *
 * `start` opens the microphone and, at the same time, mints a fresh single-use token
 * and connects. The microphone hears from the press on and holds what it hears until
 * Scribe has started, so the first words are not lost to the connection. `stop` lets
 * the microphone hear the last syllable, asks Scribe to commit what is still in
 * flight (the session never commits on its own, so the last words would otherwise be
 * lost), waits briefly for it, ends the session and reports everything heard
 * (committed segments plus any forming one) to `onFinal`. A session that ends in
 * failure reports to `onError` exactly once and never to `onFinal`.
 */
export function useCommandCapture({
  onConnected,
  onPartial,
  onFinal,
  onError,
}: CommandCaptureOptions) {
  const api = useApi()
  const session = useRef<Session | null>(null)
  const scribeRef = useRef<UseScribeReturn | null>(null)
  const latest = useRef({ onConnected, onPartial, onFinal, onError })

  useEffect(() => {
    latest.current = { onConnected, onPartial, onFinal, onError }
  })

  // The first failure ends the session; the echoes that follow it are ignored.
  const fail = useCallback(
    (failure: CaptureFailure, of: Session | null = session.current) => {
      if (!of || session.current !== of) return
      session.current = null
      of.mic?.close()
      // A `stop` still waiting has nothing left to wait for.
      of.settle?.()
      of.wake?.()
      scribeRef.current?.disconnect()
      latest.current.onError(failure)
    },
    []
  )

  const scribe = useScribe({
    modelId: "scribe_v2_realtime",
    onSessionStarted: () => {
      const current = session.current
      if (!current?.mic || current.streaming) return
      current.streaming = true
      // What was said while connecting goes first, then the rest as it is heard.
      current.mic.pipe((chunk) => {
        try {
          scribeRef.current?.sendAudio(chunk)
        } catch {
          // The socket has closed under the session, which is ending with it.
        }
      })
      current.wake?.()
    },
    onPartialTranscript: ({ text }) => {
      const current = session.current
      if (!current) return
      current.partial = text
      latest.current.onPartial(joinTranscript(current.committed, text))
    },
    onCommittedTranscript: ({ text }) => {
      const current = session.current
      if (!current) return
      // An empty commit has nothing to replace the words still forming.
      if (text.trim()) {
        current.committed.push(text)
        current.partial = ""
      }
      latest.current.onPartial(
        joinTranscript(current.committed, current.partial)
      )
      current.settle?.()
    },
    onError: () => {
      // While the final commit is awaited, a hiccup (such as a commit with too little
      // audio behind it) must not throw away the words already heard.
      const settle = session.current?.settle
      if (settle) return settle()
      fail({ reason: "Voice connection failed", fatal: false })
    },
    onAuthError: () => fail({ reason: "Voice sign-in failed", fatal: true }),
    onQuotaExceededError: () =>
      fail({ reason: "Voice usage limit reached", fatal: true }),
    onUnacceptedTermsError: () =>
      fail({ reason: "Voice terms not accepted", fatal: true }),
    onDisconnect: () => {
      const current = session.current
      if (!current?.connected) return
      if (current.settle) return current.settle()
      fail({ reason: "Voice connection closed", fatal: false })
    },
  })

  useEffect(() => {
    scribeRef.current = scribe
  })

  // The microphone is this hook's, not Scribe's: let it go if the dock goes away.
  useEffect(
    () => () => {
      const current = session.current
      session.current = null
      current?.mic?.close()
      current?.settle?.()
      current?.wake?.()
    },
    []
  )

  const start = useCallback(async () => {
    if (session.current) return
    const current: Session = {
      committed: [],
      partial: "",
      mic: null,
      connected: false,
      streaming: false,
      releasing: false,
      settle: null,
      wake: null,
    }
    session.current = current

    // Both at once: the token and the connection take long enough to lose the first
    // words if the microphone waited for them.
    const token = mintScribeToken(api).catch(() => null)
    let mic: Microphone
    try {
      mic = await openMicrophone()
    } catch (error) {
      fail(micFailure(error), current)
      return
    }
    // Let go (or failed) while the microphone was opening.
    if (session.current !== current) return mic.close()
    current.mic = mic
    latest.current.onConnected?.()

    const value = await token
    if (session.current !== current) return
    if (!value)
      return fail({ reason: "Voice is unavailable", fatal: true }, current)

    try {
      await scribeRef.current?.connect({
        token: value,
        audioFormat: AudioFormat.PCM_16000,
        sampleRate: PCM_SAMPLE_RATE,
      })
      current.connected = true
    } catch {
      fail({ reason: "Voice connection failed", fatal: true }, current)
    }
  }, [api, fail])

  const stop = useCallback(async () => {
    const current = session.current
    if (!current || current.releasing) return
    current.releasing = true

    // A press let go before the microphone opened heard nothing.
    if (current.mic) {
      await current.mic.stop()
      if (session.current !== current) return
      if (!current.streaming) {
        const started = await scribeStarted(current)
        if (session.current !== current) return
        // What the microphone held can no longer be heard.
        if (!started)
          return fail({ reason: "Voice connection failed", fatal: false })
      }
      await commitLastWords(current, scribeRef)
      // A failure while waiting has already reported itself and ended the session.
      if (session.current !== current) return
    }

    session.current = null
    current.mic?.close()
    scribeRef.current?.disconnect()
    latest.current.onFinal(joinTranscript(current.committed, current.partial))
  }, [fail])

  return { start, stop, status: scribe.status }
}
