"use client"

import { Button } from "@/components/ui/button"
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
  SheetTrigger,
} from "@/components/ui/sheet"

const BUYER_EMAIL = process.env.NEXT_PUBLIC_JUDGE_BUYER_EMAIL ?? ""
const BUYER_PASSWORD = process.env.NEXT_PUBLIC_JUDGE_BUYER_PASSWORD ?? ""

const STEPS = [
  "Enter as Lumen Audio (brand) and open the “Lumen Pods launch” deal.",
  "Optionally describe a performance bonus, then press Fund with PayPal and log in with the sandbox buyer below.",
  "Switch to Priya (creator) from the app menu, open the same deal and submit proof for Video 1 (a sample screenshot is provided).",
  "Watch Claude verify the post and pay Priya through PayPal Payouts; payouts above the brand's limit wait for approval.",
  "Back as the brand, close the deal to refund the unspent budget. “Reset demo” in the menu restores everything.",
]

/** Judge guide: the walkthrough and the PayPal sandbox buyer login (sandbox only). */
export function JudgeGuide() {
  return (
    <Sheet>
      <SheetTrigger render={<Button variant="outline" size="sm" />}>Judge guide</SheetTrigger>
      <SheetContent side="right" className="overflow-y-auto">
        <SheetHeader>
          <SheetTitle>Judge guide</SheetTitle>
          <SheetDescription>
            Everything runs on the PayPal sandbox: no real money moves.
          </SheetDescription>
        </SheetHeader>
        <div className="space-y-6 px-4 pb-6">
          <ol className="list-decimal space-y-2 pl-5 text-sm">
            {STEPS.map((step) => (
              <li key={step}>{step}</li>
            ))}
          </ol>
          <div className="rounded-xl border border-border p-4 text-sm">
            <p className="font-medium">PayPal sandbox buyer</p>
            <dl className="mt-2 grid grid-cols-[auto_1fr] gap-x-3 gap-y-1">
              <dt className="text-muted-foreground">Email</dt>
              <dd className="font-mono break-all select-all">{BUYER_EMAIL || "see README"}</dd>
              <dt className="text-muted-foreground">Password</dt>
              <dd className="font-mono select-all">{BUYER_PASSWORD || "see README"}</dd>
            </dl>
          </div>
          <p className="text-sm text-muted-foreground">
            Phone calls are off in the public demo (they cost real money). Negotiation still
            works by email and in the app.
          </p>
        </div>
      </SheetContent>
    </Sheet>
  )
}
