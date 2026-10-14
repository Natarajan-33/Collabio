"use client"

import { useRouter } from "next/navigation"
import * as React from "react"

import { OfferRow } from "@/components/offers/offer-row"
import { useCreatorId } from "@/components/shell/creator-context"
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group"
import {
  useVoiceScreen,
  type VoiceIntent,
} from "@/components/voice/voice-screen"
import { useApi } from "@/hooks/use-api"
import {
  OFFER_SORTS,
  OFFER_TABS,
  offerPath,
  visibleOffers,
  type OfferCounts,
  type OfferListItem,
  type OfferSort,
  type OfferTab,
} from "@/lib/deal/offers"
import { useCreatorDoorbell } from "@/lib/supabase/realtime"
import { cn } from "@/lib/utils"

export default function CreatorOffersPage() {
  const api = useApi()
  const router = useRouter()
  const creatorId = useCreatorId()

  const [tab, setTab] = React.useState<OfferTab>("needs_you")
  const [sort, setSort] = React.useState<OfferSort>("fit")
  const [items, setItems] = React.useState<OfferListItem[] | null>(null)
  const [counts, setCounts] = React.useState<OfferCounts | null>(null)
  const [failed, setFailed] = React.useState(false)
  const [now, setNow] = React.useState(() => new Date())
  const [attempt, setAttempt] = React.useState(0)
  /** Only the newest request may write: a slow answer for an old tab must not win. */
  const latest = React.useRef(0)
  const mounted = React.useRef(false)
  React.useEffect(() => {
    mounted.current = true
    return () => {
      mounted.current = false
    }
  }, [])

  const fetchOffers = React.useCallback(async () => {
    try {
      const [list, tally] = await Promise.all([
        api.GET("/api/v1/offers", { params: { query: { tab, sort } } }),
        api.GET("/api/v1/offers/counts"),
      ])
      return { list: list.data ?? null, tally: tally.data ?? null }
    } catch {
      // A network failure reads like any other failed load: the error state.
      return { list: null, tally: null }
    }
  }, [api, tab, sort])

  const apply = React.useCallback(
    (result: Awaited<ReturnType<typeof fetchOffers>>, mine: number) => {
      if (!mounted.current || mine !== latest.current) return
      if (result.tally) setCounts(result.tally)
      if (result.list) {
        setItems(result.list)
        setNow(new Date())
        setFailed(false)
      } else {
        setFailed(true)
      }
    },
    []
  )

  React.useEffect(() => {
    const mine = ++latest.current
    void (async () => apply(await fetchOffers(), mine))()
  }, [fetchOffers, apply, attempt])

  useCreatorDoorbell(creatorId, () => {
    const mine = ++latest.current
    void fetchOffers().then((result) => apply(result, mine))
  })

  const open = React.useCallback(
    (threadId: string) => router.push(offerPath(threadId)),
    [router]
  )

  useVoiceScreen(
    "offers",
    () => ({
      visible_creators: [],
      visible_offers: visibleOffers(items ?? []),
    }),
    (intent: VoiceIntent) => {
      if (intent.kind !== "open_offer" || !intent.thread_id) return
      if (items?.some((item) => item.thread_id === intent.thread_id)) {
        open(intent.thread_id)
      }
    }
  )

  function changeTab(next: OfferTab) {
    if (next === tab) return
    setItems(null)
    setFailed(false)
    setTab(next)
  }

  const emptyText = OFFER_TABS.find((t) => t.key === tab)?.empty ?? ""

  return (
    <div className="mx-auto max-w-5xl space-y-6 p-6">
      <div className="space-y-1">
        <h1 className="text-2xl font-semibold tracking-tight">Offers</h1>
        <p className="text-sm text-muted-foreground">
          Brands that want to work with you, and where each one stands.
        </p>
      </div>

      <div className="flex flex-wrap items-center justify-between gap-3">
        <div
          role="tablist"
          aria-label="Offer status"
          className="flex flex-wrap gap-1 rounded-lg bg-muted p-1"
        >
          {OFFER_TABS.map((t) => {
            const selected = t.key === tab
            return (
              <button
                key={t.key}
                type="button"
                role="tab"
                aria-selected={selected}
                onClick={() => changeTab(t.key)}
                className={cn(
                  "inline-flex h-8 items-center gap-2 rounded-md px-3 text-sm font-medium outline-none focus-visible:ring-3 focus-visible:ring-ring/50",
                  selected
                    ? "bg-background text-foreground shadow-sm"
                    : "text-muted-foreground hover:text-foreground"
                )}
              >
                {t.label}
                {counts ? (
                  <span className="num text-xs text-muted-foreground">
                    {counts[t.key]}
                  </span>
                ) : null}
              </button>
            )
          })}
        </div>

        <div className="flex items-center gap-2">
          <span className="text-sm text-muted-foreground">Sort</span>
          <ToggleGroup
            aria-label="Sort offers"
            value={[sort]}
            onValueChange={(values) => {
              const next = values[0] as OfferSort | undefined
              if (next) setSort(next)
            }}
          >
            {OFFER_SORTS.map((option) => (
              <ToggleGroupItem key={option.key} value={option.key}>
                {option.label}
              </ToggleGroupItem>
            ))}
          </ToggleGroup>
        </div>
      </div>

      {failed && items === null ? (
        <div className="space-y-3">
          <p className="text-sm text-destructive">
            Could not load your offers.
          </p>
          <button
            type="button"
            className="text-sm text-voice underline"
            onClick={() => setAttempt((n) => n + 1)}
          >
            Try again
          </button>
        </div>
      ) : items === null ? (
        <p className="text-sm text-muted-foreground">Loading offers…</p>
      ) : items.length === 0 ? (
        <p className="rounded-xl border border-dashed px-4 py-10 text-center text-sm text-muted-foreground">
          {emptyText}
        </p>
      ) : (
        <ul className="space-y-3">
          {items.map((offer) => (
            <OfferRow
              key={offer.thread_id}
              offer={offer}
              now={now}
              href={offerPath(offer.thread_id)}
              onOpen={open}
            />
          ))}
        </ul>
      )}
    </div>
  )
}
