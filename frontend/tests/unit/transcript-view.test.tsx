import { cleanup, render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { afterEach, describe, expect, it } from "vitest"

import { TranscriptView } from "@/components/board/transcript-view"
import type { components } from "@/lib/api/schema"

afterEach(cleanup)

type Transcript = components["schemas"]["TranscriptView"]

function transcript(over: Partial<Transcript> = {}): Transcript {
  return {
    id: "tr-1",
    kind: "email_in",
    created_at: "2026-01-02T00:00:00Z",
    subject: "Re: Collab offer",
    body_text: "I'd need $1,200",
    raw_text: "Thanks!\n> 3 videos for $1,000\nI'd need $1,200\n-- \nPriya",
    turns: [],
    summary: null,
    ...over,
  }
}

describe("TranscriptView email replies", () => {
  it("keeps the full email behind a toggle", async () => {
    const user = userEvent.setup()
    render(<TranscriptView transcript={transcript()} />)
    expect(screen.getByText("I'd need $1,200")).toBeTruthy()
    expect(screen.queryByText(/3 videos for \$1,000/)).toBeNull()

    const toggle = screen.getByRole("button", { name: "Show full email" })
    expect(toggle.getAttribute("aria-expanded")).toBe("false")
    await user.click(toggle)

    expect(toggle.getAttribute("aria-expanded")).toBe("true")
    expect(screen.getByText(/3 videos for \$1,000/)).toBeTruthy()
    await user.click(screen.getByRole("button", { name: "Hide full email" }))
    expect(screen.queryByText(/3 videos for \$1,000/)).toBeNull()
  })

  it("has no toggle when nothing was cut", () => {
    render(
      <TranscriptView
        transcript={transcript({ raw_text: "I'd need $1,200\n" })}
      />
    )
    expect(screen.queryByRole("button", { name: /full email/ })).toBeNull()
  })

  it("has no toggle for a reply stored before the full text was kept", () => {
    render(<TranscriptView transcript={transcript({ raw_text: null })} />)
    expect(screen.queryByRole("button", { name: /full email/ })).toBeNull()
  })

  it("has no toggle on an email we sent", () => {
    render(<TranscriptView transcript={transcript({ kind: "email_out" })} />)
    expect(screen.queryByRole("button", { name: /full email/ })).toBeNull()
  })
})
