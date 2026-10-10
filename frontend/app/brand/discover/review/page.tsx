"use client"

import { ArrowLeft, LoaderCircle, TriangleAlert } from "lucide-react"
import Link from "next/link"
import { useRouter } from "next/navigation"
import * as React from "react"
import { toast } from "sonner"

import { CompareTable } from "@/components/deal/compare-table"
import { Button, buttonVariants } from "@/components/ui/button"
import {
  useVoiceScreen,
  type VoiceIntent,
} from "@/components/voice/voice-screen"
import { useApi } from "@/hooks/use-api"
import { useHydrated } from "@/hooks/use-hydrated"
import {
  applySearchIntent,
  bestFitPackage,
  emptyDiscover,
  loadSearch,
  loadSelection,
  requestFor,
  saveSearch,
  saveSelection,
  type CreatorCard as Creator,
} from "@/lib/discover/state"
import { cn } from "@/lib/utils"

const DISCOVER_PATH = "/brand/discover"

type Phase = "loading" | "ready" | "failed"

/** An id that no longer names a creator in the marketplace (or never did). */
const GONE = new Set([404, 422])

function StartNegotiation({
  disabled,
  pending,
  onStart,
}: {
  disabled: boolean
  pending: boolean
  onStart: () => void
}) {
  return (
    <Button size="lg" disabled={disabled || pending} onClick={onStart}>
      {pending ? <LoaderCircle aria-hidden className="animate-spin" /> : null}
      Start negotiation
    </Button>
  )
}

function BackToCreators({ className }: { className?: string }) {
  return (
    <Link
      href={DISCOVER_PATH}
      className={cn(
        buttonVariants({ variant: "outline", size: "sm" }),
        className
      )}
    >
      <ArrowLeft aria-hidden />
      Back to creators
    </Link>
  )
}

function Review() {
  const api = useApi()
  const router = useRouter()

  // The batch picked on Discover, in the order it was picked.
  const [ids, setIds] = React.useState<string[]>(loadSelection)
  const [cards, setCards] = React.useState<Record<string, Creator>>({})
  // Which of a creator's packages is compared, by creator id.
  const [chosen, setChosen] = React.useState<Record<string, string>>({})
  const [phase, setPhase] = React.useState<Phase>("loading")
  const [starting, setStarting] = React.useState(false)
  // Set at once, unlike state, so a double click cannot post twice.
  const startingRef = React.useRef(false)

  const select = React.useCallback((next: string[]) => {
    setIds(next)
    saveSelection(next)
  }, [])

  const load = React.useCallback(
    async (wanted: string[]) => {
      if (wanted.length === 0) {
        setPhase("ready")
        return
      }

      let replies
      try {
        replies = await Promise.all(
          wanted.map((id) =>
            api.GET("/api/v1/creators/{creator_id}", {
              params: { path: { creator_id: id } },
            })
          )
        )
      } catch {
        setPhase("failed")
        return
      }
      // A creator who is gone just drops out; anything else is worth another try.
      if (replies.some((r) => !r.data && !GONE.has(r.response.status))) {
        setPhase("failed")
        return
      }

      const found = replies.flatMap((r) => (r.data ? [r.data] : []))
      // Compare the package the last search was after, when there was one.
      const filters = loadSearch()?.filters ?? emptyDiscover.filters
      setCards(Object.fromEntries(found.map((c) => [c.id, c])))
      setChosen(
        Object.fromEntries(
          found.flatMap((c) => {
            const best = bestFitPackage(c.packages, filters)
            return best ? [[c.id, best.id]] : []
          })
        )
      )
      if (found.length !== wanted.length) {
        select(wanted.filter((id) => found.some((c) => c.id === id)))
      }
      setPhase("ready")
    },
    [api, select]
  )

  // Loads the batch once, on arrival. (The state starts as "loading".)
  const first = React.useRef(ids)
  React.useEffect(() => {
    void load(first.current)
  }, [load])

  // The batch becomes a draft brief, and the brief page takes it from there.
  async function startNegotiation() {
    if (startingRef.current || ids.length === 0) return
    startingRef.current = true
    setStarting(true)

    let briefId: string | undefined
    try {
      const { data } = await api.POST("/api/v1/briefs", {
        body: { creator_ids: ids },
      })
      briefId = data?.id
    } catch {
      // Handled with the missing id below.
    }

    if (briefId) {
      // Stay "starting" while the next page loads: nothing more to start here.
      router.push(`/brand/briefs/${briefId}`)
      return
    }
    toast.error("Couldn't start the brief")
    startingRef.current = false
    setStarting(false)
  }

  const creators = ids.flatMap((id) => (cards[id] ? [cards[id]] : []))

  useVoiceScreen(
    "review",
    () => ({
      visible_creators: creators.map(({ id, name, handle }) => ({
        id,
        name,
        handle,
      })),
    }),
    (spoken: VoiceIntent) => {
      switch (spoken.kind) {
        case "search":
          // Searching is Discover's job: go there with it applied.
          if (spoken.search) {
            saveSearch(
              requestFor(applySearchIntent(emptyDiscover, spoken.search))
            )
            router.push(DISCOVER_PATH)
          }
          return
        case "select": {
          // On this screen selecting narrows the comparison to who was asked for.
          const pick = spoken.select
          if (!pick) return
          let next = ids
          if (pick.top_n != null) next = next.slice(0, pick.top_n)
          if (pick.creator_ids.length > 0) {
            const named = next.filter((id) => pick.creator_ids.includes(id))
            if (named.length > 0) next = named
          }
          if (next.length !== ids.length) select(next)
          return
        }
        case "clear_selection":
          select([])
          return
        // "open_review": this is it.
      }
    }
  )

  return (
    <div className="flex flex-col gap-6">
      <header className="flex flex-wrap items-end justify-between gap-4 pt-2">
        <div className="flex flex-col gap-3">
          <BackToCreators className="w-fit" />
          <h1 className="font-display text-4xl leading-[1.05] tracking-tight sm:text-5xl">
            Compare your shortlist
          </h1>
          <p className="text-sm text-muted-foreground">
            {creators.length > 0 ? (
              <>
                <span className="num text-foreground">{creators.length}</span>{" "}
                {creators.length === 1 ? "creator" : "creators"}, side by side.
                The best value in each row is marked.
              </>
            ) : (
              "Their packages, side by side."
            )}
          </p>
        </div>
        <StartNegotiation
          disabled={creators.length === 0}
          pending={starting}
          onStart={() => void startNegotiation()}
        />
      </header>

      {phase === "loading" ? (
        <div
          role="status"
          className="rounded-2xl border bg-muted/40 p-8 text-sm text-muted-foreground"
        >
          Loading your shortlist…
        </div>
      ) : phase === "failed" ? (
        <div
          role="alert"
          className="flex flex-col items-start gap-3 rounded-2xl border border-destructive/30 bg-card p-8"
        >
          <TriangleAlert aria-hidden className="size-5 text-destructive" />
          <h2 className="font-display text-3xl">Couldn&apos;t load creators</h2>
          <p className="max-w-prose text-sm text-muted-foreground">
            Your shortlist is kept. Try again in a moment.
          </p>
          <Button
            variant="outline"
            onClick={() => {
              setPhase("loading")
              void load(ids)
            }}
          >
            Try again
          </Button>
        </div>
      ) : creators.length === 0 ? (
        <section
          aria-labelledby="nothing-to-compare"
          className="flex flex-col items-start gap-4 rounded-2xl border border-dashed bg-card/60 p-8"
        >
          <h2 id="nothing-to-compare" className="font-display text-3xl">
            Nothing to compare yet
          </h2>
          <p className="max-w-prose text-sm text-muted-foreground">
            Pick creators on Discover, then come back to see their packages side
            by side.
          </p>
          <BackToCreators />
        </section>
      ) : (
        <div className="overflow-hidden rounded-2xl border bg-background">
          <CompareTable
            creators={creators}
            chosen={chosen}
            onChoose={(creatorId, packageId) =>
              setChosen((current) => ({ ...current, [creatorId]: packageId }))
            }
            onRemove={(creatorId) =>
              select(ids.filter((id) => id !== creatorId))
            }
          />
        </div>
      )}
    </div>
  )
}

export default function ReviewPage() {
  // The batch comes from session storage, which the server cannot see.
  return useHydrated() ? <Review /> : null
}
