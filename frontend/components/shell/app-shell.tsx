"use client"

import * as React from "react"
import Link from "next/link"
import { usePathname, useRouter } from "next/navigation"
import {
  ChartColumn,
  Compass,
  Handshake,
  LayoutGrid,
  LogOut,
  Package,
  type LucideIcon,
} from "lucide-react"

import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip"
import { WelcomeNoteToast } from "@/components/auth/welcome-note-toast"
import { TryYourselfTrigger } from "@/components/voice/try-yourself-dialog"
import { VoiceDock } from "@/components/voice/voice-dock"
import { VoiceScreenProvider } from "@/components/voice/voice-screen"
import { clearDiscoverSession } from "@/lib/discover/state"
import { getSupabaseBrowser } from "@/lib/supabase/browser"
import { cn } from "@/lib/utils"

export type ShellRole = "brand" | "creator"

type NavItem = {
  label: string
  /** Tooltip text. Disabled items are described as coming soon instead. */
  hint: string
  icon: LucideIcon
  /** Absent for entries that are not built yet. */
  href?: string
}

const NAV: Record<ShellRole, NavItem[]> = {
  brand: [
    {
      label: "Discover",
      hint: "Find creators by voice",
      icon: Compass,
      href: "/brand/discover",
    },
    {
      label: "Board",
      hint: "Live negotiations",
      icon: LayoutGrid,
      href: "/brand/batches",
    },
    { label: "Analytics", hint: "How your deals perform", icon: ChartColumn },
  ],
  creator: [
    {
      label: "Packages",
      hint: "Your packages and prices",
      icon: Package,
      href: "/creator/packages",
    },
    { label: "Offers", hint: "Offers from brands", icon: Handshake },
    { label: "Analytics", hint: "How your deals perform", icon: ChartColumn },
  ],
}

const ROLE_LABEL: Record<ShellRole, string> = {
  brand: "Brand",
  creator: "Creator",
}

function isActive(pathname: string | null, href: string) {
  return pathname === href || !!pathname?.startsWith(`${href}/`)
}

const itemBase =
  "relative flex w-14 flex-col items-center gap-1 rounded-lg px-1 pt-2 pb-2.5 text-[0.6875rem] leading-none font-medium outline-none focus-visible:ring-3 focus-visible:ring-ring/50"

/** Ember underline that marks the section the user is in. */
const activeMark =
  "after:absolute after:inset-x-3 after:bottom-0.5 after:h-0.5 after:rounded-full after:bg-voice"

function RailLink({
  item,
  href,
  active,
}: {
  item: NavItem
  href: string
  active: boolean
}) {
  const Icon = item.icon

  return (
    <Tooltip>
      <TooltipTrigger
        render={
          <Link
            href={href}
            aria-current={active ? "page" : undefined}
            className={cn(
              itemBase,
              active
                ? cn("text-sidebar-foreground", activeMark)
                : "text-muted-foreground hover:bg-sidebar-accent hover:text-sidebar-foreground"
            )}
          />
        }
      >
        <Icon className="size-5" aria-hidden />
        {item.label}
      </TooltipTrigger>
      <TooltipContent side="right" sideOffset={8}>
        {item.hint}
      </TooltipContent>
    </Tooltip>
  )
}

/**
 * An entry that is planned but not built. It keeps a place in the rail so the
 * creator sees where the product is going, without being a dead link.
 */
function RailSoon({ item }: { item: NavItem }) {
  const Icon = item.icon
  const noteId = React.useId()

  return (
    <>
      <Tooltip>
        <TooltipTrigger
          render={
            <span
              role="link"
              tabIndex={0}
              aria-disabled="true"
              aria-describedby={noteId}
              className={cn(
                itemBase,
                "cursor-not-allowed text-muted-foreground/70"
              )}
            />
          }
        >
          <Icon className="size-5" aria-hidden />
          {item.label}
          <span
            aria-hidden
            className="-mt-0.5 num text-[0.625rem] tracking-wide text-muted-foreground uppercase"
          >
            Soon
          </span>
        </TooltipTrigger>
        <TooltipContent side="right" sideOffset={8}>
          {item.label} is coming soon
        </TooltipContent>
      </Tooltip>
      {/* Outside the trigger so the link's name stays just the label. */}
      <span id={noteId} className="sr-only">
        Coming soon
      </span>
    </>
  )
}

/**
 * Ends the session and returns to sign-in, so another account (a demo persona, say)
 * can be used without clearing cookies by hand.
 */
function SignOut() {
  const router = useRouter()
  const [leaving, setLeaving] = React.useState(false)

  async function signOut() {
    setLeaving(true)
    try {
      await getSupabaseBrowser().auth.signOut()
    } catch {
      // Leave for sign-in regardless: the user asked to go.
    }
    // The next account must not inherit this one's picks.
    clearDiscoverSession()
    router.replace("/sign-in")
    router.refresh()
  }

  return (
    <Tooltip>
      <TooltipTrigger
        render={
          <button
            type="button"
            disabled={leaving}
            onClick={signOut}
            className={cn(
              itemBase,
              "text-muted-foreground hover:bg-sidebar-accent hover:text-sidebar-foreground disabled:opacity-50"
            )}
          />
        }
      >
        <LogOut className="size-5" aria-hidden />
        Sign out
      </TooltipTrigger>
      <TooltipContent side="right" sideOffset={8}>
        Sign out of Collabio
      </TooltipContent>
    </Tooltip>
  )
}

type AppShellProps = {
  role: ShellRole
  children: React.ReactNode
}

export function AppShell({ role, children }: AppShellProps) {
  const pathname = usePathname()

  return (
    <VoiceScreenProvider>
      <WelcomeNoteToast />
      <div className="min-h-svh bg-background text-foreground">
        <aside
          data-slot="app-rail"
          className="fixed inset-y-0 left-0 z-30 flex w-(--rail-width) flex-col items-center border-r border-sidebar-border bg-sidebar py-3 text-sidebar-foreground"
        >
          <div
            role="img"
            aria-label="Collabio"
            className="flex size-9 items-center justify-center rounded-lg bg-foreground font-display text-2xl leading-none text-background italic"
          >
            C
          </div>

          <nav
            aria-label="Primary"
            className="mt-6 flex flex-1 flex-col items-center gap-1"
          >
            {NAV[role].map((item) =>
              item.href ? (
                <RailLink
                  key={item.label}
                  item={item}
                  href={item.href}
                  active={isActive(pathname, item.href)}
                />
              ) : (
                <RailSoon key={item.label} item={item} />
              )
            )}
          </nav>

          <TryYourselfTrigger role={role} />

          <SignOut />

          <p className="mt-3 text-[0.625rem] font-medium tracking-[0.18em] text-muted-foreground uppercase [writing-mode:vertical-rl]">
            {ROLE_LABEL[role]}
          </p>
        </aside>

        <div className="pl-(--rail-width)">
          <main
            id="main"
            className="mx-auto min-h-svh w-full max-w-[96rem] px-6 pt-6 pb-32"
          >
            {children}
          </main>
        </div>

        <div
          data-slot="voice-dock"
          className="pointer-events-none fixed inset-x-0 bottom-0 z-40 flex justify-center pb-4 pl-(--rail-width)"
        >
          <div className="pointer-events-auto">
            <VoiceDock />
          </div>
        </div>
      </div>
    </VoiceScreenProvider>
  )
}
