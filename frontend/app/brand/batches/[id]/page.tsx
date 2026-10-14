"use client"

import { useGSAP } from "@gsap/react"
import gsap from "gsap"
import { Flip } from "gsap/Flip"
import Link from "next/link"
import { useParams, useSearchParams } from "next/navigation"
import * as React from "react"
import { toast } from "sonner"

import { DeclineRestDialog } from "@/components/board/decline-rest-dialog"
import { KpiStrip } from "@/components/board/kpi-strip"
import { ThreadCardView } from "@/components/board/thread-card"
import { ThreadDrawer } from "@/components/board/thread-drawer"
import { Button } from "@/components/ui/button"
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group"
import { useApi } from "@/hooks/use-api"
import type { components } from "@/lib/api/schema"
import {
  type BoardDialog,
  type BoardSortKey,
  briefAskLine,
  counterPrefill,
  isLive,
  launchedAgo,
  sortThreads,
} from "@/lib/board/state"
import { mergeDraft, type TermsDraft } from "@/lib/deal/terms"
import { useBatchDoorbell } from "@/lib/supabase/realtime"
import {
  useVoiceScreen,
  type VoiceIntent,
} from "@/components/voice/voice-screen"

gsap.registerPlugin(useGSAP, Flip)

type BatchView = components["schemas"]["BatchView"]
type ThreadCard = components["schemas"]["ThreadCard"]

const SORT_OPTIONS: { key: BoardSortKey; label: string }[] = [
  { key: "best_value", label: "Best value" },
  { key: "price", label: "Price" },
  { key: "status", label: "Status" },
  { key: "recent", label: "Recent" },
]

type FlipState = ReturnType<typeof Flip.getState>

/**
 * Reads `?thread=<id>` (the link in the brand's notification emails). It sits in its
 * own component so the rest of the board does not wait on the query string.
 */
function ThreadLink({ onThread }: { onThread: (id: string | null) => void }) {
  const thread = useSearchParams().get("thread")
  React.useEffect(() => {
    onThread(thread)
  }, [thread, onThread])
  return null
}

export default function BatchBoardPage() {
  const { id: batchId } = useParams<{ id: string }>()
  const api = useApi()
  const [view, setView] = React.useState<BatchView | null>(null)
  const [phase, setPhase] = React.useState<"loading" | "ready" | "failed">(
    "loading"
  )
  const [sortKey, setSortKey] = React.useState<BoardSortKey>("best_value")
  const [now, setNow] = React.useState(() => new Date())
  const [emailAnimate, setEmailAnimate] = React.useState<
    Record<string, boolean>
  >({})
  const [openThreadId, setOpenThreadId] = React.useState<string | null>(null)
  const [dialog, setDialog] = React.useState<BoardDialog | null>(null)
  const [counterDraft, setCounterDraft] = React.useState<TermsDraft>({
    conditions: [],
  })
  const [declineRestOpen, setDeclineRestOpen] = React.useState(false)
  const [linkedThread, setLinkedThread] = React.useState<string | null>(null)
  const [openedLink, setOpenedLink] = React.useState<string | null>(null)
  const [refreshKey, setRefreshKey] = React.useState(0)
  const dealtIn = React.useRef(false)
  const gridRef = React.useRef<HTMLDivElement>(null)
  const flipFrom = React.useRef<FlipState | null>(null)
  const seenEmailThreads = React.useRef(new Set<string>())

  const scheduleEmailReveal = React.useCallback((data: BatchView) => {
    const pending: string[] = []
    for (const thread of data.threads) {
      if (thread.email && !seenEmailThreads.current.has(thread.id)) {
        seenEmailThreads.current.add(thread.id)
        pending.push(thread.id)
      }
    }
    if (!pending.length) return
    setEmailAnimate((prev) => {
      const next = { ...prev }
      for (const id of pending) next[id] = true
      return next
    })
    window.setTimeout(() => {
      setEmailAnimate((prev) => {
        const next = { ...prev }
        for (const id of pending) next[id] = false
        return next
      })
    }, 1300)
  }, [])

  const applyBatch = React.useCallback(
    (data: BatchView) => {
      setView(data)
      setPhase("ready")
      setNow(new Date())
      scheduleEmailReveal(data)
    },
    [scheduleEmailReveal]
  )

  const fetchBatch = React.useCallback(async () => {
    const { data, error } = await api.GET("/api/v1/batches/{batch_id}", {
      params: { path: { batch_id: batchId } },
    })
    if (error || !data) return null
    return data
  }, [api, batchId])

  const [attempt, setAttempt] = React.useState(0)
  React.useEffect(() => {
    let gone = false
    void (async () => {
      const data = await fetchBatch()
      if (gone) return
      if (!data) {
        setPhase("failed")
        return
      }
      applyBatch(data)
    })()
    return () => {
      gone = true
    }
  }, [attempt, applyBatch, fetchBatch])

  const reload = React.useCallback(async () => {
    const data = await fetchBatch()
    if (data) applyBatch(data)
  }, [applyBatch, fetchBatch])

  const threads = React.useMemo(() => {
    if (!view) return []
    return sortThreads(view.threads, sortKey)
  }, [view, sortKey])

  const live = view ? isLive(view.threads) : false

  const cardsForVoice = view?.threads ?? []

  const captureFlip = React.useCallback(() => {
    const grid = gridRef.current
    if (!grid) return
    const cards = grid.querySelectorAll("[data-flip-id]")
    if (cards.length) flipFrom.current = Flip.getState(cards)
  }, [])

  const openCard = cardsForVoice.find((c) => c.id === openThreadId) ?? null

  /** Opens a thread's drawer (or closes it), with no dialog on top. */
  const openThread = React.useCallback((id: string | null) => {
    setOpenThreadId(id)
    setDialog(null)
  }, [])

  const openDialog = (kind: BoardDialog, card: ThreadCard) => {
    if (kind === "counter" && view) {
      setCounterDraft(counterPrefill(card, view.brief))
    }
    setDialog(kind)
  }

  // The thread a notification email linked to opens once the board has loaded; a link
  // to a thread that is not on this board is ignored.
  if (view && linkedThread && openedLink !== linkedThread) {
    setOpenedLink(linkedThread)
    if (view.threads.some((t) => t.id === linkedThread)) {
      setOpenThreadId(linkedThread)
      setDialog(null)
    }
  }

  const onChanged = React.useCallback(() => {
    setRefreshKey((k) => k + 1)
    void reload()
  }, [reload])

  useVoiceScreen(
    "board",
    () => ({
      visible_creators: cardsForVoice.map((c) => ({
        id: c.creator.id,
        name: c.creator.name,
        handle: c.creator.handle,
      })),
      // The draft belongs to one creator: the backend lays spoken terms over it only
      // for that creator.
      current_terms: dialog === "counter" && openCard ? counterDraft : null,
      current_terms_creator_id:
        dialog === "counter" && openCard ? openCard.creator.id : null,
    }),
    (intent: VoiceIntent) => {
      if (intent.kind === "open_thread" && intent.open_thread) {
        const match = cardsForVoice.find(
          (c) => c.creator.id === intent.open_thread?.creator_id
        )
        if (match) openThread(match.id)
      }
      if (intent.kind === "sort" && intent.sort) {
        captureFlip()
        setSortKey(intent.sort)
      }
      // Voice only opens the confirming UI: nothing is sent from here.
      if (
        view &&
        (intent.kind === "counter" ||
          intent.kind === "award" ||
          intent.kind === "decline")
      ) {
        const target = intent.creator_id
          ? cardsForVoice.find((c) => c.creator.id === intent.creator_id)
          : openCard
        if (!target) return
        const allowed = target.allowed_actions
        if (intent.kind === "counter" && allowed.includes("counter")) {
          const base =
            dialog === "counter" && openThreadId === target.id
              ? counterDraft
              : counterPrefill(target, view.brief)
          setCounterDraft(intent.terms ? mergeDraft(base, intent.terms) : base)
          setOpenThreadId(target.id)
          setDialog("counter")
        } else if (intent.kind === "award" && allowed.includes("award")) {
          setOpenThreadId(target.id)
          setDialog("award")
        } else if (intent.kind === "decline") {
          const kind = allowed.includes("decline")
            ? "decline"
            : allowed.includes("withdraw")
              ? "withdraw"
              : null
          if (kind) {
            setOpenThreadId(target.id)
            setDialog(kind)
          }
        }
      }
    }
  )

  useBatchDoorbell(batchId, () => {
    setRefreshKey((k) => k + 1)
    void reload()
  }, { live })

  const onSortChange = (value: BoardSortKey) => {
    captureFlip()
    setSortKey(value)
  }

  useGSAP(
    () => {
      const grid = gridRef.current
      if (!grid || phase !== "ready" || threads.length === 0) return
      const mm = gsap.matchMedia()
      if (!dealtIn.current) {
        dealtIn.current = true
        mm.add("(prefers-reduced-motion: no-preference)", () => {
          const cards = grid.querySelectorAll("[data-flip-id]")
          if (cards.length) {
            gsap.from(cards, {
              y: 24,
              opacity: 0,
              stagger: 0.06,
              duration: 0.45,
              ease: "power2.out",
            })
          }
        })
        return () => mm.revert()
      }
      const from = flipFrom.current
      flipFrom.current = null
      if (!from) return
      mm.add("(prefers-reduced-motion: no-preference)", () => {
        Flip.from(from, {
          targets: grid.querySelectorAll("[data-flip-id]"),
          duration: 0.5,
          ease: "power2.inOut",
          scale: false,
        })
      })
      return () => mm.revert()
    },
    { dependencies: [threads, phase], scope: gridRef }
  )

  const retry = async (threadId: string) => {
    const { error } = await api.POST("/api/v1/threads/{thread_id}/retry", {
      params: { path: { thread_id: threadId } },
    })
    if (error) {
      toast.error("Retry failed")
      return
    }
    await reload()
  }

  if (phase === "loading") {
    return (
      <div className="p-6 text-muted-foreground text-sm">Loading board…</div>
    )
  }

  if (phase === "failed" || !view) {
    return (
      <div className="space-y-3 p-6">
        <p className="text-destructive text-sm">Could not load this board.</p>
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
    <div className="mx-auto max-w-6xl space-y-6 p-6">
      <div className="space-y-1">
        <Link
          href="/brand/batches"
          className="text-muted-foreground text-sm hover:text-foreground"
        >
          All launches
        </Link>
        <h1 className="text-2xl font-semibold tracking-tight">
          {view.brief.product_name}
        </h1>
        <p className="text-muted-foreground text-sm">
          {briefAskLine(view.brief)}
        </p>
        <p className="text-muted-foreground text-xs">
          {launchedAgo(view.kpis.launched_at, now)}
        </p>
      </div>

      <KpiStrip
        kpis={view.kpis}
        hiresTarget={view.brief.hires_target}
        now={now}
      />

      <div className="flex flex-wrap items-center justify-between gap-3">
        <ToggleGroup
          value={[sortKey]}
          onValueChange={(values) => {
            const next = values[0] as BoardSortKey | undefined
            if (next) onSortChange(next)
          }}
        >
          {SORT_OPTIONS.map((opt) => (
            <ToggleGroupItem key={opt.key} value={opt.key}>
              {opt.label}
            </ToggleGroupItem>
          ))}
        </ToggleGroup>
        {view.kpis.hired >= 1 ? (
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={() => setDeclineRestOpen(true)}
          >
            Decline remaining
          </Button>
        ) : null}
      </div>

      <div
        ref={gridRef}
        className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3"
      >
        {threads.map((thread) => (
          <ThreadCardView
            key={thread.id}
            thread={thread}
            now={now}
            revealEmail={emailAnimate[thread.id] === true}
            onOpen={() => openThread(thread.id)}
            onRetry={(tid) => void retry(tid)}
          />
        ))}
      </div>

      <ThreadDrawer
        threadId={openThreadId}
        refreshKey={refreshKey}
        onClose={() => openThread(null)}
        onRetry={(tid) => void retry(tid)}
        dialog={dialog}
        onOpenDialog={openDialog}
        onCloseDialog={() => setDialog(null)}
        counterDraft={counterDraft}
        onCounterDraftChange={setCounterDraft}
        onChanged={onChanged}
      />

      <DeclineRestDialog
        batchId={batchId}
        open={declineRestOpen}
        onClose={() => setDeclineRestOpen(false)}
        onDone={onChanged}
      />

      <React.Suspense fallback={null}>
        <ThreadLink onThread={setLinkedThread} />
      </React.Suspense>
    </div>
  )
}
