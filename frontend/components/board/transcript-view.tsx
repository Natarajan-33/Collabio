"use client"

import * as React from "react"

import type { components } from "@/lib/api/schema"

type TranscriptView = components["schemas"]["TranscriptView"]

function formatTurnTime(seconds: number): string {
  const m = Math.floor(seconds / 60)
  const s = Math.floor(seconds % 60)
  return `${m}:${s.toString().padStart(2, "0")}`
}

function roleLabel(role: "agent" | "user"): string {
  return role === "agent" ? "Agent" : "Creator"
}

/** An email reply as it arrived, behind a toggle: what we read is shown above it. */
function FullEmail({ text }: { text: string }) {
  const [shown, setShown] = React.useState(false)
  const id = React.useId()
  return (
    <div className="space-y-1">
      <button
        type="button"
        className="text-xs text-muted-foreground underline underline-offset-2 hover:text-foreground"
        aria-expanded={shown}
        aria-controls={id}
        onClick={() => setShown((v) => !v)}
      >
        {shown ? "Hide full email" : "Show full email"}
      </button>
      {shown ? (
        <p
          id={id}
          className="rounded-md border bg-muted/30 p-2 text-xs whitespace-pre-wrap text-muted-foreground"
        >
          {text}
        </p>
      ) : null}
    </div>
  )
}

export function TranscriptView({ transcript }: { transcript: TranscriptView }) {
  if (transcript.kind === "email_out" || transcript.kind === "email_in") {
    const raw = transcript.kind === "email_in" ? transcript.raw_text : null
    // Worth a toggle only when there is more than what we read.
    const hasMore = !!raw && raw.trim() !== (transcript.body_text ?? "").trim()
    return (
      <div className="space-y-2 text-sm">
        {transcript.subject ? (
          <p className="font-medium">{transcript.subject}</p>
        ) : null}
        <p className="whitespace-pre-wrap text-muted-foreground">
          {transcript.body_text}
        </p>
        {hasMore && raw ? <FullEmail text={raw} /> : null}
      </div>
    )
  }

  if (transcript.kind === "call") {
    return (
      <ul className="space-y-1 text-sm">
        {transcript.turns.map((turn, i) => (
          <li key={i}>
            <span className="font-medium">{roleLabel(turn.role)}</span>
            <span className="text-muted-foreground">
              {" "}
              [{formatTurnTime(turn.t)}]
            </span>{" "}
            {turn.text}
          </li>
        ))}
        {transcript.summary ? (
          <p className="mt-2 text-xs text-muted-foreground">
            {transcript.summary}
          </p>
        ) : null}
      </ul>
    )
  }

  return (
    <p className="text-sm text-muted-foreground">
      {transcript.summary ?? transcript.body_text ?? "—"}
    </p>
  )
}
