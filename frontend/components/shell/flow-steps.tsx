"use client"

import Link from "next/link"
import { usePathname } from "next/navigation"
import { ChevronRight } from "lucide-react"

import { flowFor, type FlowRole } from "@/lib/flow"
import { cn } from "@/lib/utils"

/** "You are here" strip: the steps of the flow, the current one, and what this page is for. */
export function FlowSteps({ role }: { role: FlowRole }) {
  const pathname = usePathname()
  const { steps, hint } = flowFor(role, pathname)
  if (!hint) return null
  return (
    <nav
      aria-label="How it works"
      className="mb-6 rounded-xl border border-border bg-card/60 px-4 py-3"
    >
      <ol className="flex flex-wrap items-center gap-1 text-sm">
        {steps.map((s, i) => (
          <li key={s.href} className="flex items-center gap-1">
            {i > 0 && (
              <ChevronRight className="size-4 text-muted-foreground" aria-hidden />
            )}
            <Link
              href={s.href}
              aria-current={s.current ? "step" : undefined}
              className={cn(
                "flex items-center gap-1.5 rounded-md px-2 py-1 outline-none focus-visible:ring-2 focus-visible:ring-ring/50",
                s.current
                  ? "bg-foreground text-background font-medium"
                  : "text-muted-foreground hover:text-foreground"
              )}
            >
              <span className="num text-xs opacity-70">{s.n}</span>
              {s.label}
            </Link>
          </li>
        ))}
      </ol>
      <p className="mt-2 text-sm text-muted-foreground">{hint}</p>
    </nav>
  )
}
