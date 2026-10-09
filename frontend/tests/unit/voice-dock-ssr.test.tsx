// @vitest-environment node
import { renderToString } from "react-dom/server"
import { describe, expect, it, vi } from "vitest"

import { VoiceDock } from "@/components/voice/voice-dock"
import { VoiceScreenProvider } from "@/components/voice/voice-screen"

vi.mock("@/hooks/use-api", () => ({ useApi: () => ({ POST: vi.fn() }) }))
vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn() }) }))

describe("VoiceDock on the server", () => {
  it("renders without a browser, as the app shell does for every page", () => {
    const html = renderToString(
      <VoiceScreenProvider>
        <VoiceDock />
      </VoiceScreenProvider>
    )

    expect(html).toContain("Hold to speak")
    expect(html).toContain("Hold Space to speak")
    // Hidden until its entrance tween shows it, so there is no flash on hydration.
    expect(html).toContain("opacity-0")
    // The WebGL Orb is client-only and idle shows a static disc.
    expect(html).not.toContain("<canvas")
  })
})
