"use client"

import { Mail, Phone } from "lucide-react"
import Link from "next/link"

import ShinyText from "@/components/ShinyText"
import { EmailReveal } from "@/components/board/email-reveal"
import { StatusPill } from "@/components/board/status-pill"
import { ExpiryBadge } from "@/components/deal/expiry-badge"
import { Button } from "@/components/ui/button"
import type { components } from "@/lib/api/schema"
import { lastEventLine, termsLine } from "@/lib/board/state"
import { formatCents } from "@/lib/money"
import { cn } from "@/lib/utils"

type ThreadCard = components["schemas"]["ThreadCard"]

function offerLine(terms: components["schemas"]["NegotiationTerms"]): string {
  const price =
    terms.price_cents != null ? formatCents(terms.price_cents) : "—"
  const videos = terms.videos != null ? `${terms.videos} videos` : "—"
  return `${price} · ${videos} — creator`
}

export function ThreadCardView({
  thread,
  onOpen,
  onRetry,
  revealEmail,
  now,
}: {
  thread: ThreadCard
  onOpen: () => void
  onRetry: (id: string) => void
  revealEmail: boolean
  now: Date
}) {
  const deltaLine =
    thread.delta.latest_headline ?? thread.delta.headline
  const deltaTone =
    thread.delta.latest_price_cents != null &&
    thread.delta.latest_price_cents < thread.delta.ask_price_cents
      ? "text-emerald-600 dark:text-emerald-400"
      : thread.delta.latest_price_cents != null &&
          thread.delta.latest_price_cents > thread.delta.ask_price_cents
        ? "text-amber-700 dark:text-amber-300"
        : "text-muted-foreground"

  const ChannelIcon =
    thread.channel_plan === "call" ? Phone : Mail

  const showBest =
    thread.best_value?.eligible && thread.best_value.rank === 1

  return (
    <article
      data-flip-id={thread.id}
      className="flex flex-col gap-3 rounded-xl border bg-card p-4 shadow-sm"
    >
      <button
        type="button"
        onClick={onOpen}
        className="flex flex-col gap-3 text-left outline-none focus-visible:ring-3 focus-visible:ring-ring/50 rounded-lg -m-1 p-1"
      >
        <div className="flex items-start justify-between gap-2">
          <div className="flex items-center gap-2 min-w-0">
            {thread.status !== "in_call" ? (
              <StatusPill status={thread.status} />
            ) : null}
            <ChannelIcon
              className="size-4 shrink-0 text-muted-foreground"
              aria-hidden
            />
            <span className="truncate font-medium">{thread.creator.name}</span>
          </div>
          {showBest ? (
            <div className="flex flex-col items-end gap-1">
              <ShinyText
                className="text-xs font-semibold uppercase tracking-wide"
                speed={2}
              >
                Best value
              </ShinyText>
              <div className="flex flex-wrap justify-end gap-1">
                {thread.best_value?.reasons.map((reason) => (
                  <span
                    key={reason}
                    className="rounded-full bg-muted px-1.5 py-0.5 text-[0.625rem] text-muted-foreground"
                  >
                    {reason}
                  </span>
                ))}
              </div>
            </div>
          ) : null}
        </div>

        <div className="space-y-1 text-sm">
          <p className="num tabular-nums">{termsLine(thread.latest_terms)}</p>
          <p className={cn("text-sm", deltaTone)}>{deltaLine}</p>
          <p className="text-muted-foreground text-xs">
            {lastEventLine(thread.last_event, now)}
          </p>
          {thread.status === "awaiting_reply" ? (
            <ExpiryBadge expiresAt={thread.expires_at} now={now} />
          ) : null}
        </div>

        {thread.status === "calling" ? (
          <p className="flex items-center gap-2 text-sm text-voice">
            <span
              className="size-2 animate-pulse rounded-full bg-voice"
              aria-hidden
            />
            Calling…
          </p>
        ) : null}

        {thread.status === "in_call" ? (
          <div className="space-y-1 text-sm" aria-label="In call">
            <p className="flex items-center gap-2 font-medium text-destructive">
              <span
                className="size-2 rounded-full bg-destructive"
                aria-hidden
              />
              In call
            </p>
            {thread.live_offers.map((offer, i) => (
              <p key={i} className="num text-xs text-muted-foreground">
                {offerLine(offer)}
              </p>
            ))}
          </div>
        ) : null}

        {thread.email ? (
          <div className="rounded-lg border bg-muted/30 p-3">
            <p className="text-xs font-medium text-muted-foreground mb-1">
              {thread.email.subject}
            </p>
            <EmailReveal text={thread.email.body_text} animate={revealEmail} />
            {thread.email.delivered === false ? (
              <p className="mt-2 text-xs text-amber-700 dark:text-amber-300">
                Not delivered: test address
              </p>
            ) : null}
          </div>
        ) : null}
      </button>

      {thread.status === "awarded" && thread.deal_id ? (
        <div className="border-t pt-3">
          <Link
            href={`/brand/deals/${thread.deal_id}`}
            className="text-sm font-medium underline underline-offset-4"
          >
            View deal
          </Link>
        </div>
      ) : null}

      {thread.status === "failed" ? (
        <div className="flex flex-col gap-2 border-t pt-3">
          {thread.last_error ? (
            <p className="text-sm text-destructive">{thread.last_error}</p>
          ) : null}
          <Button
            type="button"
            size="sm"
            variant="outline"
            onClick={() => onRetry(thread.id)}
          >
            Retry
          </Button>
        </div>
      ) : null}
    </article>
  )
}
