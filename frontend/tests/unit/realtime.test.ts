import { renderHook } from "@testing-library/react"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import { useBatchDoorbell } from "@/lib/supabase/realtime"

const h = vi.hoisted(() => {
  const channel = { on: vi.fn(), subscribe: vi.fn() }
  return {
    channel,
    supabase: { channel: vi.fn(), removeChannel: vi.fn() },
    /** The postgres_changes callback the hook registered. */
    insert: null as null | (() => void),
    /** The subscribe status callback the hook registered. */
    status: null as null | ((status: string) => void),
  }
})

vi.mock("@/lib/supabase/browser", () => ({
  getSupabaseBrowser: () => h.supabase,
}))

beforeEach(() => {
  vi.useFakeTimers()
  h.insert = null
  h.status = null
  h.channel.on.mockReset().mockImplementation((_type, _filter, cb) => {
    h.insert = cb
    return h.channel
  })
  h.channel.subscribe.mockReset().mockImplementation((cb) => {
    h.status = cb
    return h.channel
  })
  h.supabase.channel.mockReset().mockReturnValue(h.channel)
  h.supabase.removeChannel.mockReset()
})

afterEach(() => {
  vi.useRealTimers()
})

describe("useBatchDoorbell", () => {
  it("subscribes to thread_events inserts for the batch", () => {
    renderHook(() => useBatchDoorbell("batch-1", vi.fn()))

    expect(h.supabase.channel).toHaveBeenCalledWith("thread-events:batch-1")
    expect(h.channel.on).toHaveBeenCalledWith(
      "postgres_changes",
      {
        event: "INSERT",
        schema: "public",
        table: "thread_events",
        filter: "batch_id=eq.batch-1",
      },
      expect.any(Function)
    )
    expect(h.channel.subscribe).toHaveBeenCalledTimes(1)
  })

  it("debounces a burst of inserts into one ring", () => {
    const onRing = vi.fn()
    renderHook(() => useBatchDoorbell("batch-1", onRing))

    for (let i = 0; i < 5; i++) {
      h.insert!()
      vi.advanceTimersByTime(20)
    }
    expect(onRing).not.toHaveBeenCalled()

    vi.advanceTimersByTime(229)
    expect(onRing).not.toHaveBeenCalled()
    vi.advanceTimersByTime(1)
    expect(onRing).toHaveBeenCalledTimes(1)

    vi.advanceTimersByTime(1000)
    expect(onRing).toHaveBeenCalledTimes(1)
  })

  it("rings once when the subscription opens, to catch up", () => {
    const onRing = vi.fn()
    renderHook(() => useBatchDoorbell("batch-1", onRing))

    h.status!("CHANNEL_ERROR")
    h.status!("TIMED_OUT")
    vi.advanceTimersByTime(1000)
    expect(onRing).not.toHaveBeenCalled()

    h.status!("SUBSCRIBED")
    expect(onRing).toHaveBeenCalledTimes(1)
  })

  it("polls while live and stops polling when not", () => {
    const onRing = vi.fn()
    const { rerender } = renderHook(
      ({ live }) => useBatchDoorbell("batch-1", onRing, { live }),
      { initialProps: { live: true } }
    )

    vi.advanceTimersByTime(10_000)
    expect(onRing).toHaveBeenCalledTimes(1)
    vi.advanceTimersByTime(20_000)
    expect(onRing).toHaveBeenCalledTimes(3)

    rerender({ live: false })
    vi.advanceTimersByTime(60_000)
    expect(onRing).toHaveBeenCalledTimes(3)
  })

  it("does not poll by default", () => {
    const onRing = vi.fn()
    renderHook(() => useBatchDoorbell("batch-1", onRing))

    vi.advanceTimersByTime(60_000)
    expect(onRing).not.toHaveBeenCalled()
  })

  it("honours custom poll and debounce intervals", () => {
    const onRing = vi.fn()
    renderHook(() =>
      useBatchDoorbell("batch-1", onRing, {
        live: true,
        pollMs: 1000,
        debounceMs: 50,
      })
    )

    vi.advanceTimersByTime(1000)
    expect(onRing).toHaveBeenCalledTimes(1)
    h.insert!()
    vi.advanceTimersByTime(50)
    expect(onRing).toHaveBeenCalledTimes(2)
  })

  it("rings the latest callback without resubscribing", () => {
    const first = vi.fn()
    const second = vi.fn()
    const { rerender } = renderHook(
      ({ onRing }) => useBatchDoorbell("batch-1", onRing),
      { initialProps: { onRing: first } }
    )
    rerender({ onRing: second })

    h.insert!()
    vi.advanceTimersByTime(250)

    expect(first).not.toHaveBeenCalled()
    expect(second).toHaveBeenCalledTimes(1)
    expect(h.supabase.channel).toHaveBeenCalledTimes(1)
  })

  it("removes the channel on unmount and clears both timers", () => {
    const onRing = vi.fn()
    const { unmount } = renderHook(() =>
      useBatchDoorbell("batch-1", onRing, { live: true })
    )
    h.insert!()

    unmount()

    expect(h.supabase.removeChannel).toHaveBeenCalledExactlyOnceWith(h.channel)
    vi.advanceTimersByTime(60_000)
    expect(onRing).not.toHaveBeenCalled()
    expect(vi.getTimerCount()).toBe(0)
  })

  it("moves to the new channel when the batch changes", () => {
    const { rerender } = renderHook(({ id }) => useBatchDoorbell(id, vi.fn()), {
      initialProps: { id: "a" },
    })
    rerender({ id: "b" })

    expect(h.supabase.removeChannel).toHaveBeenCalledTimes(1)
    expect(h.supabase.channel).toHaveBeenLastCalledWith("thread-events:b")
  })
})
