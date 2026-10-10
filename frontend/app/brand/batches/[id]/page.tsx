"use client"

import { useGSAP } from "@gsap/react"
import gsap from "gsap"
import { Flip } from "gsap/Flip"
import Link from "next/link"
import { useParams } from "next/navigation"
import * as React from "react"
import { toast } from "sonner"

import { KpiStrip } from "@/components/board/kpi-strip"
import { ThreadCardView } from "@/components/board/thread-card"
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group"
import { useApi } from "@/hooks/use-api"
import type { components } from "@/lib/api/schema"
import {
  type BoardSortKey,
  briefAskLine,
  isLive,
  launchedAgo,
  sortThreads,
} from "@/lib/board/state"
import { useBatchDoorbell } from "@/lib/supabase/realtime"

gsap.registerPlugin(useGSAP, Flip)

type BatchView = components["schemas"]["BatchView"]

const SORT_OPTIONS: { key: BoardSortKey; label: string }[] = [
  { key: "best_value", label: "Best value" },
  { key: "price", label: "Price" },
  { key: "status", label: "Status" },
  { key: "recent", label: "Recent" },
]

type FlipState = ReturnType<typeof Flip.getState>

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

  useBatchDoorbell(batchId, () => {
    void reload()
  }, { live })

  const captureFlip = React.useCallback(() => {
    const grid = gridRef.current
    if (!grid) return
    const cards = grid.querySelectorAll("[data-flip-id]")
    if (cards.length) flipFrom.current = Flip.getState(cards)
  }, [])

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

      <KpiStrip kpis={view.kpis} now={now} />

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
            onOpen={() => {}}
            onRetry={(tid) => void retry(tid)}
          />
        ))}
      </div>
    </div>
  )
}
