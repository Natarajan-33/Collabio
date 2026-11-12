import { cleanup, render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { afterEach, describe, expect, it, vi } from "vitest"

const post = vi.fn()
vi.mock("@/hooks/use-api", () => ({ useApi: () => ({ POST: post, PUT: vi.fn() }) }))

import { BonusTermsEditor } from "@/components/money/bonus-terms-editor"

const renderEditor = () =>
  render(
    <BonusTermsEditor dealId="d1" initialText={null} initialTerms={null} onSaved={() => {}} />
  )

afterEach(cleanup)

describe("BonusTermsEditor", () => {
  it("offers examples of what it supports, and a click fills the box", async () => {
    renderEditor()
    const user = userEvent.setup()
    await user.click(screen.getByRole("button", { name: /\$2 per 1K views after 200K/ }))
    expect((screen.getByLabelText("Describe the bonus") as HTMLInputElement).value).toMatch(
      /\$2 per 1K views after 200K/
    )
  })

  it("says how to answer Claude's question (edit the description and preview again)", async () => {
    post.mockResolvedValue({
      data: undefined,
      error: { detail: { question: "Should the $50 be per video?" } },
      response: { status: 422 },
    })
    renderEditor()
    const user = userEvent.setup()
    await user.type(screen.getByLabelText("Describe the bonus"), "$50 flat for all videos")
    await user.click(screen.getByRole("button", { name: /Preview with Claude/ }))
    expect(await screen.findByText(/Should the \$50 be per video\?/)).toBeTruthy()
    expect(screen.getByText(/edit the description above/i)).toBeTruthy()
  })
})
