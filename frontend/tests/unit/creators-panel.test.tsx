import { cleanup, render, screen, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { afterEach, describe, expect, it, vi } from "vitest"

import { CreatorsPanel } from "@/components/brief/creators-panel"
import { TooltipProvider } from "@/components/ui/tooltip"
import type { components } from "@/lib/api/schema"

type Preview = components["schemas"]["BriefCreatorPreview"]
type Delta = components["schemas"]["PackageDelta"]
type Plan = components["schemas"]["LaunchRequest"]["channels"][string]

function delta(over: Partial<Delta> = {}): Delta {
  return {
    package_id: "pkg-1",
    package_name: "Launch Trio",
    listed_videos: 3,
    ask_videos: 3,
    latest_videos: null,
    listed_price_cents: 150000,
    ask_price_cents: 120000,
    latest_price_cents: null,
    listed_per_video_cents: 50000,
    ask_per_video_cents: 40000,
    latest_per_video_cents: null,
    lead_time_days: 14,
    days_to_go_live: 30,
    headline: "Same videos · $300 under list (−20%)",
    latest_headline: null,
    flags: [],
    ...over,
  }
}

function preview(id: string, over: Partial<Preview> = {}): Preview {
  return {
    creator_id: id,
    name: `Name ${id}`,
    handle: `${id}_handle`,
    initials: "NA",
    package: {
      id: "pkg-1",
      name: "Launch Trio",
      content_type: "short_video",
      niche: "consumer_tech",
      volume_count: 3,
      volume_basis: "per_contract",
      base_price_cents: 150000,
      per_video_cents: 50000,
      one_liner: "3 videos/contract · $1,500",
      lead_time_days: 14,
      preferred_channel: "email_first",
      addons: [],
    },
    delta: delta(),
    default_channel: "email",
    call_allowed: true,
    excluded_reason: null,
    ...over,
  }
}

function renderPanel(
  creators: Preview[],
  channels: Record<string, Plan> = {},
  onChannel = vi.fn()
) {
  render(
    <TooltipProvider delay={0}>
      <CreatorsPanel
        creators={creators}
        channels={channels}
        onChannel={onChannel}
      />
    </TooltipProvider>
  )
  return onChannel
}

afterEach(cleanup)

describe("CreatorsPanel", () => {
  it("shows each creator's package, delta headline and flags", () => {
    renderPanel(
      [
        preview("arjun", {
          delta: delta({
            flags: ["below_base_price", "lead_time_conflict", "estimated"],
          }),
        }),
        preview("priya", {
          name: "Priya Shah",
          delta: delta({ headline: "+1 video vs package" }),
        }),
      ],
      { arjun: "email", priya: "email" }
    )

    const arjun = screen.getByRole("listitem", { name: "Name arjun" })
    expect(within(arjun).getByText("Launch Trio")).toBeTruthy()
    expect(
      within(arjun).getByText("Same videos · $300 under list (−20%)")
    ).toBeTruthy()
    expect(within(arjun).getByText("Below base price")).toBeTruthy()
    expect(within(arjun).getByText("Lead time conflict")).toBeTruthy()
    expect(within(arjun).getByText("Estimated")).toBeTruthy()

    const priya = screen.getByRole("listitem", { name: "Priya Shah" })
    expect(within(priya).getByText("+1 video vs package")).toBeTruthy()
    expect(within(priya).queryByText("Below base price")).toBeNull()
  })

  it("keeps prices in the number style", () => {
    renderPanel([preview("arjun")], { arjun: "email" })

    const arjun = screen.getByRole("listitem", { name: "Name arjun" })
    expect(within(arjun).getByText("$400").className).toContain("num")
    expect(within(arjun).getByText("$500").className).toContain("num")
    expect(
      within(arjun).getByText("Same videos · $300 under list (−20%)").className
    ).toContain("num")
  })

  it("says what is still needed before a comparison", () => {
    renderPanel([preview("arjun", { delta: null })], { arjun: "email" })

    expect(
      screen.getByText(
        "Set the deliverables, opening ask and go-live date to compare."
      )
    ).toBeTruthy()
  })

  it("marks the chosen channel and reports a change", async () => {
    const user = userEvent.setup()
    const onChannel = renderPanel([preview("arjun")], { arjun: "email" })
    const pressed = (name: string) =>
      screen.getByRole("button", { name }).getAttribute("aria-pressed")

    expect(pressed("Email")).toBe("true")
    expect(pressed("Call")).toBe("false")

    await user.click(screen.getByRole("button", { name: "Call" }))
    expect(onChannel).toHaveBeenCalledWith("arjun", "call")

    // Pressing the chosen channel again does not clear it.
    onChannel.mockClear()
    await user.click(screen.getByRole("button", { name: "Email" }))
    expect(onChannel).not.toHaveBeenCalled()
  })

  it("disables Call without opt-in and says why", async () => {
    const user = userEvent.setup()
    const onChannel = renderPanel([preview("arjun", { call_allowed: false })], {
      arjun: "email",
    })

    const call = screen.getByRole("button", { name: "Call" })
    expect(call).toHaveProperty("disabled", true)
    await user.hover(call.parentElement as HTMLElement)
    expect(await screen.findByText("No phone opt-in")).toBeTruthy()

    await user.click(call)
    expect(onChannel).not.toHaveBeenCalled()
  })

  it("greys out an opted-out creator", () => {
    renderPanel(
      [
        preview("arjun", { excluded_reason: "Opted out of contact" }),
        preview("priya"),
      ],
      { priya: "email" }
    )

    const arjun = screen.getByRole("listitem", { name: "Name arjun" })
    expect(within(arjun).getByText("Opted out of contact")).toBeTruthy()
    expect(within(arjun).queryByRole("button")).toBeNull()
    expect(arjun.dataset.excluded).toBe("true")
    expect(
      within(screen.getByRole("listitem", { name: "Name priya" })).getAllByRole(
        "button"
      )
    ).toHaveLength(2)
  })

  it("marks the highlighted creator", () => {
    render(
      <TooltipProvider>
        <CreatorsPanel
          creators={[preview("arjun"), preview("priya")]}
          channels={{}}
          onChannel={vi.fn()}
          highlighted="priya"
        />
      </TooltipProvider>
    )

    expect(
      screen.getByRole("listitem", { name: "Name priya" }).dataset.highlighted
    ).toBe("true")
    expect(
      screen.getByRole("listitem", { name: "Name arjun" }).dataset.highlighted
    ).toBeUndefined()
  })

  it("explains an empty panel", () => {
    renderPanel([])

    expect(screen.getByText("No creators on this brief")).toBeTruthy()
  })
})
