import {
  cleanup,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import { AwardDialog } from "@/components/board/award-dialog"
import type { components } from "@/lib/api/schema"

type AwardPreview = components["schemas"]["AwardPreview"]
type DealView = components["schemas"]["DealView"]

const h = vi.hoisted(() => ({
  api: { GET: vi.fn(), POST: vi.fn() },
  toast: { info: vi.fn(), error: vi.fn(), success: vi.fn() },
}))

vi.mock("@/hooks/use-api", () => ({ useApi: () => h.api }))
vi.mock("sonner", () => ({ toast: h.toast }))

const AWARD = "/api/v1/threads/{thread_id}/award"
const PREVIEW = "/api/v1/threads/{thread_id}/award/preview"
const DECLINE_REST = "/api/v1/batches/{batch_id}/decline-rest"

function makePreview(over: Partial<AwardPreview> = {}): AwardPreview {
  return {
    agreed: {
      videos: 2,
      format: "short_video",
      price_cents: 100000,
      go_live_by: "2026-12-01",
      conditions: ["No exclusivity"],
      addons: [],
    },
    milestones: [
      { seq: 1, title: "Video 1", amount_cents: 50000, due_date: "2026-12-01" },
      { seq: 2, title: "Video 2", amount_cents: 50000, due_date: "2026-12-01" },
    ],
    over_ceiling_cents: null,
    hired: 0,
    hires_target: 1,
    would_reach_target: false,
    over_target: false,
    open_others: [],
    terms_event_id: 12,
    ...over,
  }
}

const DEAL: DealView = {
  id: "deal-1",
  thread_id: "t1",
  batch_id: "batch-1",
  status: "booked",
  product_name: "Lumen Pods",
  terms: {
    videos: 2,
    format: "short_video",
    price_cents: 100000,
    go_live_by: "2026-12-01",
    conditions: [],
    addons: [],
  },
  milestones: [],
  brand: { name: "Lumen", email: "hello@lumen.test" },
  creator: { name: "Priya", email: "priya@example.com" },
  creator_handle: "priya",
  created_at: "2026-01-01T00:00:00Z",
}

const OTHERS = [
  { id: "c2", name: "Arjun", handle: "arjun", initials: "AR" },
  { id: "c3", name: "Maya", handle: "maya", initials: "MA" },
]

function servePreview(preview: AwardPreview) {
  h.api.POST.mockImplementation(async (path: string) => {
    if (path === PREVIEW) return { data: preview }
    if (path === AWARD) return { data: DEAL }
    if (path === DECLINE_REST) return { data: { closed: ["x"], failed: [] } }
    throw new Error(`unexpected POST ${path}`)
  })
}

function posts(path: string) {
  return h.api.POST.mock.calls.filter(([p]) => p === path)
}

function renderDialog(props: { onAwarded?: (d: DealView) => void } = {}) {
  const onAwarded = props.onAwarded ?? vi.fn()
  const onOpenChange = vi.fn()
  const onStale = vi.fn()
  render(
    <AwardDialog
      threadId="t1"
      creatorName="Priya"
      open
      onOpenChange={onOpenChange}
      onAwarded={onAwarded}
      onStale={onStale}
    />
  )
  return { onAwarded, onOpenChange, onStale }
}

async function dialog() {
  return screen.findByRole("dialog", { name: /Award Priya/ })
}

function confirmButton(d: HTMLElement) {
  return within(d).getByRole("button", { name: "Confirm award" })
}

beforeEach(() => {
  h.api.POST.mockReset()
  h.toast.info.mockReset()
  h.toast.error.mockReset()
  h.toast.success.mockReset()
})

afterEach(cleanup)

describe("AwardDialog", () => {
  it("previews the agreed terms and a payment per video", async () => {
    servePreview(makePreview())
    renderDialog()
    const d = await dialog()
    expect(await within(d).findByText(/2 videos · \$1,000/)).toBeTruthy()
    expect(within(d).getByText("No exclusivity")).toBeTruthy()
    expect(within(d).getByLabelText("Video 1 title")).toBeTruthy()
    expect(within(d).getByLabelText("Video 2 payment")).toBeTruthy()
    expect(posts(PREVIEW)[0]).toEqual([
      PREVIEW,
      { params: { path: { thread_id: "t1" } } },
    ])
    expect(confirmButton(d).hasAttribute("disabled")).toBe(false)
  })

  it("will not confirm payments that do not add up, until they do", async () => {
    const user = userEvent.setup()
    servePreview(makePreview())
    renderDialog()
    const d = await dialog()
    const payment = await within(d).findByLabelText("Video 1 payment")
    await user.clear(payment)
    await user.type(payment, "400")
    expect(
      within(d).getByText(/Payments add up to \$900, not the agreed \$1,000/)
    ).toBeTruthy()
    expect(confirmButton(d).hasAttribute("disabled")).toBe(true)

    await user.clear(payment)
    await user.type(payment, "500")
    expect(confirmButton(d).hasAttribute("disabled")).toBe(false)
  })

  it("awards with the milestones shown, bound to the terms previewed", async () => {
    const user = userEvent.setup()
    servePreview(makePreview())
    const { onAwarded, onOpenChange } = renderDialog()
    const d = await dialog()
    await within(d).findByLabelText("Video 1 title")
    await user.click(confirmButton(d))
    await waitFor(() => expect(posts(AWARD)).toHaveLength(1))
    expect(posts(AWARD)[0]).toEqual([
      AWARD,
      {
        params: { path: { thread_id: "t1" } },
        body: {
          milestones: [
            {
              seq: 1,
              title: "Video 1",
              amount_cents: 50000,
              due_date: "2026-12-01",
            },
            {
              seq: 2,
              title: "Video 2",
              amount_cents: 50000,
              due_date: "2026-12-01",
            },
          ],
          based_on_event_id: 12,
          confirm_over_ceiling: false,
          confirm_over_target: false,
        },
      },
    ])
    await waitFor(() => expect(onAwarded).toHaveBeenCalledWith(DEAL))
    expect(onOpenChange).toHaveBeenCalledWith(false)
    // Nobody to decline: no second call.
    expect(posts(DECLINE_REST)).toHaveLength(0)
  })

  it("needs the over-ceiling confirmation, worded with the amount", async () => {
    const user = userEvent.setup()
    servePreview(makePreview({ over_ceiling_cents: 6600 }))
    renderDialog()
    const d = await dialog()
    const box = await within(d).findByRole("checkbox", {
      name: "Award $66 over my ceiling",
    })
    expect((box as HTMLInputElement).checked).toBe(false)
    expect(confirmButton(d).hasAttribute("disabled")).toBe(true)

    await user.click(box)
    expect(confirmButton(d).hasAttribute("disabled")).toBe(false)
    await user.click(confirmButton(d))
    await waitFor(() => expect(posts(AWARD)).toHaveLength(1))
    expect(posts(AWARD)[0][1].body).toMatchObject({
      confirm_over_ceiling: true,
      confirm_over_target: false,
    })
  })

  it("needs the over-target confirmation", async () => {
    const user = userEvent.setup()
    servePreview(
      makePreview({ over_target: true, hired: 1, hires_target: 1 })
    )
    renderDialog()
    const d = await dialog()
    const box = await within(d).findByRole("checkbox", {
      name: "Hire beyond my target of 1",
    })
    expect(confirmButton(d).hasAttribute("disabled")).toBe(true)
    await user.click(box)
    expect(confirmButton(d).hasAttribute("disabled")).toBe(false)
    await user.click(confirmButton(d))
    await waitFor(() => expect(posts(AWARD)).toHaveLength(1))
    expect(posts(AWARD)[0][1].body).toMatchObject({
      confirm_over_ceiling: false,
      confirm_over_target: true,
    })
  })

  it("offers to decline the rest, checked, and does so after the award", async () => {
    const user = userEvent.setup()
    servePreview(
      makePreview({ would_reach_target: true, open_others: OTHERS })
    )
    const { onAwarded } = renderDialog()
    const d = await dialog()
    const box = await within(d).findByRole("checkbox", {
      name: "Politely decline the remaining 2",
    })
    expect((box as HTMLInputElement).checked).toBe(true)
    expect(within(d).getByText("Arjun, Maya")).toBeTruthy()

    await user.click(confirmButton(d))
    await waitFor(() => expect(posts(DECLINE_REST)).toHaveLength(1))
    expect(posts(DECLINE_REST)[0]).toEqual([
      DECLINE_REST,
      { params: { path: { batch_id: "batch-1" } } },
    ])
    // The award came first.
    const order = h.api.POST.mock.calls.map(([p]) => p)
    expect(order.indexOf(AWARD)).toBeLessThan(order.indexOf(DECLINE_REST))
    await waitFor(() => expect(onAwarded).toHaveBeenCalledWith(DEAL))
  })

  it("keeps the rest when the box is cleared", async () => {
    const user = userEvent.setup()
    servePreview(
      makePreview({ would_reach_target: true, open_others: OTHERS })
    )
    const { onAwarded } = renderDialog()
    const d = await dialog()
    await user.click(
      await within(d).findByRole("checkbox", {
        name: "Politely decline the remaining 2",
      })
    )
    await user.click(confirmButton(d))
    await waitFor(() => expect(onAwarded).toHaveBeenCalled())
    expect(posts(DECLINE_REST)).toHaveLength(0)
  })

  it("does not offer to decline the rest while the target is not reached", async () => {
    servePreview(
      makePreview({ would_reach_target: false, open_others: OTHERS })
    )
    renderDialog()
    const d = await dialog()
    await within(d).findByLabelText("Video 1 title")
    expect(within(d).queryByText(/Politely decline/)).toBeNull()
  })

  it("still reports the award when declining the rest fails", async () => {
    const user = userEvent.setup()
    servePreview(
      makePreview({ would_reach_target: true, open_others: OTHERS })
    )
    h.api.POST.mockImplementation(async (path: string) => {
      if (path === PREVIEW)
        return {
          data: makePreview({ would_reach_target: true, open_others: OTHERS }),
        }
      if (path === AWARD) return { data: DEAL }
      return { error: { detail: { code: "x", message: "No" } } }
    })
    const { onAwarded } = renderDialog()
    const d = await dialog()
    await within(d).findByLabelText("Video 1 title")
    await user.click(confirmButton(d))
    await waitFor(() => expect(onAwarded).toHaveBeenCalledWith(DEAL))
    expect(h.toast.error).toHaveBeenCalled()
  })

  it("shows the server's milestone problems under the editor", async () => {
    const user = userEvent.setup()
    servePreview(makePreview())
    h.api.POST.mockImplementation(async (path: string) => {
      if (path === PREVIEW) return { data: makePreview() }
      return {
        error: {
          detail: {
            code: "milestones_invalid",
            message: "The payment schedule is not valid",
            errors: ["Video 2 is due before the agreed go-live date Dec 1, 2026"],
          },
        },
      }
    })
    const { onAwarded } = renderDialog()
    const d = await dialog()
    await within(d).findByLabelText("Video 1 title")
    await user.click(confirmButton(d))
    expect(
      await within(d).findByText(
        "Video 2 is due before the agreed go-live date Dec 1, 2026"
      )
    ).toBeTruthy()
    expect(onAwarded).not.toHaveBeenCalled()
  })

  it("reloads the preview when the terms moved under it", async () => {
    const user = userEvent.setup()
    let previews = 0
    h.api.POST.mockImplementation(async (path: string) => {
      if (path === PREVIEW) {
        previews += 1
        return {
          data: makePreview({
            terms_event_id: previews === 1 ? 12 : 14,
            agreed: {
              ...makePreview().agreed,
              price_cents: previews === 1 ? 100000 : 90000,
            },
            milestones: [
              {
                seq: 1,
                title: "Video 1",
                amount_cents: previews === 1 ? 50000 : 45000,
                due_date: "2026-12-01",
              },
              {
                seq: 2,
                title: "Video 2",
                amount_cents: previews === 1 ? 50000 : 45000,
                due_date: "2026-12-01",
              },
            ],
          }),
        }
      }
      return {
        error: {
          detail: {
            code: "terms_changed",
            message: "The terms changed",
            terms_event_id: 14,
          },
        },
      }
    })
    const { onAwarded } = renderDialog()
    const d = await dialog()
    await within(d).findByText(/2 videos · \$1,000/)
    await user.click(confirmButton(d))
    expect(await within(d).findByText(/2 videos · \$900/)).toBeTruthy()
    expect(h.toast.info).toHaveBeenCalledWith(
      "Terms changed — review the latest"
    )
    expect(posts(PREVIEW)).toHaveLength(2)
    expect(onAwarded).not.toHaveBeenCalled()
  })

  it("closes and asks the board to reload when the thread can no longer be awarded", async () => {
    const user = userEvent.setup()
    h.api.POST.mockImplementation(async (path: string) =>
      path === PREVIEW
        ? { data: makePreview() }
        : {
            error: {
              detail: { code: "stale_status", message: "It moved on" },
            },
          }
    )
    const { onOpenChange, onStale } = renderDialog()
    const d = await dialog()
    await within(d).findByLabelText("Video 1 title")
    await user.click(confirmButton(d))
    await waitFor(() => expect(onStale).toHaveBeenCalled())
    expect(onOpenChange).toHaveBeenCalledWith(false)
    expect(h.toast.error).toHaveBeenCalledWith("It moved on")
  })
})
