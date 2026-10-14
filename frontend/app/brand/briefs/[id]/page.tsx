"use client"

import { ArrowLeft, TriangleAlert } from "lucide-react"
import Link from "next/link"
import { useParams, useRouter } from "next/navigation"
import * as React from "react"
import { toast } from "sonner"

import { AgentSession } from "@/components/brief/agent-session"
import { BriefCard } from "@/components/brief/brief-card"
import { CreatorsPanel } from "@/components/brief/creators-panel"
import { LaunchBar } from "@/components/brief/launch-bar"
import { Button, buttonVariants } from "@/components/ui/button"
import { Stepper } from "@/components/ui/stepper"
import {
  useVoiceScreen,
  type VoiceIntent,
} from "@/components/voice/voice-screen"
import { useApi } from "@/hooks/use-api"
import type { components } from "@/lib/api/schema"
import {
  changedFields,
  invalidFieldMessage,
  type BriefFieldKey,
} from "@/lib/brief/state"
import { cn } from "@/lib/utils"

type DealBrief = components["schemas"]["DealBrief"]
type BriefPatch = components["schemas"]["BriefPatch"]
type Preview = components["schemas"]["BriefCreatorPreview"]
type ChannelPlan = Preview["default_channel"]
type Policy = components["schemas"]["LaunchRequest"]["follow_up_policy"]

type Phase = "loading" | "ready" | "failed"

const NO_CHANGES: ReadonlySet<BriefFieldKey> = new Set()
/** How long a creator the agent named stays outlined. */
const HIGHLIGHT_MS = 5000
const REVIEW_PATH = "/brand/discover/review"

function boardPath(batchId: string): string {
  return `/brand/batches/${batchId}`
}

export default function BriefPage() {
  const { id } = useParams<{ id: string }>()
  const api = useApi()
  const router = useRouter()

  const [phase, setPhase] = React.useState<Phase>("loading")
  const [brief, setBrief] = React.useState<DealBrief | null>(null)
  // The latest brief, for the next save to compare against.
  const briefRef = React.useRef<DealBrief | null>(null)
  const [creators, setCreators] = React.useState<Preview[]>([])
  const [channels, setChannels] = React.useState<Record<string, ChannelPlan>>(
    {}
  )
  const [changed, setChanged] =
    React.useState<ReadonlySet<BriefFieldKey>>(NO_CHANGES)
  // The fields the brand changed by hand: the agent is told about these, not about its own.
  const [edited, setEdited] =
    React.useState<ReadonlySet<BriefFieldKey>>(NO_CHANGES)
  // The creator the agent just named, and whether it has said the brief is complete.
  const [highlighted, setHighlighted] = React.useState<string | null>(null)
  const [ready, setReady] = React.useState(false)
  const [policy, setPolicy] = React.useState<Policy>("suggest")
  const [launching, setLaunching] = React.useState(false)
  // Set at once, unlike state, so a double click cannot launch twice.
  const launchingRef = React.useRef(false)
  // Only the newest preview request is shown: an older reply can arrive later.
  const previewRequest = React.useRef(0)

  const path = React.useMemo(
    () => ({ params: { path: { brief_id: id } } }),
    [id]
  )

  const commit = React.useCallback((next: DealBrief) => {
    briefRef.current = next
    setBrief(next)
  }, [])

  const refreshPreview = React.useCallback(async () => {
    const request = ++previewRequest.current
    try {
      const { data } = await api.GET("/api/v1/briefs/{brief_id}/preview", path)
      if (!data || request !== previewRequest.current) return
      setCreators(data.creators)
      // Keep what the brand chose; a creator seen for the first time gets the default.
      setChannels((current) =>
        Object.fromEntries(
          data.creators.map((c) => [
            c.creator_id,
            current[c.creator_id] ?? c.default_channel,
          ])
        )
      )
    } catch {
      // The last preview stays up; the next edit asks again.
    }
  }, [api, path])

  const refreshBrief = React.useCallback(async () => {
    try {
      const { data } = await api.GET("/api/v1/briefs/{brief_id}", path)
      if (data) commit(data)
    } catch {
      // Nothing to show beyond what is already on screen.
    }
  }, [api, path, commit])

  // Loads the brief once on arrival, and again on "Try again" (the state starts as
  // "loading"). A reply that lands after the page has gone is dropped.
  const [attempt, setAttempt] = React.useState(0)
  React.useEffect(() => {
    let gone = false
    async function load() {
      let outcome: Phase = "failed"
      try {
        const [loaded] = await Promise.all([
          api.GET("/api/v1/briefs/{brief_id}", path),
          refreshPreview(),
        ])
        if (gone) return
        if (loaded.data) {
          commit(loaded.data)
          outcome = "ready"
        }
      } catch {
        // Shown as the failure below.
      }
      if (!gone) setPhase(outcome)
    }
    void load()
    return () => {
      gone = true
    }
  }, [api, path, commit, refreshPreview, attempt])

  // A brief that was launched has a board; that is where it belongs.
  const batchId = brief?.batch_id ?? null
  React.useEffect(() => {
    if (batchId) router.replace(boardPath(batchId))
  }, [batchId, router])

  // The ring around a named creator fades after a few seconds.
  React.useEffect(() => {
    if (!highlighted) return
    const timer = setTimeout(() => setHighlighted(null), HIGHLIGHT_MS)
    return () => clearTimeout(timer)
  }, [highlighted])

  // A brief saved from outside the card (the agent): mark what changed and re-compare.
  const applySaved = React.useCallback(
    (saved: DealBrief) => {
      setChanged(changedFields(briefRef.current, saved))
      commit(saved)
      setReady(false)
      void refreshPreview()
    },
    [commit, refreshPreview]
  )

  const edit = React.useCallback(
    async (_key: BriefFieldKey, patch: BriefPatch): Promise<string | null> => {
      let reply
      try {
        reply = await api.PATCH("/api/v1/briefs/{brief_id}", {
          ...path,
          body: patch,
        })
      } catch {
        return "Couldn't save. Try again."
      }

      if (reply.data) {
        setEdited(changedFields(briefRef.current, reply.data))
        applySaved(reply.data)
        return null
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
          // Launched from another tab: the refreshed brief sends us to its board.
          void refreshBrief()
          return "This brief was already launched."
        default:
          return "Couldn't save. Try again."
      }
    },
    [api, path, applySaved, refreshBrief]
  )

  // How many creators the brand wants to hire. Saved at once, like any other field.
  const [savingHires, setSavingHires] = React.useState(false)
  const hiresLabelId = React.useId()
  async function setHiresTarget(next: number | null) {
    if (next === null) return
    setSavingHires(true)
    try {
      const reply = await api.PATCH("/api/v1/briefs/{brief_id}", {
        ...path,
        body: { hires_target: next },
      })
      if (reply.data) {
        commit(reply.data)
      } else {
        if (reply.response.status === 409) void refreshBrief()
        toast.error("Couldn't save how many creators to hire")
      }
    } catch {
      toast.error("Couldn't save how many creators to hire")
    } finally {
      setSavingHires(false)
    }
  }

  // Who the launch reaches: everyone who has not opted out of contact.
  const reachable = creators.filter((c) => c.excluded_reason === null)

  async function launch() {
    if (launchingRef.current || reachable.length === 0) return
    launchingRef.current = true
    setLaunching(true)

    let launched: components["schemas"]["LaunchResponse"] | undefined
    let status = 0
    try {
      const reply = await api.POST("/api/v1/briefs/{brief_id}/launch", {
        ...path,
        body: {
          channels: Object.fromEntries(
            reachable.map((c) => [
              c.creator_id,
              channels[c.creator_id] ?? c.default_channel,
            ])
          ),
          follow_up_policy: policy,
        },
      })
      launched = reply.data
      status = reply.response.status
    } catch {
      // Handled with the missing reply below.
    }

    if (launched) {
      // Stay "launching" while the board loads: there is nothing more to launch.
      router.push(boardPath(launched.batch_id))
      return
    }
    if (status === 409) {
      // Already launched elsewhere; the refreshed brief carries its batch.
      await refreshBrief()
    } else if (status === 422) {
      toast.error("The brief changed. Check what is still needed.")
      await Promise.all([refreshBrief(), refreshPreview()])
    } else {
      toast.error("Couldn't launch the brief")
    }
    launchingRef.current = false
    setLaunching(false)
  }

  useVoiceScreen(
    "brief",
    () => ({
      visible_creators: creators.map((c) => ({
        id: c.creator_id,
        name: c.name,
        handle: c.handle,
      })),
    }),
    (spoken: VoiceIntent) => {
      // The brief agent handles the brief itself; the router only moves around.
      if (spoken.kind === "navigate" && spoken.navigate) {
        router.push(spoken.navigate)
      }
    }
  )

  if (phase === "loading") {
    return (
      <div
        role="status"
        className="rounded-2xl border bg-muted/40 p-8 text-sm text-muted-foreground"
      >
        Loading your brief…
      </div>
    )
  }

  if (phase === "failed" || !brief) {
    return (
      <div
        role="alert"
        className="flex flex-col items-start gap-3 rounded-2xl border border-destructive/30 bg-card p-8"
      >
        <TriangleAlert aria-hidden className="size-5 text-destructive" />
        <h1 className="font-display text-3xl">Couldn&apos;t load this brief</h1>
        <p className="max-w-prose text-sm text-muted-foreground">
          It may have been removed, or the connection dropped. Try again in a
          moment.
        </p>
        <div className="flex gap-2">
          <Button
            variant="outline"
            onClick={() => {
              setPhase("loading")
              setAttempt((n) => n + 1)
            }}
          >
            Try again
          </Button>
          <Link
            href={REVIEW_PATH}
            className={cn(buttonVariants({ variant: "ghost" }))}
          >
            Back to comparison
          </Link>
        </div>
      </div>
    )
  }

  if (brief.batch_id) {
    return (
      <div
        role="status"
        className="rounded-2xl border bg-muted/40 p-8 text-sm text-muted-foreground"
      >
        Opening your board…
      </div>
    )
  }

  return (
    <div className="flex flex-col gap-6">
      <header className="flex flex-col gap-3 pt-2">
        <Link
          href={REVIEW_PATH}
          className={cn(
            buttonVariants({ variant: "outline", size: "sm" }),
            "w-fit"
          )}
        >
          <ArrowLeft aria-hidden />
          Back to comparison
        </Link>
        <h1 className="font-display text-4xl leading-[1.05] tracking-tight sm:text-5xl">
          Your brief
        </h1>
        <p className="text-sm text-muted-foreground">
          Fill in what the creators will be asked. Anything outlined is still
          needed before you can launch.
        </p>
      </header>

      <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.2fr)]">
        <div className="flex flex-col gap-4">
          <AgentSession
            briefId={id}
            brief={brief}
            preview={creators}
            edited={edited}
            onSaved={applySaved}
            onHighlight={setHighlighted}
            onReady={() => setReady(true)}
          />
          <BriefCard brief={brief} changed={changed} onEdit={edit} />
        </div>

        <div className="flex flex-col gap-4">
          <CreatorsPanel
            creators={creators}
            highlighted={highlighted}
            channels={channels}
            onChannel={(creatorId, plan) =>
              setChannels((current) => ({ ...current, [creatorId]: plan }))
            }
          />
          <fieldset
            disabled={savingHires}
            className="m-0 flex min-w-0 items-center justify-between gap-4 rounded-2xl border bg-card p-4"
          >
            <div className="flex flex-col">
              <p id={hiresLabelId} className="text-sm font-medium">
                Creators to hire
              </p>
              <p className="text-xs text-muted-foreground">
                The board tells you when you have hired enough.
              </p>
            </div>
            <Stepper
              labelledBy={hiresLabelId}
              noun="creators to hire"
              min={1}
              max={10}
              value={brief.hires_target}
              onValueChange={(next) => void setHiresTarget(next)}
            />
          </fieldset>
          <LaunchBar
            count={reachable.length}
            missing={brief.missing}
            violations={brief.violations}
            policy={policy}
            onPolicy={setPolicy}
            onLaunch={() => void launch()}
            launching={launching}
            pulse={ready}
          />
        </div>
      </div>
    </div>
  )
}
