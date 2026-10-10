"use client"

import { useGSAP } from "@gsap/react"
import gsap from "gsap"
import * as React from "react"

gsap.registerPlugin(useGSAP)

const PREVIEW_CHARS = 320
const DURATION_S = 1.2

export function EmailReveal({
  text,
  animate,
}: {
  text: string
  /** When true, typewriter once; when false, show the full preview immediately. */
  animate: boolean
}) {
  const preview = text.slice(0, PREVIEW_CHARS)
  const [shown, setShown] = React.useState(animate ? "" : preview)
  const rootRef = React.useRef<HTMLParagraphElement>(null)

  useGSAP(
    () => {
      if (!animate || !rootRef.current) {
        setShown(preview)
        return
      }
      const state = { n: 0 }
      const mm = gsap.matchMedia()
      mm.add("(prefers-reduced-motion: reduce)", () => {
        setShown(preview)
      })
      mm.add("(prefers-reduced-motion: no-preference)", () => {
        gsap.to(state, {
          n: preview.length,
          duration: DURATION_S,
          ease: "none",
          onUpdate: () => {
            setShown(preview.slice(0, Math.round(state.n)))
          },
        })
      })
      return () => mm.revert()
    },
    { dependencies: [animate, preview], scope: rootRef }
  )

  return (
    <p
      ref={rootRef}
      className="text-sm leading-relaxed text-muted-foreground whitespace-pre-wrap"
    >
      {shown}
      {preview.length < text.length ? "…" : null}
    </p>
  )
}
