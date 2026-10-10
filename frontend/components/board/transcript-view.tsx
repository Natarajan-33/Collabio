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

export function TranscriptView({ transcript }: { transcript: TranscriptView }) {
  if (transcript.kind === "email_out") {
    return (
      <div className="space-y-2 text-sm">
        {transcript.subject ? (
          <p className="font-medium">{transcript.subject}</p>
        ) : null}
        <p className="whitespace-pre-wrap text-muted-foreground">
          {transcript.body_text}
        </p>
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
            </span>
            {" "}
            {turn.text}
          </li>
        ))}
        {transcript.summary ? (
          <p className="mt-2 text-muted-foreground text-xs">
            {transcript.summary}
          </p>
        ) : null}
      </ul>
    )
  }

  return (
    <p className="text-muted-foreground text-sm">
      {transcript.summary ?? transcript.body_text ?? "—"}
    </p>
  )
}
