"use client"

import {
  ConversationProvider,
  useConversation,
  useConversationClientTool,
} from "@elevenlabs/react"
import { Mic, Square } from "lucide-react"
import { useReducedMotion } from "motion/react"
import dynamic from "next/dynamic"
import * as React from "react"
import { toast } from "sonner"

import { Button } from "@/components/ui/button"
import type { AgentState } from "@/components/ui/orb"
import { useVoicePause } from "@/components/voice/voice-screen"
import { useApi } from "@/hooks/use-api"
import type { components } from "@/lib/api/schema"
import {
  agentFieldToPatch,
  contextualUpdate,
  matchCreator,
} from "@/lib/brief/agent-tools"
import {
  invalidFieldMessage,
  missingLabels,
  type BriefFieldKey,
} from "@/lib/brief/state"
import { cn } from "@/lib/utils"

type DealBrief = components["schemas"]["DealBrief"]
type Preview = components["schemas"]["BriefCreatorPreview"]

// three.js is heavy and only draws during a conversation: load it on demand, and never
// on the server.
const Orb = dynamic(() => import("@/components/ui/orb").then((m) => m.Orb), {
  ssr: false,
})

/** The `--voice` ember as the Orb's [darker, lighter] ramp. It takes hex, not oklch. */
const ORB_COLORS: [string, string] = ["#f6623d", "#ffaf76"]

/** Why the Voice Dock is quiet while the conversation is open (one microphone). */
const DOCK_PAUSED = "Voice is in the brief conversation"

const SAVE_FAILED = "Couldn't save that. Ask the brand to edit the card."

type AgentSessionProps = {
  briefId: string
  brief: DealBrief
  preview: readonly Preview[]
  /** The fields the brand just changed on the card. Pass a new set per edit. */
  edited: ReadonlySet<BriefFieldKey>
  /** The agent saved a field: the brief as the API now has it. */
  onSaved: (brief: DealBrief) => void
  /** The agent named a creator. */
  onHighlight: (creatorId: string) => void
  /** The agent says the brief is complete. */
  onReady: () => void
}

/** Whether a failure to start was the browser refusing the microphone. */
function isMicrophoneBlocked(message: string, context: unknown): boolean {
  const name =
    typeof context === "object" && context !== null
      ? (context as { name?: unknown }).name
      : undefined
  return (
    name === "NotAllowedError" ||
    name === "SecurityError" ||
    /permission|not allowed|denied/i.test(message)
  )
}

/**
 * The conversation with the brief agent: an orb, what it is doing, live captions, and
 * the tools the agent uses to fill the card. The card stays editable throughout.
 */
export function AgentSession(props: AgentSessionProps) {
  return (
    <ConversationProvider>
      <SessionPanel {...props} />
    </ConversationProvider>
  )
}

function SessionPanel({
  briefId,
  brief,
  preview,
  edited,
  onSaved,
  onHighlight,
  onReady,
}: AgentSessionProps) {
  const api = useApi()
  const reducedMotion = useReducedMotion()
  const { status, isSpeaking, startSession, endSession, sendContextualUpdate } =
    useConversation()

  const [starting, setStarting] = React.useState(false)
  const [ended, setEnded] = React.useState(false)
  const [agentLine, setAgentLine] = React.useState("")
  const [userLine, setUserLine] = React.useState("")

  const path = React.useMemo(
    () => ({ params: { path: { brief_id: briefId } } }),
    [briefId]
  )

  // The tools and the card-edit note read the latest props without re-registering.
  const latest = React.useRef({ brief, preview, status, onSaved, onHighlight })
  const mounted = React.useRef(false)
  // End was pressed while the session was still being minted.
  const abandoned = React.useRef(false)
  React.useEffect(() => {
    latest.current = { brief, preview, status, onSaved, onHighlight }
  })
  React.useEffect(() => {
    mounted.current = true
    return () => {
      mounted.current = false
    }
  }, [])

  const connected = status === "connected"
  const connecting = !connected && (starting || status === "connecting")
  const live = connecting || connected

  // One microphone: the Voice Dock waits while the conversation is open.
  useVoicePause(status === "connecting" || connected ? DOCK_PAUSED : null)

  useConversationClientTool(
    "update_brief",
    async (params: Record<string, unknown>) => {
      const parsed = agentFieldToPatch(
        String(params.field ?? ""),
        String(params.value ?? "")
      )
      if ("error" in parsed) return parsed.error

      let reply
      try {
        reply = await api.PATCH("/api/v1/briefs/{brief_id}", {
          ...path,
          body: parsed.patch,
        })
      } catch {
        return SAVE_FAILED
      }

      if (reply.data) {
        latest.current.onSaved(reply.data)
        const missing = missingLabels(reply.data.missing)
        return missing.length > 0
          ? `Saved. Still missing: ${missing.join(", ")}`
          : "Saved. Nothing is missing."
      }
      switch (reply.response.status) {
        case 422: {
          const detail = (reply.error as { detail?: unknown } | undefined)
            ?.detail
          return (
            invalidFieldMessage(detail)?.message ?? "That value isn't allowed."
          )
        }
        case 409:
          return "This brief was already launched."
        default:
          return SAVE_FAILED
      }
    }
  )

  useConversationClientTool(
    "show_creator",
    (params: Record<string, unknown>) => {
      const id = matchCreator(
        String(params.creator_ref ?? ""),
        latest.current.preview.map((c) => ({
          creator_id: c.creator_id,
          name: c.name,
          handle: c.handle,
        }))
      )
      if (!id) return "No creator by that name in this brief."
      latest.current.onHighlight(id)
      return "Shown."
    }
  )

  useConversationClientTool("ready_to_launch", () => {
    const current = latest.current.brief
    const missing = missingLabels(current.missing)
    if (missing.length > 0) return `Still missing: ${missing.join(", ")}`
    if (current.violations.length > 0) {
      return `Not ready: ${current.violations.map((v) => v.message).join(" ")}`
    }
    onReady()
    return "ready"
  })

  // Tell the agent what the brand changed on the card while the call is open. Edits
  // made before the call are in the brief it was given at the start.
  const told = React.useRef(edited)
  React.useEffect(() => {
    if (told.current === edited) return
    told.current = edited
    if (latest.current.status !== "connected") return
    for (const key of edited) {
      sendContextualUpdate(contextualUpdate(key, latest.current.brief))
    }
  }, [edited, sendContextualUpdate])

  async function begin() {
    if (live) return
    abandoned.current = false
    setStarting(true)
    setEnded(false)
    setAgentLine("")
    setUserLine("")

    let session: components["schemas"]["VoiceSessionResponse"] | undefined
    try {
      const reply = await api.POST(
        "/api/v1/briefs/{brief_id}/voice-session",
        path
      )
      session = reply.data
    } catch {
      // Handled with the missing session below.
    }
    if (!mounted.current || abandoned.current) return
    if (!session) {
      setStarting(false)
      toast.error("Couldn't start the conversation — edit the card instead")
      return
    }

    startSession({
      conversationToken: session.conversation_token,
      connectionType: "webrtc",
      dynamicVariables: session.dynamic_variables,
      onConnect: ({ conversationId }) => {
        setStarting(false)
        // Kept so the transcript can be found later; the card does not change.
        void Promise.resolve(
          api.PATCH("/api/v1/briefs/{brief_id}", {
            ...path,
            body: { intake_conversation_id: conversationId },
          })
        ).catch(() => {})
      },
      onDisconnect: () => {
        setStarting(false)
        setEnded(true)
      },
      onMessage: ({ message, role }) => {
        if (role === "agent") setAgentLine(message)
        else setUserLine(message)
      },
      onError: (message, context) => {
        setStarting(false)
        toast.error(
          isMicrophoneBlocked(message, context)
            ? "Microphone blocked — edit the card instead"
            : "The conversation hit a problem — edit the card instead"
        )
      },
    })
  }

  const orbState: AgentState = connecting
    ? "thinking"
    : isSpeaking
      ? "talking"
      : "listening"

  const statusText = connecting
    ? "Connecting…"
    : connected
      ? isSpeaking
        ? "Speaking"
        : "Listening"
      : ended
        ? "Ended"
        : "Talk the brief through, or edit the card."

  return (
    <section
      data-slot="agent-session"
      data-live={live ? "true" : undefined}
      aria-label="Brief conversation"
      className="flex flex-col gap-3 rounded-2xl border bg-card p-4"
    >
      <div className="flex items-center gap-4">
        <div aria-hidden className="relative size-14 shrink-0">
          <span
            className={cn(
              "absolute inset-1 rounded-full bg-[radial-gradient(circle_at_35%_30%,#ffaf76,var(--voice)_55%,color-mix(in_oklch,var(--voice),black_35%))]",
              !live && "opacity-40"
            )}
          />
          {live && !reducedMotion ? (
            <Orb
              colors={ORB_COLORS}
              agentState={orbState}
              className="pointer-events-none absolute inset-0"
            />
          ) : null}
        </div>

        <p
          className={cn(
            "min-w-0 flex-1 text-sm",
            live ? "font-medium" : "text-muted-foreground"
          )}
        >
          {statusText}
        </p>

        {connected || connecting ? (
          <Button
            type="button"
            variant="outline"
            onClick={() => {
              abandoned.current = true
              endSession()
              setStarting(false)
            }}
          >
            <Square aria-hidden />
            End conversation
          </Button>
        ) : (
          <Button
            type="button"
            disabled={starting}
            onClick={() => void begin()}
          >
            <Mic aria-hidden />
            {ended ? "Resume" : "Talk it through"}
          </Button>
        )}
      </div>

      <div
        role="log"
        aria-label="Captions"
        aria-live="polite"
        className="flex flex-col gap-1.5 text-sm empty:hidden"
      >
        {agentLine ? (
          <p className="flex gap-2">
            <span className="w-10 shrink-0 text-xs tracking-wide text-muted-foreground uppercase">
              Agent
            </span>
            <span>{agentLine}</span>
          </p>
        ) : null}
        {userLine ? (
          <p className="flex gap-2">
            <span className="w-10 shrink-0 text-xs tracking-wide text-muted-foreground uppercase">
              You
            </span>
            <span className="text-muted-foreground">{userLine}</span>
          </p>
        ) : null}
      </div>
    </section>
  )
}
