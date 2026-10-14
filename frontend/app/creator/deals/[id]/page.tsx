"use client"

import { useParams } from "next/navigation"

import { DealDetail } from "@/components/deal/deal-detail"

export default function CreatorDealPage() {
  const { id } = useParams<{ id: string }>()
  return <DealDetail viewer="creator" dealId={id} />
}
