"use client"

import * as React from "react"
import { Sparkles } from "lucide-react"
import { toast } from "sonner"

import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { MoneyInput } from "@/components/ui/money-input"
import { useApi } from "@/hooks/use-api"
import type { components } from "@/lib/api/schema"
import { formatCents } from "@/lib/money"
import { formatExample } from "@/lib/money/format"

type BonusTerms = components["schemas"]["BonusTermsIn"]
type Preview = components["schemas"]["BonusPreview"]

const PLACEHOLDER =
  "e.g. $2 per 1K views after 200K, up to $500 per video, plus $300 if a video hits 1M"

/** What the engine can pay (bonuses come from each video's verified views). */
const EXAMPLES = [
  "$2 per 1K views after 200K, up to $500 per video",
  "$100 if a video passes 500K views",
  "$1 per 1K views after 100K, up to $300 per video, plus $200 at 1M views",
]

function detailText(detail: unknown): string | null {
  if (detail && typeof detail === "object" && "question" in detail) {
    return String((detail as { question: string }).question)
  }
  if (typeof detail === "string") return detail.replaceAll("_", " ")
  return null
}

/**
 * The brand describes a performance bonus in plain English; Claude turns it into terms,
 * the engine prices them, and the brand can adjust the numbers before saving.
 */
export function BonusTermsEditor({
  dealId,
  initialText,
  initialTerms,
  onSaved,
}: {
  dealId: string
  initialText: string | null
  initialTerms: BonusTerms | null
  onSaved: () => void
}) {
  const api = useApi()
  const [text, setText] = React.useState(initialText ?? "")
  const [terms, setTerms] = React.useState<BonusTerms | null>(initialTerms)
  const [preview, setPreview] = React.useState<Preview | null>(null)
  const [busy, setBusy] = React.useState<"preview" | "save" | null>(null)
  const [question, setQuestion] = React.useState<string | null>(null)

  async function runPreview() {
    setBusy("preview")
    setQuestion(null)
    try {
      const { data, error, response } = await api.POST(
        "/api/v1/deals/{deal_id}/bonus-terms/preview",
        { params: { path: { deal_id: dealId } }, body: { text } }
      )
      if (data) {
        setPreview(data)
        setTerms(data.terms)
      } else if (response.status === 429) {
        toast.error("You've reached today's demo limit for bonus previews.")
      } else {
        setQuestion(
          detailText((error as { detail?: unknown })?.detail) ??
            "Claude could not read that."
        )
      }
    } finally {
      setBusy(null)
    }
  }

  async function save() {
    if (!terms) return
    setBusy("save")
    try {
      const { data, error } = await api.PUT(
        "/api/v1/deals/{deal_id}/bonus-terms",
        {
          params: { path: { deal_id: dealId } },
          body: { source_text: text, terms },
        }
      )
      if (data) {
        setPreview(data)
        toast.success("Bonus saved. The funding total now includes it.")
        onSaved()
      } else {
        toast.error(
          detailText((error as { detail?: unknown })?.detail) ??
            "Could not save."
        )
      }
    } finally {
      setBusy(null)
    }
  }

  function setCpm(patch: Partial<NonNullable<BonusTerms["cpm"]>>) {
    setTerms((t) => (t?.cpm ? { ...t, cpm: { ...t.cpm, ...patch } } : t))
  }

  return (
    <section aria-labelledby="bonus-heading" className="space-y-4">
      <div>
        <h3 id="bonus-heading" className="font-medium">
          Performance bonus{" "}
          <span className="text-muted-foreground">(optional)</span>
        </h3>
        <p className="text-sm text-muted-foreground">
          Paid per video on top of the agreed price, from the views Claude reads
          off the creator&apos;s analytics. Bonuses only ever add to what the
          creator agreed.
        </p>
      </div>
      <div className="flex flex-col gap-2 sm:flex-row">
        <Input
          aria-label="Describe the bonus"
          placeholder={PLACEHOLDER}
          value={text}
          onChange={(e) => setText(e.target.value)}
          className="h-10"
        />
        <Button
          type="button"
          variant="outline"
          className="h-10"
          disabled={!text.trim() || busy !== null}
          onClick={runPreview}
        >
          <Sparkles aria-hidden />
          {busy === "preview" ? "Reading…" : "Preview with Claude"}
        </Button>
      </div>
      <div className="space-y-1.5">
        <p className="text-xs text-muted-foreground">
          Bonuses are paid per video from its views: an amount per 1,000 views
          (with a cap), and/or a flat amount when a video passes a view count.
          Try one:
        </p>
        <div className="flex flex-wrap gap-1.5">
          {EXAMPLES.map((example) => (
            <button
              key={example}
              type="button"
              onClick={() => {
                setText(example)
                setQuestion(null)
              }}
              className="rounded-full border border-border px-2.5 py-1 text-xs text-muted-foreground hover:border-foreground/40 hover:text-foreground"
            >
              {example}
            </button>
          ))}
        </div>
      </div>
      {question && (
        <div role="status" className="rounded-lg border border-voice/40 bg-voice/5 p-3 text-sm">
          <p className="font-medium text-voice-ink">Claude needs a change</p>
          <p className="mt-1">{question}</p>
          <p className="mt-2 text-muted-foreground">
            To answer, edit the description above and press Preview with Claude
            again, or pick an example.
          </p>
        </div>
      )}

      {terms && (
        <div className="space-y-4 rounded-xl border border-border p-4">
          {terms.cpm && (
            <div className="grid gap-3 sm:grid-cols-3">
              <div className="space-y-1">
                <Label htmlFor="cpm-rate">Per 1K views</Label>
                <MoneyInput
                  id="cpm-rate"
                  value={terms.cpm.rate_cents_per_1k}
                  onValueChange={(c) => setCpm({ rate_cents_per_1k: c ?? 0 })}
                />
              </div>
              <div className="space-y-1">
                <Label htmlFor="cpm-start">After views</Label>
                <Input
                  id="cpm-start"
                  inputMode="numeric"
                  value={String(terms.cpm.starts_after_views)}
                  onChange={(e) =>
                    setCpm({
                      starts_after_views:
                        Number(e.target.value.replace(/\D/g, "")) || 0,
                    })
                  }
                />
              </div>
              <div className="space-y-1">
                <Label htmlFor="cpm-cap">Cap per video</Label>
                <MoneyInput
                  id="cpm-cap"
                  value={terms.cpm.cap_cents}
                  onValueChange={(c) => setCpm({ cap_cents: c ?? 0 })}
                />
              </div>
            </div>
          )}
          {(terms.tiers ?? []).length > 0 && (
            <ul className="space-y-1 text-sm">
              {(terms.tiers ?? []).map((tier) => (
                <li key={tier.views} className="flex justify-between gap-3">
                  <span>
                    Tier bonus at {tier.views.toLocaleString("en-US")} views
                  </span>
                  <span className="num">+{formatCents(tier.bonus_cents)}</span>
                </li>
              ))}
            </ul>
          )}
          {preview && (
            <div className="space-y-1 border-t border-border pt-3 text-sm">
              <p className="text-muted-foreground">Per video:</p>
              <ul className="flex flex-wrap gap-x-4 gap-y-1">
                {preview.examples.map((ex) => (
                  <li key={ex.views} className="num">
                    {formatExample(ex)}
                  </li>
                ))}
              </ul>
              <p>
                Most a video can earn in bonus:{" "}
                <span className="num font-medium">
                  {formatCents(preview.max_bonus_per_video_cents)}
                </span>
              </p>
            </div>
          )}
          <Button type="button" onClick={save} disabled={busy !== null}>
            {busy === "save" ? "Saving…" : "Save bonus"}
          </Button>
        </div>
      )}
    </section>
  )
}
