import { contentTypeLabel } from "@/lib/vocab"
import { formatCents } from "@/lib/money"
import type { PackageSummary } from "@/lib/discover/state"
import { cn } from "@/lib/utils"

type PackageStripProps = {
  pkg: PackageSummary
  /** Not one of the packages the search asked for: shown, but quieter. */
  muted?: boolean
}

/**
 * One package on a creator card: its name and format, the terms the creator wrote
 * (`2 videos/contract · $1,000 · +1 video $400`), and what a video costs.
 */
export function PackageStrip({ pkg, muted = false }: PackageStripProps) {
  return (
    <div
      data-slot="package-strip"
      data-muted={muted ? "" : undefined}
      className={cn(
        "flex flex-col gap-1 rounded-xl bg-muted/70 px-3 py-2.5 transition-opacity",
        muted && "opacity-60"
      )}
    >
      <div className="flex items-baseline justify-between gap-3">
        <p className="min-w-0 truncate text-sm font-medium">{pkg.name}</p>
        <span className="shrink-0 num text-sm font-semibold">
          {formatCents(pkg.per_video_cents)}/video
        </span>
      </div>
      <p className="num text-xs leading-relaxed text-muted-foreground">
        {pkg.one_liner}
      </p>
      <p className="text-[0.6875rem] tracking-wide text-muted-foreground uppercase">
        {contentTypeLabel(pkg.content_type)}
      </p>
    </div>
  )
}
