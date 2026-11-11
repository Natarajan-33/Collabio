import Link from "next/link"
import { BadgeCheck, CircleDollarSign, ScanEye, Undo2 } from "lucide-react"

import { JudgeGuide } from "@/components/landing/judge-guide"
import { PERSONAS } from "@/lib/hackathon"

const STEPS = [
  {
    icon: CircleDollarSign,
    title: "Brand funds the deal",
    body: "The agreed price plus a performance bonus is paid in through PayPal Checkout.",
  },
  {
    icon: ScanEye,
    title: "Creator posts proof",
    body: "Post link, caption and an analytics screenshot for each video.",
  },
  {
    icon: BadgeCheck,
    title: "Claude verifies and pays",
    body: "Checks the brief, reads the views, computes what is owed and sends a PayPal payout.",
  },
  {
    icon: Undo2,
    title: "Unspent budget returns",
    body: "Closing the deal refunds whatever the creator did not earn.",
  },
] as const

/** The public landing in hackathon mode: what Collabio does and two one-click personas. */
export function HackathonLanding({ unavailable }: { unavailable: boolean }) {
  return (
    <div className="relative min-h-svh overflow-hidden bg-background text-foreground">
      <div
        aria-hidden
        className="pointer-events-none absolute inset-x-0 top-0 h-136 bg-[radial-gradient(56rem_24rem_at_50%_-6rem,color-mix(in_oklch,var(--voice)_20%,transparent),transparent_72%)]"
      />
      <header className="relative flex items-center justify-between px-6 pt-6 sm:px-10">
        <span className="inline-flex items-center gap-2.5">
          <span
            aria-hidden
            className="flex size-9 items-center justify-center rounded-lg bg-foreground font-display text-2xl leading-none text-background italic"
          >
            C
          </span>
          <span className="font-display text-2xl leading-none">Collabio</span>
        </span>
        <JudgeGuide />
      </header>

      <main id="main" className="relative mx-auto max-w-5xl px-6 pt-16 pb-20 sm:pt-24">
        <p className="text-xs font-medium tracking-[0.18em] text-voice-ink uppercase">
          Voice-negotiated creator deals · paid out by an AI agent on PayPal
        </p>
        <h1 className="mt-4 max-w-3xl font-display text-5xl leading-[1.05] sm:text-6xl">
          Creators get paid the moment the work is proven.
        </h1>
        <p className="mt-5 max-w-2xl text-lg text-muted-foreground">
          Brands negotiate sponsorships with creators by voice. Collabio holds the budget,
          and a Claude agent checks each delivered video against the brief and the agreed
          view bonuses, then pays the creator through PayPal. No spreadsheets, no chasing
          invoices.
        </p>

        {unavailable && (
          <p role="alert" className="mt-6 text-sm text-destructive">
            The demo accounts are not reachable right now. Please try again in a minute.
          </p>
        )}

        <div className="mt-9 flex flex-col gap-3 sm:flex-row">
          <Link
            href="/api/demo-login?as=brand"
            prefetch={false}
            className="inline-flex h-12 items-center justify-center rounded-xl bg-foreground px-6 text-base font-medium text-background outline-none hover:opacity-90 focus-visible:ring-3 focus-visible:ring-ring/50"
          >
            {PERSONAS.brand.label}
          </Link>
          <Link
            href="/api/demo-login?as=creator"
            prefetch={false}
            className="inline-flex h-12 items-center justify-center rounded-xl border border-border px-6 text-base font-medium outline-none hover:bg-muted focus-visible:ring-3 focus-visible:ring-ring/50"
          >
            {PERSONAS.creator.label}
          </Link>
        </div>
        <p className="mt-3 text-sm text-muted-foreground">
          No sign-up. Switch personas any time from the app menu.
        </p>

        <section aria-labelledby="how-money-moves" className="mt-20">
          <h2 id="how-money-moves" className="font-display text-2xl">
            How money moves
          </h2>
          <ol className="mt-6 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            {STEPS.map(({ icon: Icon, title, body }, i) => (
              <li key={title} className="rounded-2xl border border-border bg-card/60 p-5">
                <div className="flex items-center gap-2 text-sm text-muted-foreground">
                  <span className="num">{i + 1}</span>
                  <Icon className="size-4 text-voice" aria-hidden />
                </div>
                <p className="mt-3 font-medium">{title}</p>
                <p className="mt-1 text-sm text-muted-foreground">{body}</p>
              </li>
            ))}
          </ol>
        </section>
      </main>
    </div>
  )
}
