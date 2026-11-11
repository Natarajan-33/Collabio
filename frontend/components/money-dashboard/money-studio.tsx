"use client"

import * as React from "react"
import { AgStudioAiModule, createAiHarness, type AgStudioMode } from "ag-studio"
import { AgStudio, AgStudioProvider } from "ag-studio-react"

import {
  buildMoneyData,
  moneyReport,
  moneyTheme,
  type MoneyRows,
} from "@/components/money-dashboard/studio-config"
import { Button } from "@/components/ui/button"
import { useApi } from "@/hooks/use-api"
import { createClaudeAdapter } from "@/lib/ai/claude-adapter"

const PROMPT_STARTERS = [
  {
    label: "Cost per 1K views",
    prompt: "Add a chart of effective cost per 1,000 views by creator.",
  },
  {
    label: "What needs my approval?",
    prompt: "Which payouts are waiting for my approval, and how much in total?",
  },
  {
    label: "Bonus share",
    prompt: "What share of everything paid so far was performance bonus?",
  },
]

/** The brand's money as an AG Studio dashboard, with an "Ask Collabio" agent on Claude. */
export function MoneyStudio({ licenseKey }: { licenseKey?: string }) {
  const api = useApi()
  const [rows, setRows] = React.useState<MoneyRows | null>(null)
  const [failed, setFailed] = React.useState(false)
  const [mode, setMode] = React.useState<AgStudioMode>("view")

  React.useEffect(() => {
    let gone = false
    void (async () => {
      const { data } = await api.GET("/api/v1/money/dashboard")
      if (gone) return
      if (data) setRows(data as unknown as MoneyRows)
      else setFailed(true)
    })()
    return () => {
      gone = true
    }
  }, [api])

  const studioData = React.useMemo(
    () => (rows ? buildMoneyData(rows) : null),
    [rows]
  )
  const ai = React.useMemo(() => {
    const adapter = createClaudeAdapter("/api/ai/claude")
    return ({
      api: studioApi,
    }: {
      api: Parameters<typeof createAiHarness>[0]
    }) =>
      createAiHarness(studioApi, { adapter, promptStarters: PROMPT_STARTERS })
  }, [])

  if (failed)
    return (
      <p className="p-6 text-sm text-destructive">
        Could not load your money data.
      </p>
    )
  if (!studioData)
    return (
      <p className="p-6 text-sm text-muted-foreground">Loading dashboard…</p>
    )

  return (
    <div className="flex h-[calc(100svh-0px)] flex-col">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-border px-6 py-4">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Money</h1>
          <p className="text-sm text-muted-foreground">
            Funding, payouts and refunds across your creator deals (PayPal
            sandbox). Ask Collabio (Claude) to answer questions or build
            widgets.
          </p>
        </div>
        <Button
          type="button"
          variant="outline"
          onClick={() => setMode((m) => (m === "view" ? "edit" : "view"))}
        >
          {mode === "view" ? "Edit dashboard" : "Done editing"}
        </Button>
      </div>
      <div className="min-h-0 flex-1">
        <AgStudioProvider licenseKey={licenseKey} modules={[AgStudioAiModule]}>
          <AgStudio
            style={{ height: "100%", width: "100%" }}
            theme={moneyTheme}
            layout={{ widgetBorderEnabled: true }}
            data={studioData}
            ai={ai}
            initialState={moneyReport}
            mode={mode}
          />
        </AgStudioProvider>
      </div>
    </div>
  )
}
