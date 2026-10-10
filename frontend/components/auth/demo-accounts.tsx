import type { DemoAccount } from "@/lib/auth/demo"

/**
 * The seeded demo logins, for a walkthrough on a demo deployment. Picking one fills the
 * email field. The password is shared out of band and is never shown here. The list
 * comes from the server's environment (see `demoAccounts`), never from this file.
 */
export function DemoAccounts({
  accounts,
  onPick,
}: {
  accounts: readonly DemoAccount[]
  onPick: (email: string) => void
}) {
  return (
    <aside
      aria-label="Demo accounts"
      className="mt-10 rounded-2xl border border-dashed border-border bg-card/60 p-4"
    >
      <p className="px-2 text-xs font-medium tracking-[0.14em] text-muted-foreground uppercase">
        Demo accounts
      </p>
      <ul className="mt-2">
        {accounts.map(({ email, who }) => (
          <li key={email}>
            <button
              type="button"
              onClick={() => onPick(email)}
              className="flex w-full flex-col gap-0.5 rounded-lg px-2 py-2 text-left outline-none hover:bg-muted focus-visible:ring-3 focus-visible:ring-ring/50 sm:flex-row sm:items-baseline sm:justify-between sm:gap-3"
            >
              <span className="font-mono text-[0.8125rem] break-all">
                {email}
              </span>
              <span className="text-xs whitespace-nowrap text-muted-foreground">
                {who}
              </span>
            </button>
          </li>
        ))}
      </ul>
    </aside>
  )
}
