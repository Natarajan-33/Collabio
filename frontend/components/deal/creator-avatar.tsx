import { cn } from "@/lib/utils"
import { nicheColor } from "@/lib/vocab"

const SIZES = {
  sm: "size-8 text-sm",
  md: "size-10 text-base",
  lg: "size-12 text-lg",
} as const

type CreatorAvatarProps = {
  initials: string
  /** The creator's niches: the first with a known colour rings the avatar. */
  niches: readonly string[]
  size?: keyof typeof SIZES
  className?: string
}

/**
 * Initials in the display serif, ringed in the colour of the creator's niche. The ring
 * is decoration: the niche is always named in text beside it.
 */
export function CreatorAvatar({
  initials,
  niches,
  size = "lg",
  className,
}: CreatorAvatarProps) {
  return (
    <span
      aria-hidden
      data-slot="creator-avatar"
      style={{ "--niche": nicheColor(niches) } as React.CSSProperties}
      className={cn(
        "inline-flex shrink-0 items-center justify-center rounded-full border-2 border-(--niche) p-0.5 select-none",
        SIZES[size],
        className
      )}
    >
      <span className="flex size-full items-center justify-center rounded-full bg-[color-mix(in_oklch,var(--niche)_14%,var(--card))] font-display leading-none text-foreground italic">
        {initials}
      </span>
    </span>
  )
}
