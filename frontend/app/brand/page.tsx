import { redirect } from "next/navigation"

import { roleHome } from "@/lib/auth/routing"

/** `/brand` has no screen of its own: it opens the brand's home. */
export default function BrandRoot() {
  redirect(roleHome("brand"))
}
