import { redirect } from "next/navigation"

import { roleHome } from "@/lib/auth/routing"

/** `/creator` has no screen of its own: it opens the creator's home. */
export default function CreatorRoot() {
  redirect(roleHome("creator"))
}
