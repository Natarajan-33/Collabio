import { toast } from "sonner"

import { apiErrorCode, apiErrorDetail } from "@/lib/api/errors"

export const TERMS_CHANGED_MESSAGE = "Terms changed — review the latest"
export const GENERIC_ERROR = "Something went wrong. Try again."

/**
 * Tells the brand why an action did not go through. `refetch` means the thread is no
 * longer what the dialog was showing (its terms moved, or the action is not allowed any
 * more): the dialog should close and the board load again. `stay` is an error the brand
 * can fix in place.
 */
export function reportActionError(error: unknown): "refetch" | "stay" {
  const code = apiErrorCode(error)
  if (code === "terms_changed") {
    toast.info(TERMS_CHANGED_MESSAGE)
    return "refetch"
  }
  toast.error(apiErrorDetail(error)?.message ?? GENERIC_ERROR)
  return code === "action_not_allowed" || code === "stale_status"
    ? "refetch"
    : "stay"
}
