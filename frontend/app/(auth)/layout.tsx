import Link from "next/link"

/**
 * Chrome shared by sign-in, sign-up and onboarding: the wordmark, and an ember glow on
 * the horizon (the one place the voice accent is allowed to sit large).
 */
export default function AuthLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <div className="relative min-h-svh overflow-hidden bg-background text-foreground">
      <div
        aria-hidden
        className="pointer-events-none absolute inset-x-0 top-0 h-112 bg-[radial-gradient(52rem_22rem_at_50%_-6rem,color-mix(in_oklch,var(--voice)_17%,transparent),transparent_72%)]"
      />

      <header className="relative px-6 pt-6 sm:px-10">
        <Link
          href="/"
          className="inline-flex items-center gap-2.5 rounded-lg outline-none focus-visible:ring-3 focus-visible:ring-ring/50"
        >
          <span
            aria-hidden
            className="flex size-9 items-center justify-center rounded-lg bg-foreground font-display text-2xl leading-none text-background italic"
          >
            C
          </span>
          <span className="font-display text-2xl leading-none">Collabio</span>
        </Link>
      </header>

      <main
        id="main"
        className="relative flex flex-col items-center px-6 pt-14 pb-20 sm:pt-20"
      >
        {children}
      </main>
    </div>
  )
}
