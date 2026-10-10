"use client"

import Link from "next/link"
import { useRouter } from "next/navigation"
import { useEffect, useId, useRef, useState } from "react"
import { ArrowLeft, LoaderCircle } from "lucide-react"

import { ChipGroup } from "@/components/auth/chip-group"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { NativeSelect } from "@/components/ui/native-select"
import { useApi } from "@/hooks/use-api"
import type { components } from "@/lib/api/schema"
import { roleHome } from "@/lib/auth/routing"
import { asRegion, NICHES, REGIONS, type Niche, type Region } from "@/lib/vocab"

type OnboardingBody =
  | components["schemas"]["BrandOnboarding"]
  | components["schemas"]["CreatorOnboarding"]

type Failure =
  "role_locked" | "handle_taken" | "unreachable" | "invalid" | "failed"

/** The `detail` code on a 409 from `POST /onboarding`, or null for anything else. */
function conflictCode(error: unknown): "role_locked" | "handle_taken" | null {
  const detail = (error as { detail?: unknown } | null | undefined)?.detail
  return detail === "role_locked" || detail === "handle_taken" ? detail : null
}

/** Posts the onboarding answers, then lands the user in their app. */
function useOnboard() {
  const api = useApi()
  const router = useRouter()
  const [pending, setPending] = useState(false)
  const [failure, setFailure] = useState<Failure | null>(null)

  async function submit(body: OnboardingBody) {
    if (pending) return
    setPending(true)
    setFailure(null)

    try {
      const { response, error } = await api.POST("/api/v1/onboarding", {
        body,
      })
      if (response.ok) {
        // Stay locked while the app navigates away. The refresh drops any cached
        // pages from before the role existed.
        router.replace(roleHome(body.role))
        router.refresh()
        return
      }
      if (response.status === 409) {
        setFailure(conflictCode(error) ?? "failed")
      } else if (response.status === 422) {
        setFailure("invalid")
      } else {
        setFailure("failed")
      }
    } catch {
      setFailure("unreachable")
    }
    setPending(false)
  }

  return { pending, failure, submit, clearFailure: () => setFailure(null) }
}

function FailureNotice({ failure }: { failure: Failure | null }) {
  if (!failure || failure === "handle_taken") return null

  return (
    <p role="alert" className="text-sm text-destructive">
      {failure === "role_locked" ? (
        <>
          This account is already set up with a different role, and a role can
          not be changed once chosen.{" "}
          <Link href="/" className="font-medium underline underline-offset-4">
            Go to your workspace
          </Link>
        </>
      ) : failure === "unreachable" ? (
        "We can't reach Collabio right now. Check your connection and try again."
      ) : failure === "invalid" ? (
        "Some answers were not accepted. Check them and try again."
      ) : (
        "Something went wrong. Try again."
      )}
    </p>
  )
}

/** The heading takes focus when a step opens, so a screen reader announces it. */
function useFocusOnMount<T extends HTMLElement>() {
  const ref = useRef<T>(null)
  useEffect(() => ref.current?.focus(), [])
  return ref
}

type FormShellProps = {
  title: string
  lede: string
  onBack: () => void
  onSubmit: () => void
  canSubmit: boolean
  pending: boolean
  failure: Failure | null
  children: React.ReactNode
}

function FormShell({
  title,
  lede,
  onBack,
  onSubmit,
  canSubmit,
  pending,
  failure,
  children,
}: FormShellProps) {
  const headingRef = useFocusOnMount<HTMLHeadingElement>()

  return (
    <section className="w-full max-w-xl animate-in duration-500 fade-in slide-in-from-bottom-2">
      <Button
        type="button"
        variant="ghost"
        size="sm"
        onClick={onBack}
        disabled={pending}
        className="-ml-2"
      >
        <ArrowLeft aria-hidden />
        Change role
      </Button>
      <h1
        ref={headingRef}
        tabIndex={-1}
        className="mt-5 font-display text-4xl leading-[1.04] outline-none sm:text-5xl"
      >
        {title}
      </h1>
      <p className="mt-3 text-muted-foreground">{lede}</p>

      <form
        className="mt-8 space-y-6"
        onSubmit={(event) => {
          event.preventDefault()
          if (canSubmit) onSubmit()
        }}
      >
        {children}
        <FailureNotice failure={failure} />
        <Button
          type="submit"
          size="lg"
          disabled={!canSubmit || pending}
          className="h-10 w-full text-sm"
        >
          {pending ? (
            <>
              <LoaderCircle aria-hidden className="animate-spin" />
              Setting up…
            </>
          ) : (
            "Finish setup"
          )}
        </Button>
      </form>
    </section>
  )
}

/** The text that names a chip group (a `Label` is only for a single control). */
function GroupLabel({
  id,
  children,
  hint,
}: {
  id: string
  children: React.ReactNode
  hint?: string
}) {
  return (
    <div className="mb-2.5 flex items-baseline justify-between gap-3">
      <p id={id} className="text-sm leading-none font-medium">
        {children}
      </p>
      {hint ? <p className="text-xs text-muted-foreground">{hint}</p> : null}
    </div>
  )
}

export function BrandForm({ onBack }: { onBack: () => void }) {
  const { pending, failure, submit } = useOnboard()
  const ids = {
    company: useId(),
    category: useId(),
    product: useId(),
    summary: useId(),
  }
  const [company, setCompany] = useState("")
  const [category, setCategory] = useState<Niche | null>(null)
  const [product, setProduct] = useState("")
  const [summary, setSummary] = useState("")

  const companyName = company.trim()
  const canSubmit =
    companyName !== "" &&
    category !== null &&
    product.trim() !== "" &&
    summary.trim() !== ""

  return (
    <FormShell
      title="Tell us about your brand"
      lede="Creators will see this when you reach out."
      onBack={onBack}
      canSubmit={canSubmit}
      pending={pending}
      failure={failure}
      onSubmit={() => {
        if (category === null) return
        void submit({
          role: "brand",
          // A brand account is known by its company.
          display_name: companyName,
          company_name: companyName,
          category,
          product_name: product.trim(),
          product_summary: summary.trim(),
        })
      }}
    >
      <div className="space-y-2">
        <Label htmlFor={ids.company}>Company</Label>
        <Input
          id={ids.company}
          value={company}
          onChange={(event) => setCompany(event.target.value)}
          maxLength={100}
          autoComplete="organization"
          className="h-10"
        />
      </div>

      <div>
        <GroupLabel id={ids.category}>Category</GroupLabel>
        <ChipGroup
          labelledBy={ids.category}
          options={NICHES}
          value={category ? [category] : []}
          onValueChange={(next) => setCategory(next[0] ?? null)}
        />
      </div>

      <div className="space-y-2">
        <Label htmlFor={ids.product}>Product name</Label>
        <Input
          id={ids.product}
          value={product}
          onChange={(event) => setProduct(event.target.value)}
          maxLength={100}
          className="h-10"
        />
      </div>

      <div className="space-y-2">
        <div className="flex items-baseline justify-between gap-3">
          <Label htmlFor={ids.summary}>One-line summary</Label>
          <span aria-hidden className="num text-xs text-muted-foreground">
            {summary.length}/200
          </span>
        </div>
        <Input
          id={ids.summary}
          value={summary}
          onChange={(event) => setSummary(event.target.value)}
          maxLength={200}
          className="h-10"
        />
      </div>
    </FormShell>
  )
}

/** Handles are lowercase letters, digits, dots, dashes and underscores, 2 to 30 long. */
function cleanHandle(raw: string): string {
  return raw.toLowerCase().replace(/[^a-z0-9._-]/g, "")
}

export function CreatorForm({ onBack }: { onBack: () => void }) {
  const { pending, failure, submit, clearFailure } = useOnboard()
  const ids = {
    name: useId(),
    handle: useId(),
    handleNote: useId(),
    niches: useId(),
    region: useId(),
  }
  const [name, setName] = useState("")
  const [handle, setHandle] = useState("")
  const [niches, setNiches] = useState<Niche[]>([])
  const [region, setRegion] = useState<Region | null>(null)

  const handleTaken = failure === "handle_taken"
  const canSubmit =
    name.trim() !== "" &&
    handle.length >= 2 &&
    niches.length > 0 &&
    region !== null

  return (
    <FormShell
      title="Set up your creator profile"
      lede="Brands find you by niche and region."
      onBack={onBack}
      canSubmit={canSubmit}
      pending={pending}
      failure={failure}
      onSubmit={() => {
        if (region === null) return
        void submit({
          role: "creator",
          display_name: name.trim(),
          handle,
          // Vocabulary order, whatever order the chips were pressed in.
          niches: NICHES.filter((n) => niches.includes(n.value)).map(
            (n) => n.value
          ),
          region,
        })
      }}
    >
      <div className="space-y-2">
        <Label htmlFor={ids.name}>Your name</Label>
        <Input
          id={ids.name}
          value={name}
          onChange={(event) => setName(event.target.value)}
          maxLength={100}
          autoComplete="name"
          className="h-10"
        />
      </div>

      <div className="space-y-2">
        <Label htmlFor={ids.handle}>Handle</Label>
        <div className="relative">
          <span
            aria-hidden
            className="pointer-events-none absolute top-1/2 left-3 -translate-y-1/2 text-muted-foreground"
          >
            @
          </span>
          <Input
            id={ids.handle}
            value={handle}
            onChange={(event) => {
              setHandle(cleanHandle(event.target.value))
              if (handleTaken) clearFailure()
            }}
            maxLength={30}
            autoCapitalize="none"
            autoCorrect="off"
            spellCheck={false}
            aria-invalid={handleTaken ? true : undefined}
            aria-describedby={ids.handleNote}
            className="h-10 pl-7"
          />
        </div>
        {handleTaken ? (
          <p
            id={ids.handleNote}
            role="alert"
            className="text-sm text-destructive"
          >
            @{handle} is taken. Try another handle.
          </p>
        ) : (
          <p id={ids.handleNote} className="text-xs text-muted-foreground">
            Letters, numbers, dots, dashes and underscores.
          </p>
        )}
      </div>

      <div>
        <GroupLabel id={ids.niches} hint="Pick at least one">
          Your niches
        </GroupLabel>
        <ChipGroup
          multiple
          labelledBy={ids.niches}
          options={NICHES}
          value={niches}
          onValueChange={setNiches}
        />
      </div>

      <div className="space-y-2">
        <Label htmlFor={ids.region}>Region</Label>
        <NativeSelect
          id={ids.region}
          value={region ?? ""}
          onChange={(event) => setRegion(asRegion(event.target.value))}
          className="h-10"
        >
          <option value="" disabled>
            Choose your region
          </option>
          {REGIONS.map((r) => (
            <option key={r.value} value={r.value}>
              {r.label}
            </option>
          ))}
        </NativeSelect>
      </div>
    </FormShell>
  )
}
