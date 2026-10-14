import { cleanup, render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import * as React from "react"
import { afterEach, describe, expect, it, vi } from "vitest"

import { TryYourselfDialog } from "@/components/voice/try-yourself-dialog"

vi.mock("@/hooks/use-api", () => ({ useApi: () => ({ POST: vi.fn() }) }))
vi.mock("sonner", () => ({ toast: { error: vi.fn(), success: vi.fn() } }))

afterEach(cleanup)

function Harness() {
  const [open, setOpen] = React.useState(true)
  return (
    <>
      <button type="button" onClick={() => setOpen(true)}>
        Reopen
      </button>
      <TryYourselfDialog role="brand" open={open} onOpenChange={setOpen} />
    </>
  )
}

describe("TryYourselfDialog", { timeout: 20_000 }, () => {
  it("starts from the first step again after it is closed", async () => {
    const user = userEvent.setup()
    render(<Harness />)

    await user.click(await screen.findByRole("button", { name: /Email me/ }))
    await user.type(await screen.findByLabelText("Email address"), "me@x.test")
    await user.click(screen.getByRole("button", { name: "Continue" }))
    expect(await screen.findByText("Pick a sample deal")).toBeTruthy()

    await user.keyboard("{Escape}")
    await user.click(await screen.findByRole("button", { name: "Reopen" }))

    expect(await screen.findByText("Try negotiation")).toBeTruthy()
    await user.click(screen.getByRole("button", { name: /Email me/ }))
    expect(
      ((await screen.findByLabelText("Email address")) as HTMLInputElement)
        .value
    ).toBe("")
  })
})
