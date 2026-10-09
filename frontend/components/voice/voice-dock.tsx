"use client"

import { useGSAP } from "@gsap/react"
import gsap from "gsap"
import { Keyboard, Mic, SendHorizontal } from "lucide-react"
import { useReducedMotion } from "motion/react"
import dynamic from "next/dynamic"
import { useRouter } from "next/navigation"
import * as React from "react"
import { toast } from "sonner"

import type { AgentState } from "@/components/ui/orb"
import { HeardChip } from "@/components/voice/heard-chip"
import {
  useVoiceRegistry,
  type VoiceIntent,
} from "@/components/voice/voice-screen"
import { useApi } from "@/hooks/use-api"
import { safeNextPath } from "@/lib/auth/routing"
import { cn } from "@/lib/utils"
import {
  type DockMode,
  type DockState,
  dockReducer,
  initialDockState,
  isAtRest,
} from "@/lib/voice/dock-machine"
import { useCommandCapture } from "@/lib/voice/use-command-capture"

gsap.registerPlugin(useGSAP)

// three.js is heavy and only draws while the dock is working: load it on demand, and
// never on the server.
const Orb = dynamic(() => import("@/components/ui/orb").then((m) => m.Orb), {
  ssr: false,
})

/** The `--voice` ember as the Orb's [darker, lighter] ramp. It takes hex, not oklch. */
const ORB_COLORS: [string, string] = ["#f6623d", "#ffaf76"]

/** The backend rejects longer commands. */
const MAX_COMMAND_LENGTH = 500

/** How long a failure stays in the dock before it clears itself. */
const ERROR_MS = 6000

/**
 * Targets that keep Space for themselves: typing fields (and anything inside an
 * editable region) and controls that Space activates from the keyboard, such as
 * buttons, links, checkboxes and their ARIA equivalents. Without this a focused
 * checkbox could never be toggled with Space, and holding the key to speak would
 * press whatever control happened to have focus.
 */
const PASSTHROUGH = [
  "input",
  "textarea",
  "select",
  "button",
  "a[href]",
  "[contenteditable]:not([contenteditable='false'])",
  "[role=button]",
  "[role=checkbox]",
  "[role=switch]",
  "[role=radio]",
  "[role=option]",
  "[role=menuitem]",
  "[role=tab]",
  "[data-voice-passthrough]",
].join(", ")

/** The hold-to-speak button: a button, but Space on it is the push-to-talk key. */
const PUSH_TO_TALK = "[data-voice-ptt]"

type PressSource = "key" | "pointer"

function isSpace(event: KeyboardEvent) {
  return event.code === "Space" || event.key === " "
}

function leavesSpaceAlone(target: EventTarget | null) {
  if (!(target instanceof Element)) return false
  if (target.closest(PUSH_TO_TALK)) return false
  return target.closest(PASSTHROUGH) !== null
}

function orbState(mode: DockMode): AgentState {
  if (mode === "listening") return "listening"
  if (mode === "connecting" || mode === "routing") return "thinking"
  return null
}

function commandFailure(status: number) {
  if (status === 503) return "Voice is unavailable right now"
  if (status === 401) return "Your session expired"
  return "Couldn't process that command"
}

function liveLabel(mode: DockMode) {
  if (mode === "connecting") return "Connecting"
  if (mode === "listening") return "Listening"
  if (mode === "routing") return "Working on it"
  return ""
}

function Readout({ state }: { state: DockState }) {
  if (state.mode === "connecting") {
    return <p className="text-sm text-muted-foreground">Connecting…</p>
  }
  if (state.mode === "listening") {
    return state.partial ? (
      <p className="line-clamp-2 text-sm">{state.partial}</p>
    ) : (
      <p className="text-sm text-muted-foreground">Listening…</p>
    )
  }
  if (state.mode === "routing") {
    return (
      <p className="line-clamp-2 text-sm text-muted-foreground">
        {state.partial}
      </p>
    )
  }
  return <p className="text-sm text-muted-foreground">Hold Space to speak</p>
}

/**
 * The Voice Dock: hold Space (or press and hold the orb) and say a command. The words
 * appear as they are heard; on release the command is routed for the page on screen
 * and a "Heard" chip shows what was understood. A text box takes over when the
 * microphone cannot be used, or on request.
 */
export function VoiceDock() {
  const api = useApi()
  const router = useRouter()
  const registry = useVoiceRegistry()
  const reducedMotion = useReducedMotion()
  const [state, dispatch] = React.useReducer(dockReducer, initialDockState)
  const [draft, setDraft] = React.useState("")
  const [suggestions, setSuggestions] = React.useState<string[]>([])

  const rootRef = React.useRef<HTMLDivElement>(null)
  const pillRef = React.useRef<HTMLDivElement>(null)
  const ringRef = React.useRef<HTMLSpanElement>(null)
  const inputRef = React.useRef<HTMLInputElement>(null)
  const stateRef = React.useRef(state)
  const pressedBy = React.useRef<PressSource | null>(null)
  const showMode = React.useRef<((mode: DockMode) => void) | null>(null)

  React.useEffect(() => {
    stateRef.current = state
  })

  // Send a command to the router and hand the result to the page it was meant for.
  const route = React.useCallback(
    async (transcript: string) => {
      const target = registry?.current() ?? null
      const text = transcript.slice(0, MAX_COMMAND_LENGTH)

      let intent: VoiceIntent | undefined
      let failure = ""
      try {
        const { data, response } = await api.POST("/api/v1/voice/command", {
          body: {
            screen: target?.screen ?? "any",
            transcript: text,
            context: target?.getContext() ?? { visible_creators: [] },
          },
        })
        intent = data
        if (!data) failure = commandFailure(response.status)
      } catch {
        failure = "Couldn't reach Collabio"
      }

      if (!intent) {
        // Keep what was said where the text box can pick it up for a retry.
        setDraft(text)
        dispatch({ type: "FAIL", reason: failure, fatal: false })
        return
      }

      setSuggestions(intent.kind === "unclear" ? intent.suggestions : [])
      dispatch({ type: "ROUTED", heard: intent.heard || text })

      // `unclear` is the dock's to show. Anything else acts only if the page that was
      // on screen when the command was sent still is.
      if (intent.kind === "unclear") return
      if ((registry?.current() ?? null) !== target) return

      // Going to another page is the same on every screen, so the dock does it and
      // pages never see it. Only in-app paths are followed.
      if (intent.kind === "navigate") {
        const to = intent.navigate
        if (to && safeNextPath(to) === to) router.push(to)
        return
      }

      if (!target) return
      try {
        target.onIntent(intent)
      } catch (error) {
        console.error("The page failed to handle a voice command", error)
      }
    },
    [api, registry, router]
  )

  const capture = useCommandCapture({
    onConnected: () => dispatch({ type: "CONNECTED" }),
    onPartial: (text) => dispatch({ type: "PARTIAL", text }),
    onFinal: (text) => {
      dispatch({ type: "RELEASE", finalText: text })
      if (text.trim()) void route(text)
    },
    onError: ({ reason, fatal }) => {
      dispatch({ type: "FAIL", reason, fatal })
      if (fatal) {
        // Typing takes over and disables the orb, so a pointer-up that would end a
        // press-and-hold may never arrive: drop the hold or Space stays locked out.
        // (A held key is let go by its own key-up, which still arrives.)
        if (pressedBy.current === "pointer") pressedBy.current = null
        toast.error(reason, {
          description: "You can type your commands instead.",
        })
      }
    },
  })
  const { start, stop } = capture

  const beginPress = React.useCallback(
    (source: PressSource) => {
      const current = stateRef.current
      if (
        pressedBy.current ||
        current.input !== "voice" ||
        !isAtRest(current.mode)
      ) {
        return false
      }
      pressedBy.current = source
      dispatch({ type: "PRESS" })
      void start()
      return true
    },
    [start]
  )

  const endPress = React.useCallback(
    (source?: PressSource) => {
      if (!pressedBy.current) return false
      if (source && pressedBy.current !== source) return false
      pressedBy.current = null
      stop()
      return true
    },
    [stop]
  )

  // Hold Space anywhere that is not asking for typing.
  React.useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (!isSpace(event)) return
      // Auto-repeat of the key being held: keep the page from scrolling.
      if (pressedBy.current === "key") return event.preventDefault()
      if (event.repeat || event.ctrlKey || event.metaKey || event.altKey) return
      if (leavesSpaceAlone(event.target)) return
      if (beginPress("key")) event.preventDefault()
    }
    const onKeyUp = (event: KeyboardEvent) => {
      if (!isSpace(event)) return
      // Also stops a focused button from taking the release as a click.
      if (endPress("key")) event.preventDefault()
    }
    // A release that happens while the window is not looking never arrives.
    const onBlur = () => endPress()

    window.addEventListener("keydown", onKeyDown)
    window.addEventListener("keyup", onKeyUp)
    window.addEventListener("blur", onBlur)
    return () => {
      window.removeEventListener("keydown", onKeyDown)
      window.removeEventListener("keyup", onKeyUp)
      window.removeEventListener("blur", onBlur)
    }
  }, [beginPress, endPress])

  // Motion: the dock rises in once; the ring and pill follow the mode. Everything
  // snaps instead when the user prefers reduced motion.
  useGSAP(
    (_, contextSafe) => {
      const mm = gsap.matchMedia()
      mm.add(
        {
          motion: "(prefers-reduced-motion: no-preference)",
          reduce: "(prefers-reduced-motion: reduce)",
        },
        (context) => {
          const reduce = Boolean(context.conditions?.reduce)

          if (reduce) {
            gsap.set(rootRef.current, { opacity: 1 })
          } else {
            gsap.fromTo(
              rootRef.current,
              { opacity: 0, y: 16 },
              { opacity: 1, y: 0, duration: 0.35, ease: "power2.out" }
            )
          }

          showMode.current = contextSafe!((mode: DockMode) => {
            const ring = mode === "listening" ? 1 : mode === "idle" ? 0 : 0.45
            if (reduce) {
              gsap.set(ringRef.current, { opacity: ring })
              return
            }
            const tween = {
              duration: 0.25,
              ease: "power2.out",
              overwrite: "auto",
            } as const
            gsap.to(ringRef.current, {
              opacity: ring,
              scale: ring ? 1 : 0.96,
              ...tween,
            })
            gsap.to(pillRef.current, {
              scale: mode === "listening" ? 1.02 : 1,
              ...tween,
            })
          })
          return () => {
            showMode.current = null
          }
        }
      )
      return () => mm.revert()
    },
    { scope: rootRef }
  )

  React.useEffect(() => {
    showMode.current?.(state.mode)
  }, [state.mode])

  // Failures clear themselves.
  React.useEffect(() => {
    if (state.mode !== "error") return
    const timer = setTimeout(() => dispatch({ type: "DISMISS" }), ERROR_MS)
    return () => clearTimeout(timer)
  }, [state.mode])

  // Typing is what the user asked for (or was left with): put the cursor there.
  React.useEffect(() => {
    if (state.input === "text") inputRef.current?.focus()
  }, [state.input])

  function submitText(raw: string) {
    const text = raw.trim()
    if (!text || !isAtRest(state.mode)) return
    setDraft("")
    dispatch({ type: "TEXT_SUBMIT", text })
    void route(text)
  }

  const typing = state.input === "text"
  const busy = !isAtRest(state.mode)
  const orbLive =
    !reducedMotion &&
    (state.mode === "connecting" ||
      state.mode === "listening" ||
      state.mode === "routing")

  return (
    <div
      ref={rootRef}
      role="group"
      aria-label="Voice commands"
      data-mode={state.mode}
      // Hidden until the entrance tween (or its reduced-motion snap) shows it, so
      // server-rendered markup does not flash before hydration.
      className="flex flex-col items-center gap-2 opacity-0"
    >
      {state.mode === "error" ? (
        // Above the pill, so it shows in the text box mode too.
        <p
          role="alert"
          className="max-w-[min(32rem,calc(100vw-var(--rail-width)-2rem))] rounded-2xl border border-destructive/40 bg-card/80 px-3 py-1.5 text-sm text-destructive shadow-sm backdrop-blur-[16px]"
        >
          {state.error}
        </p>
      ) : null}

      {state.mode === "heard" && state.heard !== null ? (
        <HeardChip
          heard={state.heard}
          suggestions={suggestions}
          onEdit={(heard) => {
            setDraft(heard)
            dispatch({ type: "SET_INPUT", input: "text" })
          }}
          onSuggest={submitText}
          onDismiss={() => dispatch({ type: "DISMISS" })}
        />
      ) : null}

      <div
        ref={pillRef}
        className="relative flex items-center gap-2 rounded-full border bg-card/70 py-1.5 pr-2 pl-1.5 shadow-lg backdrop-blur-[16px]"
      >
        <span
          ref={ringRef}
          aria-hidden
          className="pointer-events-none absolute -inset-px rounded-full opacity-0 ring-2 ring-voice"
        />

        <button
          type="button"
          disabled={typing}
          aria-label="Hold to speak"
          aria-keyshortcuts="Space"
          data-voice-ptt
          onPointerDown={(event) => {
            if (event.button !== 0) return
            if (beginPress("pointer")) {
              event.currentTarget.setPointerCapture?.(event.pointerId)
            }
          }}
          onPointerUp={() => endPress("pointer")}
          onPointerCancel={() => endPress("pointer")}
          onContextMenu={(event) => event.preventDefault()}
          className="relative size-10 shrink-0 touch-none rounded-full outline-none select-none focus-visible:ring-3 focus-visible:ring-ring/50 disabled:opacity-50"
        >
          <span
            aria-hidden
            className="absolute inset-[1.75px] rounded-full bg-[radial-gradient(circle_at_35%_30%,#ffaf76,var(--voice)_55%,color-mix(in_oklch,var(--voice),black_35%))]"
          />
          {orbLive ? (
            <Orb
              colors={ORB_COLORS}
              agentState={orbState(state.mode)}
              className="pointer-events-none absolute inset-0"
            />
          ) : null}
        </button>

        <div className="flex h-10 w-64 items-center sm:w-80">
          {typing ? (
            <form
              className="flex w-full items-center gap-1"
              onSubmit={(event) => {
                event.preventDefault()
                submitText(draft)
              }}
            >
              <input
                ref={inputRef}
                value={draft}
                onChange={(event) => setDraft(event.target.value)}
                disabled={busy}
                maxLength={MAX_COMMAND_LENGTH}
                placeholder="Type a command"
                aria-label="Type a command"
                autoComplete="off"
                className="h-9 min-w-0 flex-1 rounded-full bg-transparent px-2 text-sm outline-none placeholder:text-muted-foreground focus-visible:ring-3 focus-visible:ring-ring/50 disabled:opacity-60"
              />
              <button
                type="submit"
                aria-label="Send command"
                disabled={busy || !draft.trim()}
                className="flex size-8 shrink-0 items-center justify-center rounded-full bg-foreground text-background outline-none focus-visible:ring-3 focus-visible:ring-ring/50 disabled:opacity-40"
              >
                <SendHorizontal aria-hidden className="size-4" />
              </button>
            </form>
          ) : (
            <Readout state={state} />
          )}
        </div>

        <button
          type="button"
          data-voice-passthrough
          disabled={busy}
          aria-label={typing ? "Use voice" : "Type a command instead"}
          onClick={() =>
            dispatch({ type: "SET_INPUT", input: typing ? "voice" : "text" })
          }
          className={cn(
            "flex size-8 shrink-0 items-center justify-center rounded-full text-muted-foreground outline-none hover:bg-muted hover:text-foreground focus-visible:ring-3 focus-visible:ring-ring/50 disabled:opacity-50",
            typing && "bg-muted text-foreground"
          )}
        >
          {typing ? (
            <Mic aria-hidden className="size-4" />
          ) : (
            <Keyboard aria-hidden className="size-4" />
          )}
        </button>
      </div>

      <span role="status" className="sr-only">
        {liveLabel(state.mode)}
      </span>
    </div>
  )
}
