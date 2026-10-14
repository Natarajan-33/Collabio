import {
  Table,
  TableBody,
  TableCell,
  TableFooter,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import type { components } from "@/lib/api/schema"
import { formatDay, termsSummary } from "@/lib/deal/terms"
import { formatCents } from "@/lib/money"
import { contentTypeLabel } from "@/lib/vocab"

type DealView = components["schemas"]["DealView"]

/**
 * A booked deal: what was agreed, the payment schedule, and how to reach the other side.
 * The brand sees the creator and the creator sees the brand; the contact address is
 * shown only here, because a booking is what reveals it.
 */
export function DealSummary({
  deal,
  viewer,
}: {
  deal: DealView
  viewer: "brand" | "creator"
}) {
  const { terms, milestones } = deal
  const counterpart = viewer === "brand" ? deal.creator : deal.brand
  const total = milestones.reduce((sum, m) => sum + m.amount_cents, 0)

  return (
    <div data-slot="deal-summary" className="flex flex-col gap-6">
      <section className="flex flex-col gap-2">
        <h3 className="text-sm font-medium text-muted-foreground">Terms</h3>
        <p className="num text-lg">{termsSummary(terms)}</p>
        <p className="text-sm text-muted-foreground">
          {contentTypeLabel(terms.format)}
        </p>
        {terms.conditions.length > 0 || terms.addons.length > 0 ? (
          <ul className="flex flex-wrap gap-2">
            {[...terms.conditions, ...terms.addons].map((text, index) => (
              <li
                key={`${text}-${index}`}
                className="inline-flex h-7 items-center rounded-full border bg-muted/50 px-3 text-sm"
              >
                {text}
              </li>
            ))}
          </ul>
        ) : null}
      </section>

      <section className="flex flex-col gap-2">
        <h3 className="text-sm font-medium text-muted-foreground">
          Payment schedule
        </h3>
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead className="w-10">#</TableHead>
              <TableHead>Milestone</TableHead>
              <TableHead>Due</TableHead>
              <TableHead className="text-right">Amount</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {milestones.map((m) => (
              <TableRow key={m.id}>
                <TableCell className="num">{m.seq}</TableCell>
                <TableCell className="whitespace-normal">{m.title}</TableCell>
                <TableCell className="num">{formatDay(m.due_date)}</TableCell>
                <TableCell className="text-right num">
                  {formatCents(m.amount_cents)}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
          <TableFooter>
            <TableRow>
              <TableCell colSpan={3}>Total</TableCell>
              <TableCell className="text-right num">
                {formatCents(total)}
              </TableCell>
            </TableRow>
          </TableFooter>
        </Table>
      </section>

      <section className="flex flex-col gap-1">
        <h3 className="text-sm font-medium text-muted-foreground">
          {viewer === "brand" ? "Creator" : "Brand"}
        </h3>
        <p className="font-medium">{counterpart.name}</p>
        {counterpart.email ? (
          <a
            href={`mailto:${counterpart.email}`}
            className="w-fit text-sm underline underline-offset-4"
          >
            {counterpart.email}
          </a>
        ) : null}
      </section>
    </div>
  )
}
