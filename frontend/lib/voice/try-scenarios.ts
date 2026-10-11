/** Sample deals for POST /api/v1/voice/try-call — ids must match the backend enum. */

export type TryScenarioId = "standard" | "single_video" | "rush"

export type TryScenario = {
  id: TryScenarioId
  label: string
  hint: string
}

export const TRY_SCENARIOS: TryScenario[] = [
  {
    id: "standard",
    label: "3 videos · $1,000",
    hint: "Typical package ask with room on timeline and price",
  },
  {
    id: "single_video",
    label: "1 video · $800",
    hint: "Smaller scope — good for a quick counter",
  },
  {
    id: "rush",
    label: "2 videos · tight timeline",
    hint: "Faster go-live; the agent pushes on dates",
  },
]
