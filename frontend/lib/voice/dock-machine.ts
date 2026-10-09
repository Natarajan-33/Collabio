/**
 * The Voice Dock's state machine. It only decides what the dock shows; capturing
 * audio and calling the API happen in `useCommandCapture` and the dock itself.
 *
 * idle → connecting → listening → routing → heard → idle
 *                \________________/   \→ error
 */
export type DockMode =
  "idle" | "connecting" | "listening" | "routing" | "heard" | "error"

export type DockInput = "voice" | "text"

export type DockState = {
  mode: DockMode
  /** Which control the dock offers: hold-to-speak, or a text box. */
  input: DockInput
  /** The live transcript while listening, then the command being routed. */
  partial: string
  /** What the router understood, for the "Heard: …" chip. */
  heard: string | null
  error: string | null
}

export type DockEvent =
  | { type: "PRESS" }
  | { type: "CONNECTED" }
  | { type: "PARTIAL"; text: string }
  | { type: "RELEASE"; finalText: string }
  | { type: "ROUTED"; heard: string }
  | { type: "FAIL"; reason: string; fatal: boolean }
  | { type: "TEXT_SUBMIT"; text: string }
  | { type: "DISMISS" }
  /** The keyboard toggle: choose hold-to-speak or the text box. */
  | { type: "SET_INPUT"; input: DockInput }

export const initialDockState: DockState = {
  mode: "idle",
  input: "voice",
  partial: "",
  heard: null,
  error: null,
}

/** Modes with nothing in flight: a new command may begin. */
export function isAtRest(mode: DockMode) {
  return mode === "idle" || mode === "heard" || mode === "error"
}

export function dockReducer(state: DockState, event: DockEvent): DockState {
  switch (event.type) {
    case "PRESS":
      // Text input stays chosen until the user switches back, so a blocked
      // microphone is not retried on every Space press.
      if (state.input !== "voice" || !isAtRest(state.mode)) return state
      return {
        ...state,
        mode: "connecting",
        partial: "",
        heard: null,
        error: null,
      }

    case "CONNECTED":
      if (state.mode !== "connecting") return state
      return { ...state, mode: "listening" }

    case "PARTIAL":
      if (state.mode !== "connecting" && state.mode !== "listening")
        return state
      return { ...state, mode: "listening", partial: event.text }

    case "RELEASE": {
      if (state.mode !== "connecting" && state.mode !== "listening")
        return state
      const text = event.finalText.trim()
      if (!text) return { ...state, mode: "idle", partial: "" }
      return { ...state, mode: "routing", partial: text }
    }

    case "TEXT_SUBMIT": {
      const text = event.text.trim()
      if (!text || !isAtRest(state.mode)) return state
      return {
        ...state,
        mode: "routing",
        partial: text,
        heard: null,
        error: null,
      }
    }

    case "ROUTED":
      if (state.mode !== "routing") return state
      return { ...state, mode: "heard", partial: "", heard: event.heard }

    case "FAIL":
      return {
        ...state,
        mode: "error",
        input: event.fatal ? "text" : state.input,
        // Keep the command that failed to route so it can be retried; drop
        // anything half-heard.
        partial: state.mode === "routing" ? state.partial : "",
        error: event.reason,
      }

    case "DISMISS":
      if (state.mode !== "heard" && state.mode !== "error") return state
      return { ...state, mode: "idle", partial: "", heard: null, error: null }

    case "SET_INPUT":
      if (!isAtRest(state.mode)) return state
      return { ...initialDockState, input: event.input }
  }
}
