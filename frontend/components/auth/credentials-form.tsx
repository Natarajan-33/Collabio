"use client"

import Link from "next/link"
import { useRouter } from "next/navigation"
import { useId, useRef, useState } from "react"
import { LoaderCircle, MailCheck } from "lucide-react"

import { DemoAccounts } from "@/components/auth/demo-accounts"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import type { DemoAccount } from "@/lib/auth/demo"
import { getSupabaseBrowser } from "@/lib/supabase/browser"

type Mode = "sign-in" | "sign-up"

type AuthFailure = { code?: string; name?: string; message?: string }

const COPY = {
  "sign-in": {
    heading: "Welcome back",
    lede: "Sign in to your deal room.",
    submit: "Sign in",
    busy: "Signing in…",
    password: "current-password",
    fallback: "Could not sign in. Try again.",
  },
  "sign-up": {
    heading: "Open your deal room",
    lede: "Create an account. You will choose brand or creator next.",
    submit: "Create account",
    busy: "Creating account…",
    password: "new-password",
    fallback: "Could not create the account. Try again.",
  },
} as const

/** Plain-words messages for the failures a person can act on. */
function describeFailure(mode: Mode, error: AuthFailure): string {
  if (error.name === "AuthRetryableFetchError") {
    return "We can't reach the sign-in service. Check your connection and try again."
  }
  switch (error.code) {
    case "invalid_credentials":
      return "That email and password don't match. Check both and try again."
    case "email_not_confirmed":
      return "Confirm your email first. We sent you a link when you signed up."
    case "user_already_exists":
    case "email_exists":
      return "That email already has an account. Sign in instead."
    case "over_email_send_rate_limit":
    case "over_request_rate_limit":
      return "Too many attempts for now. Wait a minute and try again."
  }
  return error.message || COPY[mode].fallback
}

type CredentialsFormProps = {
  mode: Mode
  /** Where to land after signing in. Already vetted by `safeNextPath`. */
  next?: string
  /** Seeded demo logins to hint at (sign-in only). Empty or absent hides the hint. */
  demoAccounts?: readonly DemoAccount[]
}

export function CredentialsForm({
  mode,
  next = "/",
  demoAccounts = [],
}: CredentialsFormProps) {
  const router = useRouter()
  const emailId = useId()
  const passwordId = useId()
  const errorId = useId()
  const passwordRef = useRef<HTMLInputElement>(null)
  const [email, setEmail] = useState("")
  const [password, setPassword] = useState("")
  const [pending, setPending] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [confirmEmail, setConfirmEmail] = useState<string | null>(null)

  const copy = COPY[mode]

  function enter(to: string) {
    router.replace(to)
    // Pages fetched while signed out may be cached; make the new session visible.
    router.refresh()
  }

  async function onSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (pending) return
    setPending(true)
    setError(null)

    try {
      const supabase = getSupabaseBrowser()
      if (mode === "sign-in") {
        const { error: failure } = await supabase.auth.signInWithPassword({
          email,
          password,
        })
        if (failure) throw failure
        // Stay locked while the app navigates away.
        enter(next)
      } else {
        const { data, error: failure } = await supabase.auth.signUp({
          email,
          password,
          // If the project requires email confirmation, the link lands here.
          options: { emailRedirectTo: `${window.location.origin}/sign-in` },
        })
        if (failure) throw failure
        if (data.session) {
          enter("/onboarding")
        } else {
          setConfirmEmail(email)
          setPending(false)
        }
      }
    } catch (failure) {
      setError(describeFailure(mode, (failure ?? {}) as AuthFailure))
      setPending(false)
    }
  }

  if (confirmEmail) {
    return (
      <section className="w-full max-w-sm">
        <MailCheck aria-hidden className="size-8 text-muted-foreground" />
        <h1 className="mt-6 font-display text-5xl leading-[1.02]">
          Check your inbox
        </h1>
        <p role="status" className="mt-4 text-muted-foreground">
          We sent a confirmation link to{" "}
          <span className="font-medium break-all text-foreground">
            {confirmEmail}
          </span>
          . Confirm your email, then sign in to continue.
        </p>
        <Button
          variant="outline"
          size="lg"
          className="mt-8 h-10 w-full"
          render={<Link href="/sign-in" />}
          nativeButton={false}
        >
          Go to sign in
        </Button>
      </section>
    )
  }

  return (
    <section className="w-full max-w-sm">
      <h1 className="font-display text-5xl leading-[1.02]">{copy.heading}</h1>
      <p className="mt-3 text-muted-foreground">{copy.lede}</p>

      <form onSubmit={onSubmit} className="mt-8 space-y-5">
        <div className="space-y-2">
          <Label htmlFor={emailId}>Email</Label>
          <Input
            id={emailId}
            type="email"
            name="email"
            autoComplete="email"
            required
            value={email}
            onChange={(event) => setEmail(event.target.value)}
            aria-invalid={error ? true : undefined}
            aria-describedby={error ? errorId : undefined}
            className="h-10"
          />
        </div>
        <div className="space-y-2">
          <Label htmlFor={passwordId}>Password</Label>
          <Input
            ref={passwordRef}
            id={passwordId}
            type="password"
            name="password"
            autoComplete={copy.password}
            required
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            aria-invalid={error ? true : undefined}
            aria-describedby={error ? errorId : undefined}
            className="h-10"
          />
        </div>

        {error ? (
          <p id={errorId} role="alert" className="text-sm text-destructive">
            {error}
          </p>
        ) : null}

        <Button
          type="submit"
          size="lg"
          disabled={pending}
          className="h-10 w-full text-sm"
        >
          {pending ? (
            <>
              <LoaderCircle aria-hidden className="animate-spin" />
              {copy.busy}
            </>
          ) : (
            copy.submit
          )}
        </Button>
      </form>

      <p className="mt-6 text-sm text-muted-foreground">
        {mode === "sign-in" ? (
          <>
            New to Collabio?{" "}
            <Link
              href="/sign-up"
              className="font-medium text-foreground underline underline-offset-4"
            >
              Create an account
            </Link>
          </>
        ) : (
          <>
            Already have an account?{" "}
            <Link
              href="/sign-in"
              className="font-medium text-foreground underline underline-offset-4"
            >
              Sign in
            </Link>
          </>
        )}
      </p>

      {demoAccounts.length > 0 && mode === "sign-in" ? (
        <DemoAccounts
          accounts={demoAccounts}
          onPick={(picked) => {
            setEmail(picked)
            // The password is the only thing left to type.
            passwordRef.current?.focus()
          }}
        />
      ) : null}
    </section>
  )
}
