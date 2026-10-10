"use client"

import { useGSAP } from "@gsap/react"
import gsap from "gsap"
import { Pencil, X } from "lucide-react"
import * as React from "react"

gsap.registerPlugin(useGSAP)

/** How long the chip stays up before it dismisses itself. */
export const HEARD_CHIP_MS = 6000

type HeardChipProps = {
  /** What the router understood, already cleaned of filler words. */
  heard: string
  /** For a command that was not understood: things to say instead. */
  suggestions?: string[]
  /** The chip was tapped: edit the text and send it again. */
  onEdit: (heard: string) => void
  /** A suggestion was tapped: send it as the command. */
  onSuggest: (suggestion: string) => void
  /** The chip is gone: dismissed, timed out or closed. */
  onDismiss: () => void
}

/**
 * "Heard: …" above the dock: proof that the screen reacted to what was said, with a
 * way to fix it. Stays {@link HEARD_CHIP_MS} unless the pointer or focus is on it.
 */
export function HeardChip({
  heard,
  suggestions = [],
  onEdit,
  onSuggest,
  onDismiss,
}: HeardChipProps) {
  const rootRef = React.useRef<HTMLDivElement>(null)
  const [held, setHeld] = React.useState(false)
  const leave = React.useRef<(() => void) | null>(null)
  const onDismissRef = React.useRef(onDismiss)

  React.useEffect(() => {
    onDismissRef.current = onDismiss
  })

  // Fades in on mount. `leave` is how the chip goes away: it fades out, then reports.
  useGSAP(
    (_, contextSafe) => {
      const mm = gsap.matchMedia()
      mm.add(
        {
          motion: "(prefers-reduced-motion: no-preference)",
          reduce: "(prefers-reduced-motion: reduce)",
        },
        (context) => {
          if (context.conditions?.reduce) return
          gsap.from(rootRef.current, {
            opacity: 0,
            y: 8,
            duration: 0.25,
            ease: "power2.out",
          })
          leave.current = contextSafe!(() => {
            gsap.to(rootRef.current, {
              opacity: 0,
              y: 8,
              duration: 0.2,
              ease: "power1.in",
              onComplete: () => onDismissRef.current(),
            })
          })
        }
      )
      return () => mm.revert()
    },
    { scope: rootRef }
  )

  const dismiss = React.useCallback(() => {
    // Without motion there is nothing to wait for. Either way, once only.
    const run = leave.current ?? (() => onDismissRef.current())
    leave.current = () => {}
    run()
  }, [])

  React.useEffect(() => {
    if (held) return
    const timer = setTimeout(dismiss, HEARD_CHIP_MS)
    return () => clearTimeout(timer)
  }, [held, dismiss])

  return (
    <div
      ref={rootRef}
      role="status"
      data-slot="heard-chip"
      onPointerEnter={() => setHeld(true)}
      onPointerLeave={() => setHeld(false)}
      onFocus={() => setHeld(true)}
      onBlur={() => setHeld(false)}
      className="flex max-w-[min(32rem,calc(100vw-var(--rail-width)-2rem))] flex-col gap-1.5 rounded-2xl border border-voice/40 bg-card/80 py-1.5 pr-1.5 pl-3 text-sm shadow-sm backdrop-blur-[16px]"
    >
      <div className="flex items-center gap-1">
        <button
          type="button"
          data-voice-passthrough
          onClick={() => onEdit(heard)}
          aria-label={`Heard: ${heard}. Edit and resend`}
          className="group flex min-w-0 items-center gap-2 rounded-lg py-1 text-left outline-none focus-visible:ring-3 focus-visible:ring-ring/50"
        >
          <span className="shrink-0 font-medium text-voice-ink">Heard:</span>
          <span className="min-w-0 truncate text-foreground">{heard}</span>
          <Pencil
            aria-hidden
            className="size-3.5 shrink-0 text-muted-foreground group-hover:text-foreground"
          />
        </button>
        <button
          type="button"
          data-voice-passthrough
          onClick={dismiss}
          aria-label="Dismiss"
          className="ml-auto flex size-7 shrink-0 items-center justify-center rounded-full text-muted-foreground outline-none hover:bg-muted hover:text-foreground focus-visible:ring-3 focus-visible:ring-ring/50"
        >
          <X aria-hidden className="size-3.5" />
        </button>
      </div>

      {suggestions.length > 0 ? (
        <div className="flex flex-col gap-1 pr-1.5 pb-1">
          <p className="text-xs text-muted-foreground">Try saying</p>
          <ul className="flex flex-wrap gap-1.5">
            {suggestions.map((suggestion) => (
              <li key={suggestion}>
                <button
                  type="button"
                  data-voice-passthrough
                  onClick={() => onSuggest(suggestion)}
                  className="rounded-full border border-border bg-background/60 px-2.5 py-1 text-xs text-foreground outline-none hover:bg-muted focus-visible:ring-3 focus-visible:ring-ring/50"
                >
                  {suggestion}
                </button>
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </div>
  )
}
