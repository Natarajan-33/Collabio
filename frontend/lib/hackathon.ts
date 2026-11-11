/**
 * Hackathon mode (PayPal AI Hackathon): one-click demo personas instead of sign-up, phone
 * calls off, and a judge guide. A flag, not a deletion: unset it to get the full app back.
 */
export const isHackathon = process.env.NEXT_PUBLIC_HACKATHON_MODE === "1"

export type Persona = "brand" | "creator"

export const PERSONAS = {
  brand: { label: "Enter as Lumen Audio (brand)", short: "Lumen Audio", role: "Brand" },
  creator: { label: "Enter as Priya (creator)", short: "Priya", role: "Creator" },
} as const satisfies Record<Persona, { label: string; short: string; role: string }>

export const CALLS_OFF = "Calls are off in the public demo."

/** Where a persona lands after the one-click sign-in: the deals, where money moves. */
export function personaPath(persona: Persona): string {
  return persona === "brand" ? "/brand/deals" : "/creator/deals"
}

export function isPersona(value: string | null): value is Persona {
  return value === "brand" || value === "creator"
}
