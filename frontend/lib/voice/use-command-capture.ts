"use client"

import { useScribe, type UseScribeReturn } from "@elevenlabs/react"
import { useCallback, useEffect, useRef } from "react"

import { useApi } from "@/hooks/use-api"
import type { ApiClient } from "@/lib/api/client"

/** Why a capture ended without a command. `fatal` means voice itself cannot be used. */
export type CaptureFailure = { reason: string; fatal: boolean }

export type CommandCaptureOptions = {
  /** The listening session is live (the Scribe socket has started). */
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

type Session = {
  committed: string[]
  partial: string
  /** The Scribe connection exists. Before that, a close belongs to an earlier session. */
  connected: boolean
  /** The speaker let go and `stop` is waiting for the final commit. */
  releasing: boolean
  /** Ends that wait early. Only set while `releasing`. */
  settle: (() => void) | null
}

const MIC_BLOCKED = /permission|denied|not.?allowed|getusermedia|mediadevices/i
const MIC_MISSING = /not.?found|no (?:audio|microphone|device)/i

/** What the speaker has said: committed segments, then the one still forming. */
function joinTranscript(committed: string[], partial: string): string {
  return [...committed, partial]
    .map((part) => part.trim())
    .filter(Boolean)
    .join(" ")
}

function classify(error: Error | Event): CaptureFailure {
  const message = error instanceof Error ? error.message : ""
  if (MIC_BLOCKED.test(message))
    return { reason: "Microphone blocked", fatal: true }
  if (MIC_MISSING.test(message))
    return { reason: "No microphone found", fatal: true }
  return { reason: "Voice connection failed", fatal: false }
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
      // The socket is not open (a press too short to reach Scribe): nothing to wait for.
      settle()
    }
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
 * `start` mints a fresh single-use token and opens the microphone. `stop` asks Scribe
 * to commit what is still in flight (the session never commits on its own, so the
 * last words would otherwise be lost), waits briefly for it, ends the session and
 * reports everything heard (committed segments plus any forming one) to `onFinal`.
 * A session that ends in failure reports to `onError` exactly once and never to
 * `onFinal`.
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

  // The first failure ends the session; the echoes Scribe emits after it are ignored.
  const fail = useCallback((failure: CaptureFailure) => {
    const current = session.current
    if (!current) return
    session.current = null
    // A `stop` still waiting for the commit has nothing left to wait for.
    current.settle?.()
    scribeRef.current?.disconnect()
    latest.current.onError(failure)
  }, [])

  const scribe = useScribe({
    modelId: "scribe_v2_realtime",
    onSessionStarted: () => {
      if (session.current) latest.current.onConnected?.()
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
    onError: (error) => {
      // Once the speaker has let go, a hiccup (such as a commit with too little audio
      // behind it) must not throw away the words already heard.
      const releasing = session.current?.settle
      if (releasing) return releasing()
      fail(classify(error))
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

  const start = useCallback(async () => {
    if (session.current) return
    const current: Session = {
      committed: [],
      partial: "",
      connected: false,
      releasing: false,
      settle: null,
    }
    session.current = current

    let token: string
    try {
      token = await mintScribeToken(api)
    } catch {
      fail({ reason: "Voice is unavailable", fatal: true })
      return
    }
    // Released (or failed) while the token was on its way.
    if (session.current !== current) return

    try {
      await scribeRef.current?.connect({
        token,
        microphone: { echoCancellation: true, noiseSuppression: true },
      })
      current.connected = true
    } catch {
      if (session.current === current)
        fail({ reason: "Voice connection failed", fatal: true })
    }
  }, [api, fail])

  const stop = useCallback(async () => {
    const current = session.current
    if (!current || current.releasing) return
    current.releasing = true

    if (current.connected) await commitLastWords(current, scribeRef)
    // A failure while waiting has already reported itself and ended the session.
    if (session.current !== current) return

    session.current = null
    scribeRef.current?.disconnect()
    latest.current.onFinal(joinTranscript(current.committed, current.partial))
  }, [])

  return { start, stop, status: scribe.status }
}
