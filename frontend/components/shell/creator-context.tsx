"use client"

import * as React from "react"

const CreatorIdContext = React.createContext<string | null>(null)

/** Tells the creator's pages who is signed in, for the realtime doorbell. */
export function CreatorIdProvider({
  creatorId,
  children,
}: {
  creatorId: string | null
  children: React.ReactNode
}) {
  return <CreatorIdContext value={creatorId}>{children}</CreatorIdContext>
}

/** The signed-in creator's id; null outside a creator shell or before it is known. */
export function useCreatorId(): string | null {
  return React.useContext(CreatorIdContext)
}
