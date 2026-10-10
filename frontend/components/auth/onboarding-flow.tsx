"use client"

import { useTheme } from "next-themes"
import { useEffect, useId, useRef, useState } from "react"
import {
  ArrowRight,
  Clapperboard,
  ShoppingBag,
  type LucideIcon,
} from "lucide-react"

import { BrandForm, CreatorForm } from "@/components/auth/onboarding-forms"
import BlurText from "@/components/ui/blur-text"
import SpotlightCard from "@/components/ui/spotlight-card"
import type { Role } from "@/lib/auth/routing"

type Choice = {
  role: Role
  title: string
  body: string
  cta: string
  icon: LucideIcon
}

const CHOICES: readonly Choice[] = [
  {
    role: "brand",
    title: "I sell products",
    body: "Find creators by niche, hear what they offer, and close a collaboration by voice.",
    cta: "Set up as a brand",
    icon: ShoppingBag,
  },
  {
    role: "creator",
    title: "I create content",
    body: "Say your packages and prices out loud, and let brands come to you with offers.",
    cta: "Set up as a creator",
    icon: Clapperboard,
  },
]

// The card sits on the page tokens in both themes; the component's own palette is a
// fixed light/dark pair that would not match the warm paper and ink.
const CARD_SURFACE = {
  "--spotlight-card-surface": "var(--card)",
  "--spotlight-card-border": "var(--border)",
  "--spotlight-card-shadow":
    "0 1px 2px rgb(0 0 0 / 0.05), 0 18px 40px -22px rgb(0 0 0 / 0.28)",
} as React.CSSProperties

function RoleCard({
  choice,
  onChoose,
}: {
  choice: Choice
  onChoose: (role: Role) => void
}) {
  const { resolvedTheme } = useTheme()
  const bodyId = useId()
  const Icon = choice.icon

  return (
    <SpotlightCard
      // The spotlight is ink on paper in light mode and paper on ink in dark mode.
      theme={resolvedTheme === "dark" ? "dark" : "light"}
      spotlightColor="var(--foreground)"
      spotlightSize={280}
      style={CARD_SURFACE}
      className="group flex min-h-64 flex-col"
    >
      <span className="flex size-11 items-center justify-center rounded-xl bg-muted text-foreground">
        <Icon aria-hidden className="size-5" />
      </span>

      <h2 className="mt-8 font-display text-3xl leading-tight">
        {/* The button's ::after stretches over the card, so all of it is the target. The
            card clips overflow, hence an inset focus ring. */}
        <button
          type="button"
          aria-describedby={bodyId}
          onClick={() => onChoose(choice.role)}
          className="text-left outline-none after:absolute after:inset-0 after:z-[2] after:rounded-3xl focus-visible:after:ring-3 focus-visible:after:ring-ring focus-visible:after:ring-inset"
        >
          {choice.title}
        </button>
      </h2>
      <p id={bodyId} className="mt-2 text-sm text-muted-foreground">
        {choice.body}
      </p>

      <span
        aria-hidden
        className="mt-auto inline-flex items-center gap-1.5 pt-8 text-sm font-medium"
      >
        {choice.cta}
        <ArrowRight className="size-4 transition-transform group-hover:translate-x-0.5" />
      </span>
    </SpotlightCard>
  )
}

function RoleChoice({
  onChoose,
  focusHeading,
}: {
  onChoose: (role: Role) => void
  /** Move focus to the heading, after the user came back from a form. */
  focusHeading: boolean
}) {
  const headingRef = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (focusHeading) headingRef.current?.focus()
  }, [focusHeading])

  return (
    <section className="w-full max-w-3xl">
      {/* BlurText renders a <p>, so the heading semantics live on its wrapper. */}
      <div
        ref={headingRef}
        role="heading"
        aria-level={1}
        tabIndex={-1}
        className="outline-none"
      >
        <BlurText
          text="How will you use Collabio?"
          animateBy="words"
          direction="bottom"
          delay={110}
          className="justify-center text-center font-display text-4xl leading-[1.05] sm:text-6xl"
        />
      </div>
      <p className="mt-4 text-center text-muted-foreground">
        Pick one. It sets up your workspace, and it can&apos;t be changed later.
      </p>

      <div className="mt-10 grid gap-5 sm:grid-cols-2">
        {CHOICES.map((choice) => (
          <RoleCard key={choice.role} choice={choice} onChoose={onChoose} />
        ))}
      </div>
    </section>
  )
}

/** Step 1: brand or creator. Step 2: a short form for that role. */
export function OnboardingFlow() {
  const [role, setRole] = useState<Role | null>(null)
  const [hasChosen, setHasChosen] = useState(false)

  function choose(next: Role) {
    setRole(next)
    setHasChosen(true)
  }

  if (role === "brand") return <BrandForm onBack={() => setRole(null)} />
  if (role === "creator") return <CreatorForm onBack={() => setRole(null)} />
  return <RoleChoice onChoose={choose} focusHeading={hasChosen} />
}
