/**
 * The product's flow, shown as a "you are here" strip on every page: which step this page is
 * and what moves a creator to the next one (a contacted creator is not a deal until booked).
 */
export type FlowRole = "brand" | "creator"

type Step = { label: string; href: string; hint: string }

const STEPS: Record<FlowRole, Step[]> = {
  brand: [
    {
      label: "Discover",
      href: "/brand/discover",
      hint: "Find creators who fit your product, then send them an offer.",
    },
    {
      label: "Outreach",
      href: "/brand/batches",
      hint: "Offers you sent. Creators reply or counter here; when one agrees, book them and the deal moves to Booked.",
    },
    {
      label: "Booked",
      href: "/brand/deals",
      hint: "Creators you booked. Fund the deal once with PayPal; Claude checks each video and pays the creator.",
    },
    {
      label: "Money",
      href: "/brand/money",
      hint: "Every PayPal payment, payout and refund, with an assistant that answers questions.",
    },
  ],
  creator: [
    {
      label: "Packages",
      href: "/creator/packages",
      hint: "What you sell and at what price. Brands see these when they search.",
    },
    {
      label: "Offers",
      href: "/creator/offers",
      hint: "Offers from brands. Accept, counter or decline; accepted offers move to Booked once the brand books you.",
    },
    {
      label: "Booked",
      href: "/creator/deals",
      hint: "Deals you agreed to. Submit proof for each video and get paid through PayPal.",
    },
  ],
}

const ALSO: Record<string, string> = { "/brand/briefs": "/brand/batches" }

export function flowFor(role: FlowRole, pathname: string | null) {
  let path = pathname ?? ""
  for (const [from, to] of Object.entries(ALSO)) if (path.startsWith(from)) path = to
  const steps = STEPS[role].map((s, i) => ({
    ...s,
    n: i + 1,
    current: path === s.href || path.startsWith(`${s.href}/`),
  }))
  return { steps, hint: steps.find((s) => s.current)?.hint ?? "" }
}
