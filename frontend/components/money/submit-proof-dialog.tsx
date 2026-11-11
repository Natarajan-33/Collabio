"use client"

import * as React from "react"
import { ImageIcon } from "lucide-react"
import { toast } from "sonner"

import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { getSupabaseBrowser } from "@/lib/supabase/browser"
import { cn } from "@/lib/utils"

/** Fictional analytics screenshots for the demo (no real platform UI or logos). */
export const SAMPLE_SHOTS = [
  { src: "/demo/analytics-312k.png", views: 312_000, label: "312K views" },
  { src: "/demo/analytics-812k.png", views: 812_400, label: "812.4K views" },
  { src: "/demo/analytics-1240k.png", views: 1_240_000, label: "1.24M views" },
] as const

const MAX_BYTES = 5 * 1024 * 1024

/**
 * Proof for one milestone: the post link, its caption, the views the creator sees and an
 * analytics screenshot. Submitting starts the Claude settlement run.
 */
export function SubmitProofDialog({
  milestoneId,
  title,
  open,
  onOpenChange,
  onSubmitted,
}: {
  milestoneId: string
  title: string
  open: boolean
  onOpenChange: (open: boolean) => void
  onSubmitted: () => void
}) {
  const [postUrl, setPostUrl] = React.useState(
    "https://example.com/p/lumen-pods-review"
  )
  const [caption, setCaption] = React.useState(
    "Two weeks with Lumen Pods: 30-hour battery and the cleanest call quality I've tested. #ad"
  )
  const [claimed, setClaimed] = React.useState("812400")
  const [file, setFile] = React.useState<File | null>(null)
  const [sample, setSample] = React.useState<string | null>(SAMPLE_SHOTS[1].src)
  const [busy, setBusy] = React.useState(false)

  async function screenshot(): Promise<Blob | null> {
    if (file) return file
    if (!sample) return null
    const res = await fetch(sample)
    return res.ok ? await res.blob() : null
  }

  async function submit() {
    setBusy(true)
    try {
      const blob = await screenshot()
      if (!blob) {
        toast.error("Add an analytics screenshot.")
        return
      }
      if (blob.size > MAX_BYTES) {
        toast.error("Screenshots must be 5 MB or smaller.")
        return
      }
      const form = new FormData()
      form.set("post_url", postUrl)
      form.set("caption", caption)
      form.set("claimed_views", String(Number(claimed.replace(/\D/g, "")) || 0))
      form.set("screenshot", blob, file?.name ?? "analytics.png")
      const { data } = await getSupabaseBrowser().auth.getSession()
      const res = await fetch(
        `${process.env.NEXT_PUBLIC_API_URL}/api/v1/milestones/${milestoneId}/submissions`,
        {
          method: "POST",
          headers: {
            Authorization: `Bearer ${data.session?.access_token ?? ""}`,
          },
          body: form,
        }
      )
      if (res.ok) {
        toast.success("Submitted. Claude is checking your post.")
        onOpenChange(false)
        onSubmitted()
      } else if (res.status === 429) {
        toast.error("You've reached today's demo limit for submissions.")
      } else if (res.status === 422) {
        toast.error("That file isn't a PNG or JPG screenshot.")
      } else {
        toast.error("Could not submit the proof.")
      }
    } finally {
      setBusy(false)
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[calc(100svh-2rem)] overflow-y-auto sm:max-w-xl">
        <DialogHeader>
          <DialogTitle>Submit proof · {title}</DialogTitle>
          <DialogDescription>
            Claude checks the post against the brief, reads the views from your
            screenshot and pays you through PayPal.
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-4">
          <div className="space-y-1">
            <Label htmlFor="post-url">Post link</Label>
            <Input
              id="post-url"
              value={postUrl}
              onChange={(e) => setPostUrl(e.target.value)}
            />
          </div>
          <div className="space-y-1">
            <Label htmlFor="caption">Caption or script</Label>
            <textarea
              id="caption"
              value={caption}
              onChange={(e) => setCaption(e.target.value)}
              rows={3}
              className="w-full rounded-lg border border-input bg-transparent px-2.5 py-2 text-sm outline-none focus-visible:ring-3 focus-visible:ring-ring/50"
            />
          </div>
          <div className="space-y-1">
            <Label htmlFor="claimed">Views you see right now</Label>
            <Input
              id="claimed"
              inputMode="numeric"
              value={claimed}
              onChange={(e) => setClaimed(e.target.value)}
            />
          </div>
          <fieldset className="space-y-2">
            <legend className="text-sm font-medium">
              Analytics screenshot
            </legend>
            <div className="grid grid-cols-3 gap-2">
              {SAMPLE_SHOTS.map((shot) => (
                <button
                  key={shot.src}
                  type="button"
                  onClick={() => {
                    setSample(shot.src)
                    setFile(null)
                    setClaimed(String(shot.views))
                  }}
                  className={cn(
                    "overflow-hidden rounded-lg border text-left text-xs",
                    sample === shot.src && !file
                      ? "border-foreground ring-2 ring-ring/40"
                      : "border-border"
                  )}
                >
                  {/* eslint-disable-next-line @next/next/no-img-element */}
                  <img
                    src={shot.src}
                    alt={`Sample analytics, ${shot.label}`}
                    className="h-20 w-full object-cover"
                  />
                  <span className="block px-2 py-1">{shot.label}</span>
                </button>
              ))}
            </div>
            <label className="flex cursor-pointer items-center gap-2 text-sm text-muted-foreground">
              <ImageIcon className="size-4" aria-hidden />
              <span>{file ? file.name : "…or upload your own PNG/JPG"}</span>
              <input
                type="file"
                accept="image/png,image/jpeg"
                className="sr-only"
                onChange={(e) => {
                  const f = e.target.files?.[0] ?? null
                  setFile(f)
                  if (f) setSample(null)
                }}
              />
            </label>
          </fieldset>
        </div>
        <DialogFooter>
          <Button
            type="button"
            variant="outline"
            onClick={() => onOpenChange(false)}
          >
            Cancel
          </Button>
          <Button type="button" onClick={submit} disabled={busy || !postUrl}>
            {busy ? "Submitting…" : "Submit for payout"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
