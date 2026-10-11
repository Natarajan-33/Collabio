/** Set after sign-up + onboarding; consumed once inside the app shell. */
export const WELCOME_NOTE_STORAGE_KEY = "collabio_welcome_note_pending"

export function markWelcomeNotePending() {
  if (typeof window === "undefined") return
  sessionStorage.setItem(WELCOME_NOTE_STORAGE_KEY, "1")
}

export function consumeWelcomeNotePending(): boolean {
  if (typeof window === "undefined") return false
  if (sessionStorage.getItem(WELCOME_NOTE_STORAGE_KEY) !== "1") return false
  sessionStorage.removeItem(WELCOME_NOTE_STORAGE_KEY)
  return true
}
