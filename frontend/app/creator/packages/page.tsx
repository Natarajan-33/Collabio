"use client"

import { Lock, Mic, TriangleAlert } from "lucide-react"
import * as React from "react"
import { toast } from "sonner"

import {
  PackageDraftCard,
  type PackageStatus,
} from "@/components/deal/package-draft-card"
import { PackageStrip } from "@/components/deal/package-strip"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  useVoiceScreen,
  type VoiceIntent,
} from "@/components/voice/voice-screen"
import { useApi } from "@/hooks/use-api"
import { formatCents } from "@/lib/money"
import {
  completeDraft,
  draftBody,
  draftFromPackage,
  draftViolations,
  emptyDraft,
  fieldLabel,
  mergeViolations,
  missingFields,
  rejectionFrom,
  sameDraft,
  type MyPackage,
  type PackageDraft,
  type RuleViolation,
} from "@/lib/packages/draft"
import { cn } from "@/lib/utils"

/** What the page is doing about its packages. */
type Phase = "loading" | "ready" | "failed"

/** One package open in the card, and what the page knows about it. */
type Editor = {
  /** Changes when a different package is opened, so the card starts fresh. */
  session: number
  /** The saved package, or null for a draft the server has not seen. */
  id: string | null
  status: PackageStatus
  draft: PackageDraft
  /** The draft as the server has it; null until it is first saved. */
  saved: PackageDraft | null
  /** The private floor as the server has it. */
  floor: number | null
  /** Rules the server said are broken. The next edit makes them stale, so it clears them. */
  rejected: RuleViolation[]
  pending: "save" | "publish" | "floor" | null
}

type Persisted = MyPackage & { warnings?: string[] }

const ERROR_ID = "packages-error"

/** Cheapest first, as the server lists them. */
function byPrice(packages: MyPackage[]): MyPackage[] {
  return [...packages].sort((a, b) => a.base_price_cents - b.base_price_cents)
}

function upsert(packages: MyPackage[], saved: MyPackage): MyPackage[] {
  const known = packages.some((p) => p.id === saved.id)
  return byPrice(
    known
      ? packages.map((p) => (p.id === saved.id ? saved : p))
      : [...packages, saved]
  )
}

/** The draft has something the server does not. */
function hasChanges(editor: Editor): boolean {
  return !sameDraft(editor.draft, editor.saved ?? emptyDraft())
}

function Skeleton() {
  return (
    <div
      aria-hidden
      className="grid [grid-template-columns:repeat(auto-fill,minmax(min(100%,19rem),1fr))] gap-4"
    >
      {Array.from({ length: 3 }, (_, i) => (
        <div key={i} className="h-44 rounded-2xl border bg-muted/40" />
      ))}
    </div>
  )
}

function ErrorState({ onRetry }: { onRetry: () => void }) {
  return (
    <div
      role="alert"
      className="flex flex-col items-start gap-3 rounded-2xl border border-destructive/30 bg-card p-8"
    >
      <TriangleAlert aria-hidden className="size-5 text-destructive" />
      <h2 className="font-display text-3xl">
        Couldn&apos;t load your packages
      </h2>
      <p className="max-w-prose text-sm text-muted-foreground">
        Nothing was lost. Try again in a moment.
      </p>
      <Button variant="outline" onClick={onRetry}>
        Try again
      </Button>
    </div>
  )
}

function PackageCard({
  pkg,
  open,
  locked,
  onEdit,
}: {
  pkg: MyPackage
  /** This is the package in the card. */
  open: boolean
  locked: boolean
  onEdit: () => void
}) {
  const published = pkg.status === "published"

  return (
    <div
      role="group"
      aria-label={pkg.name}
      data-open={open ? "" : undefined}
      className={cn(
        "flex flex-col gap-3 rounded-2xl border bg-card p-4 transition-shadow",
        open && "ring-2 ring-ring/60"
      )}
    >
      <div className="flex items-center justify-between gap-2">
        <Badge
          variant={published ? "secondary" : "outline"}
          className={cn(published && "bg-gain/15 text-gain-ink")}
        >
          {published ? "Published" : "Draft"}
        </Badge>
        <Button
          type="button"
          variant="outline"
          size="sm"
          aria-label={`Edit ${pkg.name}`}
          disabled={locked}
          onClick={onEdit}
        >
          Edit
        </Button>
      </div>
      <PackageStrip pkg={pkg} />
      {pkg.floor_price_cents !== null ? (
        <p className="flex items-center gap-1.5 text-xs text-muted-foreground">
          <Lock aria-hidden className="size-3 shrink-0" />
          <span className="num text-foreground">
            Floor {formatCents(pkg.floor_price_cents)}
          </span>
          <span aria-hidden>·</span>
          <span>Only you see this</span>
        </p>
      ) : null}
    </div>
  )
}

function NewPackageCard({
  locked,
  onStart,
}: {
  locked: boolean
  onStart: () => void
}) {
  return (
    <div className="flex flex-col items-start gap-3 rounded-2xl border border-dashed bg-card/60 p-5">
      <span
        aria-hidden
        className="flex size-9 items-center justify-center rounded-full bg-voice text-voice-foreground"
      >
        <Mic className="size-4" />
      </span>
      <p className="font-display text-2xl leading-tight">
        Hold Space and describe your package
      </p>
      <p className="font-display text-base text-muted-foreground italic">
        Try “short videos, tech, two per contract for nine hundred, extra video
        three fifty, email first”
      </p>
      <Button
        type="button"
        variant="outline"
        disabled={locked}
        onClick={onStart}
      >
        Start from scratch
      </Button>
    </div>
  )
}

function Packages() {
  const api = useApi()

  const [phase, setPhase] = React.useState<Phase>("loading")
  const [packages, setPackages] = React.useState<MyPackage[]>([])
  // The niches a package may use: the creator's own.
  const [niches, setNiches] = React.useState<string[]>([])
  const [editor, setEditor] = React.useState<Editor | null>(null)

  // The latest editor for handlers that run between renders (voice commands arrive
  // one after another, each needing what the last one did).
  const editorRef = React.useRef<Editor | null>(null)
  const sessions = React.useRef(0)

  const commit = React.useCallback((next: Editor | null) => {
    editorRef.current = next
    setEditor(next)
  }, [])

  /** Changes the open editor. Does nothing when `session` is no longer the open one. */
  const change = React.useCallback(
    (changes: Partial<Editor>, session?: number) => {
      const current = editorRef.current
      if (!current || (session !== undefined && current.session !== session))
        return
      commit({ ...current, ...changes })
    },
    [commit]
  )

  /** The creator's niches and packages, or null when either cannot be had. */
  const fetchAll = React.useCallback(async () => {
    try {
      const [me, mine] = await Promise.all([
        api.GET("/api/v1/me"),
        api.GET("/api/v1/me/packages"),
      ])
      const creator = me.data?.creator
      if (!creator || !mine.data) return null
      return { niches: creator.niches, packages: mine.data }
    } catch {
      return null
    }
  }, [api])

  const show = React.useCallback(
    (found: Awaited<ReturnType<typeof fetchAll>>) => {
      if (!found) {
        setPhase("failed")
        return
      }
      setNiches(found.niches)
      setPackages(found.packages)
      setPhase("ready")
    },
    []
  )

  React.useEffect(() => {
    let live = true
    void fetchAll().then((found) => {
      if (live) show(found)
    })
    return () => {
      live = false
    }
  }, [fetchAll, show])

  const retry = () => {
    setPhase("loading")
    void fetchAll().then(show)
  }

  // Opening ------------------------------------------------------------------------

  const open = React.useCallback(
    (from: Pick<Editor, "id" | "status" | "draft" | "saved" | "floor">) => {
      commit({
        session: ++sessions.current,
        rejected: [],
        pending: null,
        ...from,
      })
    },
    [commit]
  )

  /** Another package may be opened only when it would not throw work away. */
  const mayLeave = React.useCallback(() => {
    const current = editorRef.current
    if (!current || !hasChanges(current)) return true
    toast.info("Save or close this draft first", { id: "packages-leave" })
    return false
  }, [])

  const startBlank = () => {
    if (!mayLeave()) return
    open({
      id: null,
      status: null,
      draft: emptyDraft(),
      saved: null,
      floor: null,
    })
  }

  const edit = (pkg: MyPackage) => {
    if (!mayLeave()) return
    const draft = draftFromPackage(pkg)
    open({
      id: pkg.id,
      status: pkg.status,
      draft,
      saved: draft,
      floor: pkg.floor_price_cents,
    })
  }

  // Voice --------------------------------------------------------------------------

  // What is said is a preview: it only fills the card. Saving is the creator's click.
  const hear = React.useCallback(
    (spoken: Partial<PackageDraft>) => {
      const draft = completeDraft(spoken)
      const current = editorRef.current
      if (current?.pending) {
        toast.info("Finish saving before changing the draft", {
          id: "packages-busy",
        })
        return
      }
      if (current) change({ draft, rejected: [] })
      else {
        open({ id: null, status: null, draft, saved: null, floor: null })
      }
    },
    [change, open]
  )

  useVoiceScreen(
    "packages",
    () => ({
      visible_creators: [],
      package_draft: editorRef.current?.draft ?? null,
    }),
    (spoken: VoiceIntent) => {
      if (spoken.kind === "package_draft" && spoken.package_draft) {
        hear(spoken.package_draft)
      }
    }
  )

  // Saving -------------------------------------------------------------------------

  /** Tells the creator why the server said no. */
  const refuse = React.useCallback(
    (
      session: number,
      response: { status: number },
      error: unknown,
      action: "save" | "publish" | "floor"
    ) => {
      const rejection = response.status === 422 ? rejectionFrom(error) : null
      if (rejection?.kind === "violations") {
        change({ rejected: rejection.violations }, session)
        toast.error(
          action === "publish"
            ? "Fix the highlighted fields to publish."
            : action === "floor"
              ? "That floor isn't allowed."
              : "Fix the highlighted fields, then save again.",
          { id: ERROR_ID }
        )
      } else if (rejection?.kind === "incomplete") {
        toast.error(
          `Still needed: ${rejection.missing.map(fieldLabel).join(", ")}`,
          { id: ERROR_ID }
        )
      } else if (response.status === 404) {
        toast.error("That package no longer exists.", { id: ERROR_ID })
      } else {
        toast.error(
          action === "publish"
            ? "Couldn't publish the package. Try again."
            : action === "floor"
              ? "Couldn't save the floor. Try again."
              : "Couldn't save the package. Try again.",
          { id: ERROR_ID }
        )
      }
    },
    [change]
  )

  /** Sends the open draft to the server as a new package or as changes to its package. */
  const persist = React.useCallback(
    async (current: Editor): Promise<Persisted | null> => {
      const body = draftBody(current.draft)
      try {
        const { data, error, response } =
          current.id === null
            ? await api.POST("/api/v1/me/packages", { body })
            : await api.PATCH("/api/v1/me/packages/{package_id}", {
                params: { path: { package_id: current.id } },
                body,
              })
        if (!data) {
          refuse(current.session, response, error, "save")
          return null
        }
        const draft = draftFromPackage(data)
        setPackages((list) => upsert(list, data))
        change(
          {
            id: data.id,
            status: data.status,
            draft,
            saved: draft,
            floor: data.floor_price_cents,
            rejected: [],
          },
          current.session
        )
        return data
      } catch {
        refuse(current.session, { status: 0 }, undefined, "save")
        return null
      }
    },
    [api, change, refuse]
  )

  const warn = (saved: Persisted | null) => {
    for (const warning of saved?.warnings ?? []) toast.warning(warning)
  }

  const save = async () => {
    const current = editorRef.current
    if (!current || current.pending) return
    change({ pending: "save" })
    const saved = await persist(current)
    change({ pending: null }, current.session)
    if (!saved) return
    toast.success(current.id === null ? "Draft saved" : "Changes saved")
    warn(saved)
  }

  const publish = async () => {
    const current = editorRef.current
    if (!current || current.pending) return
    change({ pending: "publish" })

    // The server publishes what it has, so anything it does not have goes first.
    let id = current.id
    if (id === null || hasChanges(current)) {
      const saved = await persist(current)
      if (!saved) {
        change({ pending: null }, current.session)
        return
      }
      id = saved.id
      warn(saved)
    }

    try {
      const { data, error, response } = await api.POST(
        "/api/v1/me/packages/{package_id}/publish",
        { params: { path: { package_id: id } } }
      )
      if (!data) {
        refuse(current.session, response, error, "publish")
        change({ pending: null }, current.session)
        return
      }
      setPackages((list) => upsert(list, data))
      toast.success("Published. Brands can find it now.")
      warn(data)
      // Done with this card: the list shows the result.
      if (editorRef.current?.session === current.session) commit(null)
    } catch {
      refuse(current.session, { status: 0 }, undefined, "publish")
      change({ pending: null }, current.session)
    }
  }

  const setFloor = async (cents: number) => {
    const current = editorRef.current
    if (!current || current.id === null || current.pending) return
    change({
      pending: "floor",
      rejected: current.rejected.filter((v) => v.field !== "floor_price_cents"),
    })
    try {
      const { data, error, response } = await api.PUT(
        "/api/v1/me/packages/{package_id}/floor",
        {
          params: { path: { package_id: current.id } },
          body: { floor_price_cents: cents },
        }
      )
      if (!data) {
        refuse(current.session, response, error, "floor")
        change({ pending: null }, current.session)
        return
      }
      setPackages((list) => upsert(list, data))
      change({ floor: data.floor_price_cents, pending: null }, current.session)
      toast.success("Floor saved. Only you can see it.")
    } catch {
      refuse(current.session, { status: 0 }, undefined, "floor")
      change({ pending: null }, current.session)
    }
  }

  // View ---------------------------------------------------------------------------

  const locked = editor?.pending != null
  const missing = editor ? missingFields(editor.draft) : []
  const violations = editor
    ? mergeViolations(draftViolations(editor.draft, niches), editor.rejected)
    : []

  return (
    <div className="flex flex-col gap-6">
      <header className="flex max-w-3xl flex-col gap-3 pt-2">
        <h1 className="font-display text-4xl leading-[1.05] tracking-tight sm:text-6xl">
          Your packages
        </h1>
        <p className="text-sm text-muted-foreground">
          What you sell and what it costs. Brands find you by these.
        </p>
      </header>

      {phase === "failed" ? (
        <ErrorState onRetry={retry} />
      ) : phase === "loading" ? (
        <div aria-busy>
          <Skeleton />
        </div>
      ) : (
        <div className="flex flex-col gap-6 lg:flex-row lg:items-start">
          <section aria-label="Your packages" className="min-w-0 flex-1">
            <div className="grid [grid-template-columns:repeat(auto-fill,minmax(min(100%,19rem),1fr))] gap-4">
              {packages.length === 0 ? (
                <p className="col-span-full text-sm text-muted-foreground">
                  No packages yet
                </p>
              ) : null}
              {packages.map((pkg) => (
                <PackageCard
                  key={pkg.id}
                  pkg={pkg}
                  open={editor?.id === pkg.id}
                  locked={locked}
                  onEdit={() => edit(pkg)}
                />
              ))}
              <NewPackageCard locked={locked} onStart={startBlank} />
            </div>
          </section>

          {editor ? (
            <div className="order-first w-full shrink-0 lg:sticky lg:top-6 lg:order-none lg:w-[34rem]">
              <PackageDraftCard
                key={editor.session}
                draft={editor.draft}
                missing={missing}
                violations={violations}
                niches={niches}
                status={editor.status}
                dirty={editor.saved === null || hasChanges(editor)}
                pending={editor.pending}
                floorCents={editor.floor}
                onChange={(draft) => change({ draft, rejected: [] })}
                onSave={() => void save()}
                onPublish={() => void publish()}
                onFloorSave={(cents) => void setFloor(cents)}
                onDiscard={() => commit(null)}
              />
            </div>
          ) : null}
        </div>
      )}
    </div>
  )
}

export default function PackagesPage() {
  return <Packages />
}
