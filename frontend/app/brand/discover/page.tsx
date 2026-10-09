"use client"

import { useGSAP } from "@gsap/react"
import gsap from "gsap"
import { Flip } from "gsap/Flip"
import { Mic, TriangleAlert, X } from "lucide-react"
import { useRouter } from "next/navigation"
import * as React from "react"
import { toast } from "sonner"

import { CreatorCard } from "@/components/deal/creator-card"
import { FilterChips } from "@/components/deal/filter-chips"
import { SelectionTray } from "@/components/deal/selection-tray"
import { Button } from "@/components/ui/button"
import BlurText from "@/components/ui/blur-text"
import {
  useVoiceScreen,
  type VoiceIntent,
} from "@/components/voice/voice-screen"
import { useApi } from "@/hooks/use-api"
import { useHydrated } from "@/hooks/use-hydrated"
import {
  SELECTION_CAP_MESSAGE,
  applySearchIntent,
  chipsFor,
  emptyDiscover,
  loadSearch,
  loadSelection,
  normalizeFilters,
  removeFilter,
  requestFor,
  saveSearch,
  saveSelection,
  selectionOverflow,
  selectionReducer,
  type CreatorCard as Creator,
  type DiscoverState,
  type FilterChip,
  type SearchFilters,
  type SearchResponse,
  type SelectionAction,
} from "@/lib/discover/state"
import { cn } from "@/lib/utils"

gsap.registerPlugin(useGSAP, Flip)

const REVIEW_PATH = "/brand/discover/review"
const HEADING = "Who should tell your story?"

/** What the page is doing about its results. */
type Phase = "loading" | "ready" | "unavailable" | "failed"

type FlipState = ReturnType<typeof Flip.getState>

function motionWelcome() {
  return (
    typeof window.matchMedia === "function" &&
    window.matchMedia("(prefers-reduced-motion: no-preference)").matches
  )
}

/** Where every card is now, so the grid can glide from here to the new results. */
function captureLayout(grid: HTMLElement | null): FlipState | null {
  if (!grid || !motionWelcome()) return null
  const cards = grid.querySelectorAll("[data-flip-id]")
  return cards.length > 0 ? Flip.getState(cards) : null
}

function Skeleton() {
  return (
    <div
      aria-hidden
      className="grid [grid-template-columns:repeat(auto-fill,minmax(min(100%,21.5rem),1fr))] gap-4"
    >
      {Array.from({ length: 6 }, (_, i) => (
        <div key={i} className="h-80 rounded-2xl border bg-muted/40" />
      ))}
    </div>
  )
}

function EmptyState({
  chips,
  onRemove,
}: {
  chips: FilterChip[]
  onRemove: (chip: FilterChip) => void
}) {
  const titleId = React.useId()

  return (
    <section
      aria-labelledby={titleId}
      className="flex flex-col items-start gap-4 rounded-2xl border border-dashed bg-card/60 p-8"
    >
      <h2 id={titleId} className="font-display text-3xl">
        No creators match
      </h2>
      {chips.length > 0 ? (
        <>
          <p className="max-w-prose text-sm text-muted-foreground">
            Nothing fits all of these at once. Take one off to widen the search.
          </p>
          <ul className="flex flex-wrap gap-2">
            {chips.map((chip) => (
              <li key={chip.id}>
                <button
                  type="button"
                  onClick={() => onRemove(chip)}
                  aria-label={`Remove ${chip.label}`}
                  className="inline-flex h-8 items-center gap-1.5 rounded-full border bg-background pr-2 pl-3.5 text-sm outline-none hover:bg-muted focus-visible:ring-3 focus-visible:ring-ring/50"
                >
                  <span aria-hidden>{chip.label}</span>
                  <X aria-hidden className="size-3.5 text-muted-foreground" />
                </button>
              </li>
            ))}
          </ul>
        </>
      ) : (
        <p className="max-w-prose text-sm text-muted-foreground">
          Try describing the creators another way.
        </p>
      )}
    </section>
  )
}

function ErrorState({
  unavailable,
  onRetry,
}: {
  unavailable: boolean
  onRetry: () => void
}) {
  return (
    <div
      role="alert"
      className="flex flex-col items-start gap-3 rounded-2xl border border-destructive/30 bg-card p-8"
    >
      <TriangleAlert aria-hidden className="size-5 text-destructive" />
      <h2 className="font-display text-3xl">
        {unavailable
          ? "Search is unavailable right now"
          : "Couldn't load creators"}
      </h2>
      <p className="max-w-prose text-sm text-muted-foreground">
        Your filters are kept. Try again in a moment.
      </p>
      <Button variant="outline" onClick={onRetry}>
        Try again
      </Button>
    </div>
  )
}

/** Where Discover begins: the search it was last on, and the batch so far. */
function startState(): DiscoverState {
  const last = loadSearch()
  return {
    ...emptyDiscover,
    query: last?.query ?? null,
    filters: last?.filters ?? emptyDiscover.filters,
    selected: loadSelection(),
  }
}

function Discover() {
  const api = useApi()
  const router = useRouter()

  const [state, setState] = React.useState<DiscoverState>(startState)
  const [phase, setPhase] = React.useState<Phase>("loading")
  // Every creator seen this visit, so the tray can show a face for a pick that a
  // later search has moved off screen.
  const [known, setKnown] = React.useState<Record<string, Creator>>({})

  // The latest state for handlers that run between renders (voice commands arrive
  // one after another, each needing what the last one did).
  const stateRef = React.useRef(state)
  const searchCount = React.useRef(0)
  const gridRef = React.useRef<HTMLDivElement>(null)
  const flipFrom = React.useRef<FlipState | null>(null)

  const commit = React.useCallback((next: DiscoverState) => {
    stateRef.current = next
    setState(next)
  }, [])

  const search = React.useCallback(
    async (from: DiscoverState) => {
      const request = requestFor(from)
      // Only the newest search may answer: an earlier one can arrive late.
      const mine = ++searchCount.current
      setPhase("loading")
      saveSearch(request)

      let failure: Phase = "failed"
      let found: SearchResponse | undefined
      try {
        const { data, response } = await api.POST("/api/v1/discovery/search", {
          body: request,
        })
        found = data
        if (!data && response.status === 503) failure = "unavailable"
      } catch {
        // A network failure reads as a failed search.
      }
      if (mine !== searchCount.current) return

      if (!found) {
        commit({ ...stateRef.current, results: [] })
        setPhase(failure)
        return
      }
      flipFrom.current = captureLayout(gridRef.current)
      const results = found.results
      commit({
        ...stateRef.current,
        query: found.query,
        filters: normalizeFilters(found.filters),
        results,
      })
      setKnown((seen) => ({
        ...seen,
        ...Object.fromEntries(results.map((creator) => [creator.id, creator])),
      }))
      setPhase("ready")
    },
    [api, commit]
  )

  React.useEffect(() => {
    void search(stateRef.current)
  }, [search])

  // Re-searches with the state as it now is.
  const research = React.useCallback(
    (next: DiscoverState) => {
      commit(next)
      void search(next)
    },
    [commit, search]
  )

  const applySelection = React.useCallback(
    (action: SelectionAction) => {
      const before = stateRef.current
      const next = selectionReducer(before, action)
      if (selectionOverflow(before, action)) {
        toast.info(SELECTION_CAP_MESSAGE, { id: "selection-cap" })
      }
      commit(next)
      saveSelection(next.selected)
    },
    [commit]
  )

  const dropChip = (chip: FilterChip) =>
    research(removeFilter(stateRef.current, chip))
  const changeFilters = (filters: SearchFilters) =>
    research({ ...stateRef.current, filters })
  const clearQuery = () => research({ ...stateRef.current, query: null })

  const openReview = () => {
    if (stateRef.current.selected.length === 0) {
      toast.info("Select creators to review first", { id: "review-empty" })
      return
    }
    router.push(REVIEW_PATH)
  }

  useVoiceScreen(
    "discover",
    () => ({
      visible_creators: stateRef.current.results.map(
        ({ id, name, handle }) => ({ id, name, handle })
      ),
    }),
    (spoken: VoiceIntent) => {
      switch (spoken.kind) {
        case "search":
          if (spoken.search) {
            research(applySearchIntent(stateRef.current, spoken.search))
          }
          return
        case "select": {
          const pick = spoken.select
          if (!pick) return
          if (pick.top_n != null)
            applySelection({ type: "top_n", n: pick.top_n })
          if (pick.creator_ids.length > 0) {
            applySelection({ type: "add", ids: pick.creator_ids })
          }
          return
        }
        case "clear_selection":
          applySelection({ type: "clear" })
          return
        case "open_review":
          openReview()
          return
      }
    }
  )

  // When results change, the cards glide to their new places and new ones fade in.
  // Nothing moves when the user prefers reduced motion.
  useGSAP(
    () => {
      const from = flipFrom.current
      flipFrom.current = null
      const grid = gridRef.current
      if (!from || !grid) return

      const mm = gsap.matchMedia()
      mm.add("(prefers-reduced-motion: no-preference)", () => {
        Flip.from(from, {
          targets: grid.querySelectorAll("[data-flip-id]"),
          duration: 0.6,
          ease: "power2.inOut",
          // Cards differ in height: moving them is enough, stretching is not.
          scale: false,
          onEnter: (entering) =>
            gsap.fromTo(
              entering,
              { autoAlpha: 0, y: 16 },
              {
                autoAlpha: 1,
                y: 0,
                duration: 0.45,
                delay: 0.2,
                stagger: 0.025,
                ease: "power2.out",
              }
            ),
        })
      })
      return () => mm.revert()
    },
    { dependencies: [state.results], scope: gridRef }
  )

  const chips = chipsFor(state.filters)
  const { results, selected } = state
  const loading = phase === "loading"
  const count = results.length

  return (
    <div className={cn("flex flex-col gap-6", selected.length > 0 && "pb-24")}>
      <header className="flex max-w-3xl flex-col gap-3 pt-2">
        <div aria-hidden>
          <BlurText
            text={HEADING}
            delay={90}
            className="font-display text-4xl leading-[1.05] tracking-tight sm:text-6xl"
          />
        </div>
        <h1 className="sr-only">{HEADING}</h1>
        <p className="flex items-center gap-2 text-sm text-muted-foreground">
          <Mic aria-hidden className="size-4 shrink-0" />
          Hold Space and describe the creators you want
        </p>
        <p className="font-display text-lg text-muted-foreground italic">
          Try “tech creators doing short-form reviews under two thousand
          dollars”
        </p>
      </header>

      <FilterChips
        filters={state.filters}
        onRemove={dropChip}
        onFiltersChange={changeFilters}
      />

      <section
        aria-label="Creators"
        aria-busy={loading}
        className="flex flex-col gap-4"
      >
        <div className="flex min-h-6 items-center gap-2 text-sm text-muted-foreground">
          <p role="status">
            {loading && count === 0 ? (
              "Finding creators…"
            ) : phase === "unavailable" || phase === "failed" ? (
              "No results"
            ) : count === 0 ? (
              "No creators"
            ) : (
              <>
                <span className="num text-foreground">{count}</span>{" "}
                {count === 1 ? "creator" : "creators"}
                {state.query
                  ? ` for “${state.query}”`
                  : ", most followed first"}
              </>
            )}
          </p>
          {state.query ? (
            <button
              type="button"
              onClick={clearQuery}
              aria-label="Clear search words"
              className="flex size-6 items-center justify-center rounded-full outline-none hover:bg-muted hover:text-foreground focus-visible:ring-3 focus-visible:ring-ring/50"
            >
              <X aria-hidden className="size-3.5" />
            </button>
          ) : null}
        </div>

        {phase === "unavailable" || phase === "failed" ? (
          <ErrorState
            unavailable={phase === "unavailable"}
            onRetry={() => void search(stateRef.current)}
          />
        ) : count > 0 ? (
          <div
            ref={gridRef}
            className={cn(
              "grid [grid-template-columns:repeat(auto-fill,minmax(min(100%,21.5rem),1fr))] gap-4 transition-opacity",
              loading && "opacity-60"
            )}
          >
            {results.map((creator) => (
              <CreatorCard
                key={creator.id}
                creator={creator}
                filters={state.filters}
                selected={selected.includes(creator.id)}
                onToggle={(id) => applySelection({ type: "toggle", id })}
              />
            ))}
          </div>
        ) : loading ? (
          <Skeleton />
        ) : (
          <EmptyState chips={chips} onRemove={dropChip} />
        )}
      </section>

      <SelectionTray
        items={selected.map((id) => ({ id, creator: known[id] }))}
        reviewHref={REVIEW_PATH}
        onClear={() => applySelection({ type: "clear" })}
      />
    </div>
  )
}

export default function DiscoverPage() {
  // The page starts from session storage, which the server cannot see.
  return useHydrated() ? (
    <Discover />
  ) : (
    <div className="pt-2">
      <Skeleton />
    </div>
  )
}
