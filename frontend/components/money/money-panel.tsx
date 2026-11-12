"use client"

import * as React from "react"
import { useRouter, useSearchParams } from "next/navigation"
import { toast } from "sonner"

import { BonusTermsEditor } from "@/components/money/bonus-terms-editor"
import { FundWithPayPal } from "@/components/money/fund-with-paypal"
import { Ledger } from "@/components/money/ledger"
import { CloseDeal, MilestoneMoney } from "@/components/money/milestone-money"
import { Button } from "@/components/ui/button"
import { Label } from "@/components/ui/label"
import { MoneyInput } from "@/components/ui/money-input"
import { useApi } from "@/hooks/use-api"
import { useMoneyDoorbell } from "@/hooks/use-money-doorbell"
import type { components } from "@/lib/api/schema"
import { formatCents } from "@/lib/money"
import { captureErrorText } from "@/lib/money/format"

export type MoneyView = components["schemas"]["MoneyView"]
type Viewer = "brand" | "creator"

const STATUS_LABEL: Record<string, string> = {
  booked: "Not funded",
  funded: "Funded",
  completed: "Completed",
}

function Tile({
  label,
  cents,
  hint,
}: {
  label: string
  cents: number
  hint?: string
}) {
  return (
    <div className="rounded-xl border border-border bg-card/60 p-3">
      <p className="text-xs text-muted-foreground">{label}</p>
      <p className="mt-1 num text-lg font-semibold">{formatCents(cents)}</p>
      {hint && <p className="text-xs text-muted-foreground">{hint}</p>}
    </div>
  )
}

function totals(money: MoneyView) {
  const payouts = money.milestones.flatMap((m) => m.payouts)
  const sum = (statuses: string[]) =>
    payouts
      .filter((p) => statuses.includes(p.status))
      .reduce((a, p) => a + p.amount_cents, 0)
  return {
    funded:
      money.funding?.status === "captured" ? money.funding.amount_cents : 0,
    paid: sum(["success"]),
    pending: sum(["awaiting_approval", "approved", "sent"]),
    refunded: money.funding?.refunded_cents ?? 0,
  }
}

function AutoApproveLimit({ initial }: { initial: number }) {
  const api = useApi()
  const [cents, setCents] = React.useState<number | null>(initial)
  const [saving, setSaving] = React.useState(false)

  async function save() {
    if (cents === null) return
    setSaving(true)
    const { data } = await api.PUT("/api/v1/me/brand/auto-approve-limit", {
      body: { cents },
    })
    setSaving(false)
    if (data)
      toast.success(
        `Payouts up to ${formatCents(data.cents)} are sent automatically.`
      )
    else toast.error("Could not save the limit.")
  }

  return (
    <div className="flex flex-wrap items-end gap-2">
      <div className="space-y-1">
        <Label htmlFor="auto-limit">Auto-approve payouts up to</Label>
        <p className="text-xs text-muted-foreground">
          Set $0 to review every payout yourself.
        </p>
        <MoneyInput
          id="auto-limit"
          value={cents}
          onValueChange={setCents}
          className="w-32"
        />
      </div>
      <Button type="button" variant="outline" onClick={save} disabled={saving}>
        Save
      </Button>
      <p className="w-full text-xs text-muted-foreground">
        Larger payouts, or any Claude is unsure about, wait for your approval.
      </p>
    </div>
  )
}

/**
 * The deal's money: funding through PayPal (brand), what each milestone has earned, every
 * PayPal movement and what is still held. Updates live while money moves.
 */
export function MoneyPanel({
  viewer,
  dealId,
}: {
  viewer: Viewer
  dealId: string
}) {
  const api = useApi()
  const router = useRouter()
  const params = useSearchParams()
  const [money, setMoney] = React.useState<MoneyView | null>(null)
  const [failed, setFailed] = React.useState(false)
  const captureStarted = React.useRef(false)

  const reload = React.useCallback(async () => {
    const { data } = await api.GET("/api/v1/deals/{deal_id}/money", {
      params: { path: { deal_id: dealId } },
    })
    if (data) setMoney(data)
    else setFailed(true)
  }, [api, dealId])

  // Poll while Claude is checking a post or a payout is in flight; ring on ledger inserts.
  const inFlight =
    money?.milestones.some(
      (m) =>
        m.submissions[0]?.status === "submitted" ||
        m.payouts.some((p) => p.status === "sent" || p.status === "approved")
    ) ?? false
  useMoneyDoorbell(dealId, () => void reload(), { live: inFlight })

  React.useEffect(() => {
    let gone = false
    void (async () => {
      const { data } = await api.GET("/api/v1/deals/{deal_id}/money", {
        params: { path: { deal_id: dealId } },
      })
      if (gone) return
      if (data) setMoney(data)
      else setFailed(true)
    })()
    return () => {
      gone = true
    }
  }, [api, dealId])

  // PayPal sends the brand back with ?funding=return&token=<order id>: capture once.
  React.useEffect(() => {
    const token = params.get("token")
    if (viewer !== "brand" || params.get("funding") !== "return" || !token)
      return
    if (captureStarted.current) return
    captureStarted.current = true
    void (async () => {
      const { data, error } = await api.POST(
        "/api/v1/deals/{deal_id}/funding/capture",
        {
          params: { path: { deal_id: dealId } },
          body: { order_id: token },
        }
      )
      if (data) {
        setMoney(data)
        toast.success("Deal funded through PayPal.")
      } else {
        toast.error(captureErrorText(error))
      }
      router.replace(`/brand/deals/${dealId}`)
    })()
  }, [api, dealId, params, router, viewer])

  if (failed)
    return (
      <p className="text-sm text-destructive">
        Could not load the deal&apos;s money.
      </p>
    )
  if (!money)
    return <p className="text-sm text-muted-foreground">Loading money…</p>

  const t = totals(money)
  const unfunded = money.deal_status === "booked"

  return (
    <section
      aria-labelledby="money-heading"
      className="space-y-5 rounded-2xl border border-border p-5"
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 id="money-heading" className="text-lg font-semibold">
          Money
        </h2>
        <span className="rounded-full border border-border px-2.5 py-0.5 text-xs">
          {STATUS_LABEL[money.deal_status] ?? money.deal_status} · PayPal
          sandbox
        </span>
      </div>

      {unfunded && viewer === "brand" && (
        <div className="space-y-5">
          <BonusTermsEditor
            dealId={dealId}
            initialText={money.bonus_source_text}
            initialTerms={money.bonus_terms}
            onSaved={reload}
          />
          {money.auto_approve_limit_cents !== null && (
            <AutoApproveLimit initial={money.auto_approve_limit_cents} />
          )}
          <div className="flex flex-wrap items-center gap-3 border-t border-border pt-4">
            <FundWithPayPal
              dealId={dealId}
              totalCents={money.funding_total_cents}
            />
            <p className="text-sm text-muted-foreground">
              {formatCents(money.funding_total_cents)} = the agreed price plus
              the most the bonus can pay. Whatever isn&apos;t earned is refunded
              when you close the deal.
            </p>
          </div>
        </div>
      )}

      {unfunded && viewer === "creator" && (
        <p className="text-sm text-muted-foreground">
          The brand hasn&apos;t funded this deal yet. You&apos;ll be able to
          submit proof as soon as the budget is held.
        </p>
      )}

      {!unfunded && (
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          <Tile label="Funded" cents={t.funded} />
          <Tile label="Paid to creator" cents={t.paid} />
          <Tile label="Pending" cents={t.pending} />
          <Tile
            label={
              money.deal_status === "completed" ? "Refunded" : "Still held"
            }
            cents={
              money.deal_status === "completed"
                ? t.refunded
                : money.available_cents
            }
          />
        </div>
      )}

      {!unfunded && (
        <MilestoneMoney
          money={money}
          viewer={viewer}
          onChange={() => void reload()}
          onView={setMoney}
        />
      )}

      {!unfunded && viewer === "brand" && (
        <CloseDeal dealId={dealId} money={money} onView={setMoney} />
      )}

      {!unfunded && (
        <div className="space-y-2">
          <h3 className="font-medium">Ledger</h3>
          <Ledger entries={money.ledger} />
        </div>
      )}
    </section>
  )
}
