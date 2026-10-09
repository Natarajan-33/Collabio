export type DemoAccount = { email: string; who: string }

/** `a.b@x.com` + `arjun` -> `a.b+arjun@x.com`: the same rule as the backend seed. */
export function plusAddress(email: string, tag: string): string {
  const at = email.indexOf("@")
  return `${email.slice(0, at)}+${tag}${email.slice(at)}`
}

/** A usable address has something on both sides of the `@`. */
function address(value: string | undefined): string | null {
  const email = value?.trim() ?? ""
  const at = email.indexOf("@")
  return at > 0 && at < email.length - 1 ? email : null
}

/**
 * The seeded demo logins to hint at on the sign-in page, from the same
 * `DEMO_BRAND_EMAIL` / `DEMO_HELPER_EMAIL` the backend seed reads. The seed creates the
 * second creator, Arjun, as a plus-address of the helper, so it is derived the same way.
 * Empty when nothing is configured, which hides the hint.
 */
export function demoAccounts({
  brand,
  helper,
}: {
  brand?: string
  helper?: string
}): DemoAccount[] {
  const brandEmail = address(brand)
  const helperEmail = address(helper)

  return [
    ...(brandEmail ? [{ email: brandEmail, who: "Brand · Lumen" }] : []),
    ...(helperEmail
      ? [
          { email: helperEmail, who: "Creator · Priya" },
          { email: plusAddress(helperEmail, "arjun"), who: "Creator · Arjun" },
        ]
      : []),
  ]
}
