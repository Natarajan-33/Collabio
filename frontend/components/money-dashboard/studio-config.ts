// AG Studio configuration for the brand's money dashboard: data sources over the backend's
// flat money tables (GET /api/v1/money/dashboard), a default report, and a theme built from
// the app's design tokens so Studio renders as part of the page in light and dark.

import {
  studioTheme,
  type AgDataSourcesDefinition,
  type AgFieldDefinition,
  type AgFormat,
  type AgPageState,
  type AgRelationDefinition,
  type AgReportState,
  type AgWidgetLayoutState,
} from "ag-studio"

type Row = Record<string, unknown>
export type MoneyRows = {
  deals: Row[]
  milestones: Row[]
  payouts: Row[]
  money_events: Row[]
  creators: Row[]
}

type FieldSpec = [id: string, name: string, format: AgFormat, hide?: boolean]
const fields = (specs: FieldSpec[]): AgFieldDefinition[] =>
  specs.map(([id, name, format, hide]) => ({
    id,
    name,
    format,
    ...(hide && { hide }),
  }))

const manyToOne = (
  id: string,
  source: string,
  target: string
): AgRelationDefinition => {
  const [sourceTable, sourceField] = source.split(".")
  const [targetTable, targetField] = target.split(".")
  return {
    id,
    source: { tableId: sourceTable, fieldId: sourceField },
    target: { tableId: targetTable, fieldId: targetField },
    type: "many-to-one",
  }
}

const CALENDAR = "calendar"
const onCalendar = (
  tableId: string,
  fieldId: string
): AgRelationDefinition => ({
  id: `${tableId}-${fieldId}-calendar`,
  source: { tableId, fieldId },
  target: { calendarId: CALENDAR },
  truncate: "day",
})

const num = (v: unknown) => (typeof v === "number" ? v : Number(v ?? 0))

const paidWhere = (rows: MoneyRows, key: string, id: unknown) =>
  rows.payouts
    .filter((p) => p[key] === id && p.status === "success")
    .reduce((sum, p) => sum + num(p.amount), 0)

/** Adds what each video has been paid and its effective cost per 1,000 views. */
function enrichMilestones(rows: MoneyRows): Row[] {
  return rows.milestones.map((m) => {
    const paid = paidWhere(rows, "milestone_id", m.id)
    const views = num(m.views)
    return { ...m, paid, costPer1k: views > 0 ? (paid / views) * 1000 : null }
  })
}

/** Adds what each deal has paid out, so deal-level grids never join to milestones (fan-out). */
function enrichDeals(rows: MoneyRows): Row[] {
  return rows.deals.map((d) => ({ ...d, paid: paidWhere(rows, "deal_id", d.id) }))
}

/** Adds each creator's paid total, verified views and effective cost per 1,000 views. */
function enrichCreators(rows: MoneyRows): Row[] {
  return rows.creators.map((c) => {
    const dealIds = new Set(rows.deals.filter((d) => d.creator_id === c.id).map((d) => d.id))
    const views = rows.milestones
      .filter((m) => dealIds.has(m.deal_id))
      .reduce((sum, m) => sum + num(m.views), 0)
    const paid = paidWhere(rows, "creator_id", c.id)
    return { ...c, paid, views, costPer1k: views > 0 ? (paid / views) * 1000 : null }
  })
}

export function buildMoneyData(rows: MoneyRows): AgDataSourcesDefinition {
  const dates = [
    ...rows.payouts.map((p) => p.date),
    ...rows.money_events.map((e) => e.date),
  ]
    .filter((d): d is string => typeof d === "string")
    .sort()
  const today = new Date().toISOString().slice(0, 10)
  return {
    description:
      "A brand's creator-sponsorship money on Collabio, from the PayPal sandbox. Deals are funded " +
      "through PayPal Checkout; each video (milestone) is paid to the creator through PayPal " +
      "Payouts once Claude verifies the post; unspent budget is refunded when a deal closes. " +
      "All amounts are USD. Payout status 'success' means paid; 'awaiting_approval' waits for the brand.",
    sources: [
      {
        id: "deals",
        description: "One row per sponsorship deal.",
        data: enrichDeals(rows),
        fields: fields([
          ["id", "Deal ID", "textFormat", true],
          ["title", "Deal", "textFormat"],
          ["creator_id", "Creator ID", "textFormat", true],
          ["status", "Deal Status", "textFormat"],
          ["videos", "Videos", "integerFormat"],
          ["agreed", "Agreed Price", "currencyFormat"],
          ["funded", "Funded", "currencyFormat"],
          ["paid", "Paid to Creator", "currencyFormat"],
          ["refunded", "Refunded", "currencyFormat"],
          ["go_live_by", "Go Live By", "dateFormat"],
          ["created_at", "Created", "dateFormat"],
        ]),
      },
      {
        id: "milestones",
        name: "Videos",
        description:
          "One row per delivered video. Views are the best count Claude verified.",
        data: enrichMilestones(rows),
        fields: fields([
          ["id", "Video ID", "textFormat", true],
          ["deal_id", "Deal ID", "textFormat", true],
          ["title", "Video", "textFormat"],
          ["status", "Video Status", "textFormat"],
          ["agreed", "Agreed for Video", "currencyFormat"],
          ["views", "Verified Views", "integerFormat"],
          ["paid", "Paid for Video", "currencyFormat"],
          ["costPer1k", "Cost per 1K Views", "currencyFormat"],
        ]),
      },
      {
        id: "payouts",
        description:
          "PayPal payouts to creators: base pay plus performance bonus.",
        data: rows.payouts,
        fields: fields([
          ["id", "Payout ID", "textFormat", true],
          ["deal_id", "Deal ID", "textFormat", true],
          ["milestone_id", "Video ID", "textFormat", true],
          ["creator_id", "Creator ID", "textFormat", true],
          ["status", "Payout Status", "textFormat"],
          ["amount", "Payout", "currencyFormat"],
          ["base", "Base Pay", "currencyFormat"],
          ["bonus", "Bonus Pay", "currencyFormat"],
          ["date", "Payout Date", "dateFormat"],
        ]),
      },
      {
        id: "ledger",
        name: "Money Ledger",
        description:
          "Every PayPal money movement: funded, payout_sent, payout_succeeded, refunded…",
        data: rows.money_events,
        fields: fields([
          ["id", "Event ID", "textFormat", true],
          ["deal_id", "Deal ID", "textFormat", true],
          ["kind", "Movement", "textFormat"],
          ["amount", "Amount", "currencyFormat"],
          ["date", "Date", "dateFormat"],
        ]),
      },
      {
        id: "creators",
        description:
          "One row per creator, with what they were paid and their effective cost per 1,000 verified views.",
        data: enrichCreators(rows),
        fields: fields([
          ["id", "Creator ID", "textFormat", true],
          ["name", "Creator", "textFormat"],
          ["handle", "Handle", "textFormat"],
          ["paid", "Paid to Creator", "currencyFormat"],
          ["views", "Creator Verified Views", "integerFormat"],
          ["costPer1k", "Creator Cost per 1K Views", "currencyFormat"],
        ]),
      },
    ],
    relationships: [
      manyToOne("deal-creator", "deals.creator_id", "creators.id"),
      manyToOne("milestone-deal", "milestones.deal_id", "deals.id"),
      manyToOne("payout-milestone", "payouts.milestone_id", "milestones.id"),
      manyToOne("payout-creator", "payouts.creator_id", "creators.id"),
      manyToOne("ledger-deal", "ledger.deal_id", "deals.id"),
      onCalendar("payouts", "date"),
      onCalendar("ledger", "date"),
    ],
    calendars: [
      {
        id: CALENDAR,
        label: "Calendar",
        range: {
          from: { type: "date", value: dates[0] ?? today },
          to: { type: "date", value: dates.at(-1) ?? today },
        },
        fragments: ["year", "quarter", "month", "week", "day", "dayOfWeek"],
      },
    ],
  }
}

// --- Default report -----------------------------------------------------------------------

const at = (
  xTrack: number,
  yTrack: number,
  xSpan: number,
  ySpan: number
): AgWidgetLayoutState => ({
  xTrack,
  yTrack,
  xSpan,
  ySpan,
})
const title = (text: string) => ({ title: { enabled: true, text } })
const sum = (id: string) => ({ id, aggregation: "sum" as const })
const kpi = (
  text: string,
  value: { id: string; aggregation: "sum" | "avg" }
) => ({
  type: "value" as const,
  dataMapping: { value: [value] },
  format: title(text),
})

const overview: AgPageState = {
  id: "money",
  widgets: {
    "kpi-funded": kpi("Funded through PayPal", sum("deals.funded")),
    "kpi-paid": kpi("Paid to creators", sum("milestones.paid")),
    "kpi-bonus": kpi("Bonus pay (all payouts)", sum("payouts.bonus")),
    "kpi-refunded": kpi("Refunded to you", sum("deals.refunded")),
    "paid-by-creator": {
      type: "column-chart-stacked",
      dataMapping: {
        categoryKey: [{ id: "creators.name" }],
        valueKey: [sum("payouts.amount")],
        legendKey: [{ id: "payouts.status" }],
      },
      format: {
        ...title("Payouts by creator and status"),
        style: { theme: { common: { legend: { enabled: true } } } },
      },
    },
    "by-status": {
      type: "donut-chart",
      dataMapping: {
        categoryKey: [{ id: "payouts.status" }],
        valueKey: [sum("payouts.amount")],
      },
      format: title("Payout value by status"),
    },
    "cost-per-1k": {
      type: "bar-chart-grouped",
      dataMapping: {
        categoryKey: [{ id: "deals.title" }],
        valueKey: [{ id: "milestones.costPer1k", aggregation: "avg" }],
      },
      format: title("Effective cost per 1K views, by deal"),
    },
    deals: {
      type: "grid",
      dataMapping: {
        cols: [
          { id: "deals.title" },
          { id: "deals.status" },
          sum("deals.agreed"),
          sum("deals.funded"),
          sum("deals.paid"),
          sum("deals.refunded"),
        ],
      },
      format: title("Deals"),
    },
  },
  widgetLayout: {
    "kpi-funded": at(0, 0, 6, 7),
    "kpi-paid": at(6, 0, 6, 7),
    "kpi-bonus": at(12, 0, 6, 7),
    "kpi-refunded": at(18, 0, 6, 7),
    "paid-by-creator": at(0, 7, 14, 20),
    "by-status": at(14, 7, 10, 20),
    "cost-per-1k": at(0, 27, 10, 20),
    deals: at(10, 27, 14, 20),
  },
}

export const moneyReport: AgReportState = {
  selectedPageId: overview.id,
  pages: [overview],
}

// --- Theme ------------------------------------------------------------------------------

/**
 * AG Studio's layout panel seeds its color pickers from the theme, and a `var(--token)` theme
 * value reaches the picker as a non-string (it crashes "Edit dashboard"). Give the layout
 * concrete colors resolved from the app's tokens instead.
 */
export function studioLayout(resolve: (token: string) => string) {
  return {
    widgetBorderEnabled: true,
    backgroundColor: resolve("background"),
    widgetBackgroundColor: resolve("card"),
    widgetBorderColor: resolve("border"),
  }
}

/** A CSS color token from the document as #rrggbb (canvas normalises oklch and friends). */
export function resolveCssToken(token: string, fallback = "#ffffff"): string {
  if (typeof document === "undefined") return fallback
  const raw = getComputedStyle(document.documentElement)
    .getPropertyValue(`--${token}`)
    .trim()
  const ctx = document.createElement("canvas").getContext("2d", { willReadFrequently: true })
  if (!raw || !ctx) return fallback
  ctx.fillStyle = fallback
  ctx.fillStyle = raw
  ctx.fillRect(0, 0, 1, 1)
  const [r, g, b] = ctx.getImageData(0, 0, 1, 1).data
  return `#${[r, g, b].map((n) => n.toString(16).padStart(2, "0")).join("")}`
}

const v = (name: string) => `var(--${name})`

export const moneyTheme = studioTheme.withParams({
  fontFamily: "inherit",
  fontSize: 14,
  textColor: v("foreground"),
  foregroundColor: v("foreground"),
  subtleTextColor: v("muted-foreground"),
  backgroundColor: v("card"),
  borderColor: v("border"),
  accentColor: v("voice"),
  studioWrapperBorder: false,
  studioWrapperBackgroundColor: v("background"),
  studioCanvasBorder: false,
  studioCanvasShadow: false,
  studioCanvasBackgroundColor: v("background"),
})
