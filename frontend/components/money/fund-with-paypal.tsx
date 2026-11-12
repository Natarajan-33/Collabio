"use client"

import * as React from "react"
import { toast } from "sonner"

import { Button } from "@/components/ui/button"
import { useApi } from "@/hooks/use-api"
import { formatCents } from "@/lib/money"

/**
 * Creates a PayPal order for the deal's full budget and sends the brand to PayPal to
 * approve it. PayPal returns to the deal page (`?funding=return&token=<order id>`), where
 * `MoneyPanel` captures the payment.
 */
export function FundWithPayPal({
  dealId,
  totalCents,
}: {
  dealId: string
  totalCents: number
}) {
  const api = useApi()
  const [busy, setBusy] = React.useState(false)

  async function fund() {
    setBusy(true)
    try {
      const { data } = await api.POST("/api/v1/deals/{deal_id}/funding/order", {
        params: { path: { deal_id: dealId } },
      })
      if (data?.approve_url) {
        window.location.assign(data.approve_url)
        return
      }
      if (data) {
        // An earlier approved PayPal order was captured instead of opening a new checkout.
        toast.success("Your earlier PayPal payment was completed. The deal is funded.")
        window.location.reload()
        return
      }
      toast.error("PayPal could not start the checkout. Try again.")
    } catch {
      toast.error("PayPal could not start the checkout. Try again.")
    }
    setBusy(false)
  }

  return (
    <Button
      type="button"
      onClick={fund}
      disabled={busy}
      className="h-11 bg-[#ffc439] px-5 text-base font-semibold text-[#111] hover:bg-[#f2b92f]"
    >
      {busy ? "Opening PayPal…" : `Fund ${formatCents(totalCents)} with PayPal`}
    </Button>
  )
}
