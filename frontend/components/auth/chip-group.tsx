"use client"

import { Check } from "lucide-react"

import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group"

type ChipGroupProps<Value extends string> = {
  /** Id of the element that names the group. */
  labelledBy: string
  options: readonly { value: Value; label: string }[]
  value: readonly Value[]
  onValueChange: (value: Value[]) => void
  /** Several chips can be on at once. Otherwise at most one is. */
  multiple?: boolean
}

/**
 * Pick from a short fixed list without typing. Each chip is a toggle button, so
 * keyboard and screen reader users get arrow-key movement and a pressed state; the
 * tick on a chosen chip means selection is not shown by colour alone.
 */
export function ChipGroup<Value extends string>({
  labelledBy,
  options,
  value,
  onValueChange,
  multiple = false,
}: ChipGroupProps<Value>) {
  return (
    <ToggleGroup
      aria-labelledby={labelledBy}
      multiple={multiple}
      value={value}
      // The ui wrapper types the group's values as plain strings; they can only be the
      // option values passed in.
      onValueChange={(next) => onValueChange(next as Value[])}
      variant="outline"
      className="w-full flex-wrap"
    >
      {options.map((option) => (
        <ToggleGroupItem
          key={option.value}
          value={option.value}
          className="h-9 rounded-full px-4 text-sm aria-pressed:border-foreground aria-pressed:bg-foreground aria-pressed:text-background aria-pressed:hover:bg-foreground/90 aria-pressed:hover:text-background"
        >
          <Check
            aria-hidden
            className="hidden size-3.5 group-aria-pressed/toggle:block"
          />
          {option.label}
        </ToggleGroupItem>
      ))}
    </ToggleGroup>
  )
}
