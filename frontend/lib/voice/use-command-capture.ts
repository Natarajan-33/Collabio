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
  /** The whole command, once `stop` is called. Empty when nothing was heard. */
  onFinal: (text: string) => void
  /** The session ended in failure. `onFinal` does not follow. */
  onError: (failure: CaptureFailure) => void
}

type Session = {
  committed: string[]
  partial: string
  /** The Scribe connection exists. Before that, a close belongs to an earlier session. */
  connected: boolean
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

async function mintScribeToken(api: ApiClient): Promise<string> {
  const { data } = await api.POST("/api/v1/voice/scribe-token")
  // Any non-2xx (the backend answers 503 when voice is down) leaves `data` empty.
  if (!data) throw new Error("Could not get a Scribe token")
  return data.token
}

/**
 * Push-to-talk speech capture on ElevenLabs Scribe realtime.
 *
 * `start` mints a fresh single-use token and opens the microphone; `stop` ends the
 * session and reports everything heard (committed segments plus the one still
 * forming) to `onFinal`. A session that ends in failure reports to `onError`
 * exactly once and never to `onFinal`.
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
    if (!session.current) return
    session.current = null
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
      current.committed.push(text)
      current.partial = ""
      latest.current.onPartial(joinTranscript(current.committed, ""))
    },
    onError: (error) => fail(classify(error)),
    onAuthError: () => fail({ reason: "Voice sign-in failed", fatal: true }),
    onQuotaExceededError: () =>
      fail({ reason: "Voice usage limit reached", fatal: true }),
    onUnacceptedTermsError: () =>
      fail({ reason: "Voice terms not accepted", fatal: true }),
    onDisconnect: () => {
      if (session.current?.connected)
        fail({ reason: "Voice connection closed", fatal: false })
    },
  })

  useEffect(() => {
    scribeRef.current = scribe
  })

  const start = useCallback(async () => {
    if (session.current) return
    const current: Session = { committed: [], partial: "", connected: false }
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

  const stop = useCallback(() => {
    const current = session.current
    if (!current) return
    session.current = null
    scribeRef.current?.disconnect()
    latest.current.onFinal(joinTranscript(current.committed, current.partial))
  }, [])

  return { start, stop, status: scribe.status }
}
