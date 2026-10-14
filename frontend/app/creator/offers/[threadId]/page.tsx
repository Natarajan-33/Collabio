"use client"

import { ArrowLeft } from "lucide-react"
import Link from "next/link"
import { useParams } from "next/navigation"
import * as React from "react"

import { StatusPill } from "@/components/board/status-pill"
import { Timeline } from "@/components/board/timeline"
import { TranscriptView } from "@/components/board/transcript-view"
import { CompareColumns } from "@/components/deal/compare-columns"
import { ExpiryBadge } from "@/components/deal/expiry-badge"
import {
  OfferActions,
  type OfferDialog,
} from "@/components/offers/offer-actions"
import { useCreatorId } from "@/components/shell/creator-context"
import {
  useVoiceScreen,
  type VoiceIntent,
} from "@/components/voice/voice-screen"
import { useApi } from "@/hooks/use-api"
import { counterPrefill, type OfferDesk } from "@/lib/deal/offers"
import { mergeDraft, type TermsDraft } from "@/lib/deal/terms"
import { useCreatorDoorbell } from "@/lib/supabase/realtime"
import { cn } from "@/lib/utils"

/** How long the columns pulse after the terms moved under the creator. */
const FLASH_MS = 1800

export default function OfferDeskPage() {
  const { threadId } = useParams<{ threadId: string }>()
  const api = useApi()
  const creatorId = useCreatorId()

  const [desk, setDesk] = React.useState<OfferDesk | null>(null)
  const [phase, setPhase] = React.useState<"loading" | "ready" | "failed">(
    "loading"
  )
  const [now, setNow] = React.useState(() => new Date())
  const [attempt, setAttempt] = React.useState(0)
  const [flash, setFlash] = React.useState(false)
  const flashTimer = React.useRef<ReturnType<typeof setTimeout> | undefined>(
    undefined
  )

  const [dialog, setDialog] = React.useState<OfferDialog | null>(null)
  const [draft, setDraft] = React.useState<TermsDraft>({ conditions: [] })
  const [reason, setReason] = React.useState("")

  const fetchDesk = React.useCallback(async () => {
    try {
      const { data } = await api.GET("/api/v1/offers/{thread_id}", {
        params: { path: { thread_id: threadId } },
      })
      return data ?? null
    } catch {
      return null
    }
  }, [api, threadId])

  const apply = React.useCallback((next: OfferDesk | null) => {
    if (!next) return
    setDesk(next)
    setPhase("ready")
    setNow(new Date())
  }, [])

  React.useEffect(() => {
    let gone = false
    void (async () => {
      const next = await fetchDesk()
      if (gone) return
      if (next) apply(next)
      else setPhase("failed")
    })()
    return () => {
      gone = true
    }
  }, [fetchDesk, apply, attempt])

  React.useEffect(() => () => clearTimeout(flashTimer.current), [])

  const reload = React.useCallback(() => {
    void fetchDesk().then(apply)
  }, [fetchDesk, apply])

  useCreatorDoorbell(creatorId, reload)

  function onChanged({
    desk: next,
    termsChanged,
  }: {
    desk: OfferDesk | null
    termsChanged: boolean
  }) {
    if (next) apply(next)
    else reload()
    if (termsChanged) {
      setFlash(true)
      clearTimeout(flashTimer.current)
      flashTimer.current = setTimeout(() => setFlash(false), FLASH_MS)
    }
  }

  function openDialog(kind: OfferDialog) {
    if (kind === "counter" && desk) setDraft(counterPrefill(desk))
    if (kind === "decline") setReason("")
    setDialog(kind)
  }

  useVoiceScreen(
    "offer_desk",
    () => ({
      visible_creators: [],
      current_terms: dialog === "counter" ? draft : null,
    }),
    (intent: VoiceIntent) => {
      // Voice only opens the confirming UI: nothing is sent from here.
      if (!desk) return
      const allowed = desk.allowed_actions
      if (intent.kind === "counter" && allowed.includes("counter")) {
        const base = dialog === "counter" ? draft : counterPrefill(desk)
        setDraft(intent.terms ? mergeDraft(base, intent.terms) : base)
        setDialog("counter")
      } else if (intent.kind === "accept" && allowed.includes("accept")) {
        setDialog("accept")
      } else if (intent.kind === "decline" && allowed.includes("decline")) {
        setReason(intent.reason ?? "")
        setDialog("decline")
      }
    }
  )

  if (phase === "loading") {
    return (
      <div className="p-6 text-sm text-muted-foreground">Loading offer…</div>
    )
  }

  if (phase === "failed" || !desk) {
    return (
      <div className="space-y-3 p-6">
        <p className="text-sm text-destructive">Could not load this offer.</p>
        <button
          type="button"
          className="text-sm text-voice underline"
          onClick={() => {
            setPhase("loading")
            setAttempt((n) => n + 1)
          }}
        >
          Try again
        </button>
      </div>
    )
  }

  return (
    <div className="mx-auto max-w-5xl space-y-6 p-6">
      <div className="space-y-2">
        <Link
          href="/creator/offers"
          className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground"
        >
          <ArrowLeft aria-hidden className="size-3.5" />
          All offers
        </Link>
        <div className="flex flex-wrap items-center gap-3">
          <h1 className="text-2xl font-semibold tracking-tight">
            {desk.brand.name}
          </h1>
          <StatusPill status={desk.status} />
          <ExpiryBadge expiresAt={desk.expires_at} now={now} />
        </div>
        <p className="text-muted-foreground">{desk.product_name}</p>
        {desk.product_summary ? (
          <p className="text-sm text-muted-foreground">
            {desk.product_summary}
          </p>
        ) : null}
      </div>

      {desk.deal_id ? (
        <div
          data-slot="booked-banner"
          className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-emerald-500/30 bg-emerald-500/10 px-4 py-3"
        >
          <p className="text-sm font-medium">This offer is booked.</p>
          <Link
            href={`/creator/deals/${desk.deal_id}`}
            className="text-sm font-medium underline underline-offset-4"
          >
            View deal
          </Link>
        </div>
      ) : null}

      {desk.brand_note ? (
        <blockquote
          data-slot="brand-note"
          className="rounded-xl border-l-4 border-voice bg-muted/50 px-4 py-3 text-sm"
        >
          <p className="mb-1 text-xs font-medium tracking-wide text-muted-foreground uppercase">
            Note from {desk.brand.name}
          </p>
          <p className="whitespace-pre-wrap">{desk.brand_note}</p>
        </blockquote>
      ) : null}

      <div className={cn("rounded-xl", flash && "motion-safe:animate-pulse")}>
        <CompareColumns
          mine={desk.my_package}
          theirs={desk.their_ask}
          latest={desk.latest}
          changed={desk.changed}
        />
      </div>

      <OfferActions
        desk={desk}
        dialog={dialog}
        onOpenDialog={openDialog}
        onCloseDialog={() => setDialog(null)}
        draft={draft}
        onDraftChange={setDraft}
        reason={reason}
        onReasonChange={setReason}
        onChanged={onChanged}
      />

      <section className="space-y-2">
        <h2 className="text-xs font-semibold tracking-wide text-muted-foreground uppercase">
          Timeline
        </h2>
        <Timeline events={desk.events} now={now} />
      </section>

      {desk.transcripts.length > 0 ? (
        <section className="space-y-3">
          <h2 className="text-xs font-semibold tracking-wide text-muted-foreground uppercase">
            Transcripts
          </h2>
          {desk.transcripts.map((transcript) => (
            <div key={transcript.id} className="rounded-xl border p-3">
              <TranscriptView transcript={transcript} />
            </div>
          ))}
        </section>
      ) : null}
    </div>
  )
}
