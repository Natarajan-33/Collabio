"use client"

import * as React from "react"
import { toast } from "sonner"

import { SubmitProofDialog } from "@/components/money/submit-proof-dialog"
import { VerdictCard } from "@/components/money/verdict-card"
import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { useApi } from "@/hooks/use-api"
import type { components } from "@/lib/api/schema"
import { formatCents } from "@/lib/money"

type MoneyView = components["schemas"]["MoneyView"]
type Milestone = MoneyView["milestones"][number]
type Viewer = "brand" | "creator"

const SUBMITTABLE = new Set(["funded", "needs_changes", "verified", "paid"])

const STATUS: Record<string, string> = {
  funded: "Ready for proof",
  submitted: "Checking",
  needs_changes: "Changes requested",
  verified: "Verified",
  paid: "Paid",
}

function errorText(error: unknown): string {
  const detail = (error as { detail?: unknown })?.detail
  if (detail && typeof detail === "object" && "code" in detail) {
    const d = detail as { code: string; debug_id?: string }
    return `PayPal said: ${d.code}${d.debug_id ? ` (debug ${d.debug_id})` : ""}`
  }
  return typeof detail === "string"
    ? detail.replaceAll("_", " ")
    : "Something went wrong."
}

function ApprovalActions({
  payoutId,
  onDone,
}: {
  payoutId: string
  onDone: (view: MoneyView) => void
}) {
  const api = useApi()
  const [busy, setBusy] = React.useState(false)
  const [rejecting, setRejecting] = React.useState(false)
  const [reason, setReason] = React.useState("")

  async function approve() {
    setBusy(true)
    const { data, error } = await api.POST(
      "/api/v1/payouts/{payout_id}/approve",
      {
        params: { path: { payout_id: payoutId } },
      }
    )
    setBusy(false)
    if (data) {
      const sent = data.milestones
        .flatMap((m) => m.payouts)
        .find((p) => p.id === payoutId)
      if (sent?.status === "failed")
        toast.error("PayPal refused the payout. See the details below.")
      else toast.success("Approved. The payout is on its way through PayPal.")
      onDone(data)
    } else toast.error(errorText(error))
  }

  async function reject() {
    setBusy(true)
    const { data, error } = await api.POST(
      "/api/v1/payouts/{payout_id}/reject",
      {
        params: { path: { payout_id: payoutId } },
        body: { reason },
      }
    )
    setBusy(false)
    if (data) {
      setRejecting(false)
      toast.success("Rejected. The creator has been asked to fix the post.")
      onDone(data)
    } else toast.error(errorText(error))
  }

  return (
    <div className="flex flex-wrap items-center gap-2 rounded-lg border border-voice/40 bg-voice/5 p-3">
      <p className="mr-auto text-sm">This payout needs your approval.</p>
      <Button type="button" size="sm" onClick={approve} disabled={busy}>
        Approve payout
      </Button>
      <Button
        type="button"
        size="sm"
        variant="outline"
        onClick={() => setRejecting(true)}
        disabled={busy}
      >
        Reject
      </Button>
      <Dialog open={rejecting} onOpenChange={setRejecting}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Reject this payout</DialogTitle>
            <DialogDescription>
              The creator sees your reason and can resubmit.
            </DialogDescription>
          </DialogHeader>
          <Input
            aria-label="Reason"
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            placeholder="e.g. The product isn't shown in the video"
          />
          <DialogFooter>
            <Button
              type="button"
              onClick={reject}
              disabled={busy || !reason.trim()}
            >
              Reject payout
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}

function MilestoneRow({
  milestone,
  viewer,
  dealOpen,
  onChange,
  onView,
}: {
  milestone: Milestone
  viewer: Viewer
  dealOpen: boolean
  onChange: () => void
  onView: (view: MoneyView) => void
}) {
  const api = useApi()
  const [proofOpen, setProofOpen] = React.useState(false)
  const latest = milestone.submissions[0]
  const latestPayout = milestone.payouts[0]

  async function retry() {
    if (!latest) return
    const { error } = await api.POST(
      "/api/v1/submissions/{submission_id}/retry",
      {
        params: { path: { submission_id: latest.id } },
      }
    )
    if (error) toast.error(errorText(error))
    else onChange()
  }

  return (
    <li className="space-y-3 py-4 first:pt-0 last:pb-0">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <p className="font-medium">{milestone.title}</p>
          <p className="text-xs text-muted-foreground">
            Agreed {formatCents(milestone.amount_cents)} · earned so far{" "}
            {formatCents(milestone.owed_cents)} ·{" "}
            {STATUS[milestone.status] ?? milestone.status}
          </p>
        </div>
        {viewer === "creator" &&
          dealOpen &&
          SUBMITTABLE.has(milestone.status) && (
            <Button type="button" size="sm" onClick={() => setProofOpen(true)}>
              {latest ? "Submit new proof" : "Submit proof"}
            </Button>
          )}
      </div>
      {latest && <VerdictCard submission={latest} payout={latestPayout} />}
      {latest?.run_status === "error" && viewer === "creator" && (
        <Button type="button" size="sm" variant="outline" onClick={retry}>
          Retry verification
        </Button>
      )}
      {viewer === "brand" &&
        dealOpen &&
        latestPayout?.status === "awaiting_approval" && (
          <ApprovalActions payoutId={latestPayout.id} onDone={onView} />
        )}
      {viewer === "creator" && (
        <SubmitProofDialog
          milestoneId={milestone.id}
          title={milestone.title}
          open={proofOpen}
          onOpenChange={setProofOpen}
          onSubmitted={onChange}
        />
      )}
    </li>
  )
}

/** Every milestone with its proof, Claude's verdict and the PayPal payout. */
export function MilestoneMoney({
  money,
  viewer,
  onChange,
  onView,
}: {
  money: MoneyView
  viewer: Viewer
  onChange: () => void
  onView: (view: MoneyView) => void
}) {
  return (
    <div className="space-y-2">
      <h3 className="font-medium">Deliverables</h3>
      <ul className="divide-y divide-border">
        {money.milestones.map((m) => (
          <MilestoneRow
            key={m.id}
            milestone={m}
            viewer={viewer}
            dealOpen={money.deal_status === "funded"}
            onChange={onChange}
            onView={onView}
          />
        ))}
      </ul>
    </div>
  )
}

/** The brand's "close and refund" action, with the refund shown before confirming. */
export function CloseDeal({
  dealId,
  money,
  onView,
}: {
  dealId: string
  money: MoneyView
  onView: (view: MoneyView) => void
}) {
  const api = useApi()
  const [open, setOpen] = React.useState(false)
  const [busy, setBusy] = React.useState(false)
  if (money.deal_status !== "funded") return null

  async function close() {
    setBusy(true)
    const { data, error } = await api.POST("/api/v1/deals/{deal_id}/close", {
      params: { path: { deal_id: dealId } },
    })
    setBusy(false)
    if (data) {
      setOpen(false)
      toast.success(
        "Deal closed. The unspent budget was refunded through PayPal."
      )
      onView(data)
    } else toast.error(errorText(error))
  }

  return (
    <div className="flex flex-wrap items-center gap-3 border-t border-border pt-4">
      <Button
        type="button"
        variant="outline"
        onClick={() => setOpen(true)}
        disabled={!money.can_close}
      >
        Close deal &amp; refund
      </Button>
      <p className="text-sm text-muted-foreground">
        {money.can_close
          ? `Refunds ${formatCents(money.available_cents)} that the creator didn't earn.`
          : "Available once every video is paid (or a week after the go-live date)."}
      </p>
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Close the deal?</DialogTitle>
            <DialogDescription>
              {formatCents(money.available_cents)} goes back to you through
              PayPal. Payouts still waiting for approval are cancelled.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button type="button" onClick={close} disabled={busy}>
              {busy ? "Refunding…" : "Close and refund"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
