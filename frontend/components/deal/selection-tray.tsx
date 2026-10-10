"use client"

import { useGSAP } from "@gsap/react"
import gsap from "gsap"
import Link from "next/link"
import * as React from "react"

import { CreatorAvatar } from "@/components/deal/creator-avatar"
import { buttonVariants } from "@/components/ui/button"
import type { CreatorCard } from "@/lib/discover/state"
import { cn } from "@/lib/utils"

gsap.registerPlugin(useGSAP)

/** A creator in the batch. `creator` is missing when only the id is known. */
export type TrayItem = { id: string; creator: CreatorCard | undefined }

type SelectionTrayProps = {
  items: TrayItem[]
  /** Where "Review" goes. */
  reviewHref: string
  onClear: () => void
}

function TrayBar({ items, reviewHref, onClear }: SelectionTrayProps) {
  const rootRef = React.useRef<HTMLDivElement>(null)

  // Slides up from below the Dock the moment the first creator is picked. With
  // reduced motion it is simply there.
  useGSAP(
    () => {
      const mm = gsap.matchMedia()
      mm.add("(prefers-reduced-motion: no-preference)", () => {
        gsap.from(rootRef.current, {
          y: 48,
          autoAlpha: 0,
          duration: 0.45,
          ease: "power3.out",
        })
      })
      return () => mm.revert()
    },
    { scope: rootRef }
  )

  return (
    <div
      ref={rootRef}
      role="region"
      aria-label="Selected creators"
      data-slot="selection-tray"
      // Above the Dock and the "Heard" chip that stands over it.
      className="pointer-events-none fixed inset-x-0 bottom-32 z-30 flex justify-center pr-4 pl-[calc(var(--rail-width)+1rem)]"
    >
      <div className="pointer-events-auto flex max-w-full items-center gap-3 rounded-full border bg-card/85 py-2 pr-2 pl-3 shadow-lg backdrop-blur-[16px]">
        <ul aria-hidden className="flex items-center -space-x-2">
          {items.map(({ id, creator }) => (
            <li key={id}>
              {creator ? (
                <CreatorAvatar
                  size="sm"
                  initials={creator.initials}
                  niches={creator.niches}
                  className="bg-card"
                />
              ) : (
                <span className="block size-8 rounded-full border-2 border-card bg-muted" />
              )}
            </li>
          ))}
        </ul>

        <p className="shrink-0 text-sm font-medium whitespace-nowrap">
          <span className="num">{items.length}</span> selected
        </p>

        <button
          type="button"
          onClick={onClear}
          className="shrink-0 rounded-full px-2 py-1 text-sm text-muted-foreground outline-none hover:text-foreground focus-visible:ring-3 focus-visible:ring-ring/50"
        >
          Clear
        </button>

        <Link
          href={reviewHref}
          className={cn(
            buttonVariants({ size: "lg" }),
            "shrink-0 rounded-full px-4"
          )}
        >
          Review <span aria-hidden>→</span>
        </Link>
      </div>
    </div>
  )
}

/**
 * The batch so far, floating above the Dock: who is in it, how many, and the way to
 * Review. It exists only while something is selected.
 */
export function SelectionTray(props: SelectionTrayProps) {
  if (props.items.length === 0) return null
  return <TrayBar {...props} />
}
