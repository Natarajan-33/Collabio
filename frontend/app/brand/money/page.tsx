import { MoneyStudio } from "@/components/money-dashboard/money-studio"

/** The brand's money dashboard (AG Studio + the Claude agent). */
export default function BrandMoneyPage() {
  return <MoneyStudio licenseKey={process.env.AG_STUDIO} />
}
