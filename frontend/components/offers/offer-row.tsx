import { StatusPill } from "@/components/board/status-pill"
import { ExpiryBadge } from "@/components/deal/expiry-badge"
import { DELTA_FLAG_LABEL, type OfferListItem } from "@/lib/deal/offers"
import { formatCents } from "@/lib/money"

type OfferRowProps = {
  offer: OfferListItem
  now: Date
  /** Called for a plain click; a modified click is left to the browser (new tab). */
  onOpen: (threadId: string) => void
  href: string
}

/**
 * One offer in the inbox: the brand and product, the package it is closest to, how the
 * ask differs from it, what it is worth and when it lapses. The whole row opens the
 * offer desk, and is a real link so it can be opened in a new tab.
 */
export function OfferRow({ offer, now, onOpen, href }: OfferRowProps) {
  return (
    <li>
      <a
        href={href}
        data-slot="offer-row"
        onClick={(event) => {
          if (
            event.defaultPrevented ||
            event.button !== 0 ||
            event.metaKey ||
            event.ctrlKey ||
            event.shiftKey ||
            event.altKey
          )
            return
          event.preventDefault()
          onOpen(offer.thread_id)
        }}
        className="grid gap-x-6 gap-y-2 rounded-xl border bg-card px-4 py-3 text-card-foreground outline-none transition-colors hover:bg-muted/40 focus-visible:ring-3 focus-visible:ring-ring/50 sm:grid-cols-[minmax(0,1.2fr)_minmax(0,1.6fr)_auto] sm:items-center"
      >
        <span className="flex min-w-0 flex-col">
          <span className="truncate font-medium">{offer.brand.name}</span>
          <span className="truncate text-sm text-muted-foreground">
            {offer.product_name}
          </span>
        </span>

        <span className="flex min-w-0 flex-col gap-1">
          <span className="truncate text-sm">
            <span className="text-muted-foreground">Closest to </span>
            <span>{offer.package.name}</span>
          </span>
          <span className="text-sm">{offer.delta_headline}</span>
          {offer.delta_flags.length > 0 ? (
            <span className="flex flex-wrap gap-1.5">
              {offer.delta_flags.map((flag) => (
                <span
                  key={flag}
                  className="rounded-full bg-amber-500/15 px-2 py-0.5 text-[0.6875rem] font-medium text-amber-800 dark:text-amber-300"
                >
                  {DELTA_FLAG_LABEL[flag]}
                </span>
              ))}
            </span>
          ) : null}
        </span>

        <span className="flex flex-wrap items-center gap-2 sm:justify-end">
          <span className="num font-medium">
            {formatCents(offer.total_value_cents)}
          </span>
          <StatusPill status={offer.status} />
          <ExpiryBadge expiresAt={offer.expires_at} now={now} />
        </span>
      </a>
    </li>
  )
}
