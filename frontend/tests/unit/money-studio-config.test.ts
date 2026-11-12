import { describe, expect, it } from "vitest"

import {
  buildMoneyData,
  moneyReport,
  type MoneyRows,
} from "@/components/money-dashboard/studio-config"

const rows: MoneyRows = {
  deals: [
    { id: "d1", title: "A", funded: 100000, creator_id: "c1" },
    { id: "d2", title: "B", funded: 50000, creator_id: "c2" },
  ],
  milestones: [
    { id: "m1", deal_id: "d1", views: 1000 },
    { id: "m2", deal_id: "d1", views: 2000 },
    { id: "m3", deal_id: "d2", views: 0 },
  ],
  payouts: [
    { id: "p1", deal_id: "d1", milestone_id: "m1", creator_id: "c1", status: "success", amount: 40000 },
    { id: "p2", deal_id: "d1", milestone_id: "m2", creator_id: "c1", status: "success", amount: 30000 },
    { id: "p3", deal_id: "d1", milestone_id: "m2", creator_id: "c1", status: "awaiting_approval", amount: 9000 },
    { id: "p4", deal_id: "d2", milestone_id: "m3", creator_id: "c2", status: "failed", amount: 5000 },
  ],
  money_events: [],
  creators: [
    { id: "c1", name: "Ana" },
    { id: "c2", name: "Ben" },
  ],
}

type Source = { id: string; data: Record<string, unknown>[]; fields?: { id: string }[] }
const source = (id: string) =>
  (buildMoneyData(rows).sources as unknown as Source[]).find((s) => s.id === id)!

describe("buildMoneyData", () => {
  it("gives each deal the sum of its successful payouts", () => {
    const deals = source("deals").data
    expect(deals.map((d) => [d.id, d.paid])).toEqual([
      ["d1", 70000],
      ["d2", 0],
    ])
    expect(source("deals").fields?.some((f) => f.id === "paid")).toBe(true)
  })

  it("gives each creator paid, verified views and cost per 1K views", () => {
    const creators = source("creators").data
    expect(creators.map((c) => [c.id, c.paid, c.views, c.costPer1k])).toEqual([
      ["c1", 70000, 3000, (70000 / 3000) * 1000],
      ["c2", 0, 0, null],
    ])
    const ids = source("creators").fields?.map((f) => f.id)
    expect(ids).toEqual(expect.arrayContaining(["paid", "views", "costPer1k"]))
  })

  it("keeps the deals grid on deal-level measures only (no fan-out)", () => {
    const grid = moneyReport.pages[0].widgets!.deals as {
      dataMapping: { cols: { id: string }[] }
    }
    const ids = grid.dataMapping.cols.map((c) => c.id)
    expect(ids).toContain("deals.paid")
    expect(ids.every((id) => id.startsWith("deals."))).toBe(true)
  })
})

describe("studioLayout", () => {
  it("gives AG Studio concrete layout colors from the app's tokens", async () => {
    const { studioLayout } = await import("@/components/money-dashboard/studio-config")
    const seen: string[] = []
    const layout = studioLayout((token) => {
      seen.push(token)
      return `#${token.length.toString(16).padStart(6, "0")}`
    })
    expect(seen.sort()).toEqual(["background", "border", "card"])
    expect(layout).toMatchObject({
      widgetBorderEnabled: true,
      backgroundColor: "#00000a",
      widgetBackgroundColor: "#000004",
      widgetBorderColor: "#000006",
    })
  })
})

describe("bonus KPI", () => {
  it("counts bonus actually paid (success payouts), not every payout's cumulative figures", () => {
    const widget = moneyReport.pages[0].widgets!["kpi-bonus"] as {
      dataMapping: { value: { id: string }[] }
      format: { title: { text: string } }
    }
    expect(widget.dataMapping.value[0].id).toBe("payouts.paid_bonus")
    expect(widget.format.title.text).toBe("Bonus paid")
    const fields = (buildMoneyData(rows).sources as unknown as Source[])
      .find((s) => s.id === "payouts")!
      .fields!.map((f) => f.id)
    expect(fields).toEqual(expect.arrayContaining(["paid_base", "paid_bonus"]))
  })
})

describe("buildMoneyTheme", () => {
  it("gives AG Studio concrete colours (charts draw on canvas and cannot read var())", async () => {
    const { buildMoneyTheme, moneyThemeParams } = await import(
      "@/components/money-dashboard/studio-config"
    )
    const seen: string[] = []
    const params = moneyThemeParams((token) => {
      seen.push(token)
      return "#123456"
    })
    expect(buildMoneyTheme(() => "#000000")).toBeTruthy()
    const json = JSON.stringify(params)
    expect(json).not.toContain("var(")
    expect(seen).toEqual(expect.arrayContaining(["foreground", "card", "background", "border"]))
  })
})

describe("PayPal activity", () => {
  it("shows every money movement with its PayPal id on the default dashboard", () => {
    const widget = moneyReport.pages[0].widgets!["paypal-activity"] as {
      type: string
      dataMapping: { cols: { id: string }[] }
    }
    expect(widget.type).toBe("grid")
    expect(widget.dataMapping.cols.map((c) => c.id)).toEqual(
      expect.arrayContaining(["ledger.date", "ledger.kind", "ledger.amount", "ledger.paypal_ref"])
    )
    const ledger = (buildMoneyData(rows).sources as unknown as Source[]).find(
      (s) => s.id === "ledger"
    )!
    expect(ledger.fields!.map((f) => f.id)).toContain("paypal_ref")
  })
})
