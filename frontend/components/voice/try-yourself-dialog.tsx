"use client"

import * as React from "react"
import { Info, Mail, PhoneCall } from "lucide-react"
import { toast } from "sonner"

import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Label } from "@/components/ui/label"
import { CALLS_OFF, isHackathon } from "@/lib/hackathon"
import { useApi } from "@/hooks/use-api"
import {
  TRY_SCENARIOS,
  type TryScenarioId,
} from "@/lib/voice/try-scenarios"
import type { ShellRole } from "@/components/shell/app-shell"
import { cn } from "@/lib/utils"

type Mode = "call" | "email"

// Hackathon mode starts on email: calls are off in the public demo.
const INITIAL_MODE: Mode = isHackathon ? "email" : "call"
type Step = "channel" | "contact" | "scenario" | "done"

/** Shown wherever we explain the Twilio MVP trial — sets expectation + roadmap. */
const CALL_TRIAL_ROADMAP =
  "Bear with us — Collabio is still in active development. We're upgrading telephony so outreach and demo calls can reach any number without pre-verification. That ships in the next one or two iterations."

const ROLE_INTRO: Record<ShellRole, { call: string; email: string }> = {
  brand: {
    call:
      "Answer and play the creator — our AI agent negotiates on behalf of a sample brand.",
    email:
      "See the outreach email a creator would get, with AI-written negotiation copy for a sample deal.",
  },
  creator: {
    call:
      "Hear a sample sponsorship call and respond like you would to a real brand.",
    email:
      "See what a brand outreach email looks like when they ask you for a collaboration.",
  },
}

function normalizePhone(raw: string): string {
  const trimmed = raw.trim()
  if (trimmed.startsWith("+")) return trimmed.replace(/[\s()-]/g, "")
  const digits = trimmed.replace(/\D/g, "")
  if (!digits) return trimmed
  return `+${digits}`
}

function ScenarioList({
  scenario,
  onSelect,
}: {
  scenario: TryScenarioId
  onSelect: (id: TryScenarioId) => void
}) {
  return (
    <ul className="space-y-2 py-1" role="listbox" aria-label="Sample deals">
      {TRY_SCENARIOS.map((item) => {
        const selected = scenario === item.id
        return (
          <li key={item.id}>
            <button
              type="button"
              role="option"
              aria-selected={selected}
              onClick={() => onSelect(item.id)}
              className={cn(
                "w-full rounded-lg border px-3 py-2.5 text-left text-sm transition-colors",
                selected ? "border-voice bg-voice/10" : "border-border hover:bg-muted/50"
              )}
            >
              <span className="font-medium">{item.label}</span>
              <span className="mt-0.5 block text-muted-foreground">{item.hint}</span>
            </button>
          </li>
        )
      })}
    </ul>
  )
}

type TryYourselfDialogProps = {
  role: ShellRole
  open: boolean
  onOpenChange: (open: boolean) => void
}

export function TryYourselfDialog({
  role,
  open,
  onOpenChange,
}: TryYourselfDialogProps) {
  const api = useApi()
  const [step, setStep] = React.useState<Step>("channel")
  const [mode, setMode] = React.useState<Mode>(INITIAL_MODE)
  const [phone, setPhone] = React.useState("")
  const [email, setEmail] = React.useState("")
  const [scenario, setScenario] = React.useState<TryScenarioId>("standard")
  const [message, setMessage] = React.useState("")
  const [busy, setBusy] = React.useState(false)

  // Closing the dialog clears it, so each opening starts from the first step. Reset while
  // rendering (guarded, so it settles at once) rather than in an effect.
  const dirty =
    step !== "channel" ||
    mode !== INITIAL_MODE ||
    phone !== "" ||
    email !== "" ||
    scenario !== "standard" ||
    message !== "" ||
    busy
  if (!open && dirty) {
    setStep("channel")
    setMode(INITIAL_MODE)
    setPhone("")
    setEmail("")
    setScenario("standard")
    setMessage("")
    setBusy(false)
  }

  const intro = ROLE_INTRO[role]

  async function placeCall() {
    setBusy(true)
    const { data, error, response } = await api.POST("/api/v1/voice/try-call", {
      body: { phone: normalizePhone(phone), scenario },
    })
    setBusy(false)
    if (!response.ok || !data) {
      handleCallError(response.status, error)
      return
    }
    setMessage(data.message)
    setStep("done")
  }

  async function sendEmail() {
    setBusy(true)
    const { data, error, response } = await api.POST("/api/v1/voice/try-email", {
      body: { email: email.trim().toLowerCase(), scenario },
    })
    setBusy(false)
    if (!response.ok || !data) {
      const detail =
        error && typeof error === "object" && "detail" in error
          ? String((error as { detail: unknown }).detail)
          : ""
      if (response.status === 429) {
        toast.error("You've reached today's demo email limit. Try again tomorrow.")
      } else if (detail === "email_not_configured") {
        toast.error(
          "Email isn't configured yet. Set RESEND_API_KEY and RESEND_FROM in backend/.env (your verified domain sender), then restart the API."
        )
      } else if (detail === "email_rejected") {
        toast.error("Resend rejected this address. Check the email and your Resend domain settings.")
      } else {
        toast.error(
          detail === "invalid_email"
            ? "Enter a valid email address."
            : "Could not send the sample email. Try again in a moment."
        )
      }
      return
    }
    setMessage(data.message)
    setStep("done")
  }

  function handleCallError(
    status: number,
    error: unknown
  ) {
    const detail =
      error && typeof error === "object" && "detail" in error
        ? String((error as { detail: unknown }).detail)
        : "Could not place the call."
    if (status === 429) {
      toast.error("You've reached today's demo call limit. Try again tomorrow.")
    } else if (detail === "demo_not_configured") {
      toast.error(
        "Demo data is missing. From backend/, run: uv run python -m scripts.seed --reset"
      )
    } else if (detail === "number_not_verified") {
      toast.error(
        `We could not place your call to ${normalizePhone(phone)}. On our MVP telephony trial we can only ring pre-verified numbers — this one is not verified yet. ${CALL_TRIAL_ROADMAP}`
      )
    } else if (status === 503) {
      toast.error(
        "Could not place the call (ElevenLabs/Twilio). Check backend logs for “try_call placement failed”."
      )
    } else {
      toast.error(detail === "invalid_phone" ? "Enter a valid number with country code." : detail)
    }
  }

  function pickMode(next: Mode) {
    setMode(next)
    setStep("contact")
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        {step === "channel" && (
          <>
            <DialogHeader>
              <DialogTitle>Try negotiation</DialogTitle>
              <DialogDescription>
                Sample how Collabio reaches creators — by phone or by email. Nothing is saved to
                your board.
              </DialogDescription>
            </DialogHeader>
            <div className="grid gap-2 py-2">
              <button
                type="button"
                disabled={isHackathon}
                onClick={() => pickMode("call")}
                className="flex items-start gap-3 rounded-lg border border-border px-3 py-3 text-left hover:bg-muted/50 disabled:pointer-events-none disabled:opacity-50"
              >
                <PhoneCall className="mt-0.5 size-5 shrink-0 text-voice" aria-hidden />
                <span>
                  <span className="block font-medium">Call me</span>
                  <span className="text-sm text-muted-foreground">
                    {isHackathon ? CALLS_OFF : intro.call}
                  </span>
                </span>
              </button>
              <button
                type="button"
                onClick={() => pickMode("email")}
                className="flex items-start gap-3 rounded-lg border border-border px-3 py-3 text-left hover:bg-muted/50"
              >
                <Mail className="mt-0.5 size-5 shrink-0 text-voice" aria-hidden />
                <span>
                  <span className="block font-medium">Email me</span>
                  <span className="text-sm text-muted-foreground">{intro.email}</span>
                </span>
              </button>
            </div>
          </>
        )}

        {step === "contact" && mode === "call" && (
          <>
            <DialogHeader>
              <DialogTitle>Your mobile number</DialogTitle>
              <DialogDescription>{intro.call}</DialogDescription>
            </DialogHeader>
            <div className="space-y-3 py-2">
              <div className="space-y-2">
                <Label htmlFor="try-phone">Mobile number</Label>
                <input
                  id="try-phone"
                  type="tel"
                  autoComplete="tel"
                  placeholder="+1 415 555 0123"
                  value={phone}
                  onChange={(e) => setPhone(e.target.value)}
                  className="flex h-10 w-full rounded-md border border-input bg-background px-3 text-sm shadow-xs outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50"
                />
              </div>
              <div
                role="note"
                className="flex gap-2 rounded-lg border border-border bg-muted/40 px-3 py-2.5 text-xs text-muted-foreground"
              >
                <Info className="mt-0.5 size-4 shrink-0 text-foreground" aria-hidden />
                <div className="space-y-1.5">
                  <p className="font-medium text-foreground">
                    MVP trial: only verified numbers can be called
                  </p>
                  <p>
                    For now, only numbers already verified on our telephony trial can be called.
                    If you are testing with your own phone, it may need to be verified on the
                    provider side first.
                  </p>
                  <p>{CALL_TRIAL_ROADMAP}</p>
                  <p>Your number is only used for this call and is never saved in Collabio.</p>
                </div>
              </div>
            </div>
            <DialogFooter className="gap-2 sm:justify-between">
              <Button type="button" variant="ghost" onClick={() => setStep("channel")}>
                Back
              </Button>
              <Button
                type="button"
                disabled={!phone.trim()}
                onClick={() => setStep("scenario")}
              >
                Continue
              </Button>
            </DialogFooter>
          </>
        )}

        {step === "contact" && mode === "email" && (
          <>
            <DialogHeader>
              <DialogTitle>Your email</DialogTitle>
              <DialogDescription>{intro.email}</DialogDescription>
            </DialogHeader>
            <div className="space-y-3 py-2">
              <div className="space-y-2">
                <Label htmlFor="try-email">Email address</Label>
                <input
                  id="try-email"
                  type="email"
                  autoComplete="email"
                  placeholder="you@example.com"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  className="flex h-10 w-full rounded-md border border-input bg-background px-3 text-sm shadow-xs outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50"
                />
              </div>
              <div
                role="note"
                className="rounded-lg border border-border bg-muted/40 px-3 py-2.5 text-xs text-muted-foreground"
              >
                <p>
                  We’ll send one sample outreach email from your configured brand sender
                  (Resend). Your address is not stored in Collabio — only used for this demo.
                </p>
              </div>
            </div>
            <DialogFooter className="gap-2 sm:justify-between">
              <Button type="button" variant="ghost" onClick={() => setStep("channel")}>
                Back
              </Button>
              <Button
                type="button"
                disabled={!email.trim()}
                onClick={() => setStep("scenario")}
              >
                Continue
              </Button>
            </DialogFooter>
          </>
        )}

        {step === "scenario" && (
          <>
            <DialogHeader>
              <DialogTitle>Pick a sample deal</DialogTitle>
              <DialogDescription>
                {mode === "call" ? (
                  <>
                    Brief for calling{" "}
                    <span className="font-medium text-foreground">{normalizePhone(phone)}</span>
                    . On our MVP trial, the number must be pre-verified for the call to connect.
                  </>
                ) : (
                  <>
                    Brief for emailing{" "}
                    <span className="font-medium text-foreground">{email.trim()}</span>.
                  </>
                )}
              </DialogDescription>
            </DialogHeader>
            <ScenarioList scenario={scenario} onSelect={setScenario} />
            <DialogFooter className="gap-2 sm:justify-between">
              <Button type="button" variant="ghost" onClick={() => setStep("contact")}>
                Back
              </Button>
              <Button
                type="button"
                disabled={busy}
                onClick={mode === "call" ? placeCall : sendEmail}
              >
                {busy
                  ? mode === "call"
                    ? "Calling…"
                    : "Sending…"
                  : mode === "call"
                    ? "Call me now"
                    : "Send sample email"}
              </Button>
            </DialogFooter>
          </>
        )}

        {step === "done" && (
          <>
            <DialogHeader>
              <DialogTitle className="flex items-center gap-2">
                {mode === "call" ? (
                  <PhoneCall className="size-5 text-voice" aria-hidden />
                ) : (
                  <Mail className="size-5 text-voice" aria-hidden />
                )}
                {mode === "call" ? "Your phone should ring shortly" : "Check your inbox"}
              </DialogTitle>
              <DialogDescription>{message}</DialogDescription>
            </DialogHeader>
            {mode === "call" ? (
              <p className="text-sm text-muted-foreground">
                Stay on the line and negotiate naturally. When you hang up, the demo ends.
              </p>
            ) : (
              <p className="text-sm text-muted-foreground">
                The subject line starts with [Collabio sample]. Check spam if you do not see it
                within a minute.
              </p>
            )}
            <DialogFooter>
              <Button type="button" onClick={() => onOpenChange(false)}>
                Done
              </Button>
            </DialogFooter>
          </>
        )}
      </DialogContent>
    </Dialog>
  )
}

type TryYourselfTriggerProps = {
  role: ShellRole
  className?: string
}

export function TryYourselfTrigger({ role, className }: TryYourselfTriggerProps) {
  const [open, setOpen] = React.useState(false)

  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        className={cn(
          "flex w-14 flex-col items-center gap-1 rounded-lg px-1 pt-2 pb-2.5 text-[0.6875rem] leading-none font-medium text-muted-foreground outline-none hover:bg-sidebar-accent hover:text-sidebar-foreground focus-visible:ring-3 focus-visible:ring-ring/50",
          className
        )}
      >
        <PhoneCall className="size-5" aria-hidden />
        Try it
      </button>
      <TryYourselfDialog role={role} open={open} onOpenChange={setOpen} />
    </>
  )
}
