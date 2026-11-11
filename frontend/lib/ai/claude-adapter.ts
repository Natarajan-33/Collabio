/**
 * AG Studio LLM adapter backed by Claude (Anthropic Messages API).
 *
 * Runs in the browser and posts to this app's `/api/ai/claude` route, which holds the key.
 * The route answers with one complete Claude message; the adapter replays it as AG-UI
 * content events (text and tool calls) and resolves `complete` with the consolidated
 * response. Studio runs the tools and sends their results back on the next turn.
 */
import type {
  AgAiConversationItem,
  AgAiEvent,
  AgAiOutputItem,
  AgLlmAdapter,
  AgLlmRequest,
  AgLlmResponse,
} from "ag-studio"

type ClaudeBlock =
  | { type: "text"; text: string }
  | { type: "tool_use"; id: string; name: string; input: unknown }
  | { type: "tool_result"; tool_use_id: string; content: string }
  | { type: string; [key: string]: unknown }

type ClaudeMessage = { role: "user" | "assistant"; content: ClaudeBlock[] }

export type ClaudeRequestBody = {
  system: string
  messages: ClaudeMessage[]
  tools: { name: string; description?: string; input_schema: unknown }[]
  tool_choice?: { type: "auto" | "none" }
}

export type ClaudeReply = {
  id: string
  model: string
  stop_reason: string | null
  content: ClaudeBlock[]
  usage?: { input_tokens?: number; output_tokens?: number }
}

function textOf(content: { type: string; text?: string }[]): string {
  return content
    .filter((c) => c.type === "text")
    .map((c) => c.text ?? "")
    .join("\n")
}

function push(
  messages: ClaudeMessage[],
  role: ClaudeMessage["role"],
  block: ClaudeBlock
) {
  const last = messages.at(-1)
  if (last?.role === role) last.content.push(block)
  else messages.push({ role, content: [block] })
}

function parseArgs(args: string): unknown {
  try {
    return JSON.parse(args || "{}")
  } catch {
    return {}
  }
}

/** AG Studio's request as a Claude Messages body (model and limits are set server-side). */
export function toClaudeRequest(request: AgLlmRequest): ClaudeRequestBody {
  const system: string[] = request.instructions ? [request.instructions] : []
  const messages: ClaudeMessage[] = []

  for (const item of request.input as AgAiConversationItem[]) {
    if (item.type === "message" && item.kind === "input") {
      const text = textOf(item.content as { type: string; text?: string }[])
      if (item.role === "system") system.push(text)
      else if (text) push(messages, "user", { type: "text", text })
    } else if (item.type === "message" && item.kind === "output") {
      const text = textOf(item.content as { type: string; text?: string }[])
      if (text) push(messages, "assistant", { type: "text", text })
    } else if (item.type === "function_call") {
      push(messages, "assistant", {
        type: "tool_use",
        id: item.callId,
        name: item.name,
        input: parseArgs(item.arguments),
      })
    } else if (item.type === "function_call_output") {
      push(messages, "user", {
        type: "tool_result",
        tool_use_id: item.callId,
        content: item.output,
      })
    }
    // Reasoning items are not replayed: the route turns thinking off between tools.
  }

  if (request.responseFormat?.type === "json") {
    system.push(
      `Respond with only a JSON value (no prose, no code fences) matching this JSON Schema: ${JSON.stringify(request.responseFormat.schema)}`
    )
  }

  // Claude Sonnet 5.5 rejects forced tool choice: "required" or a named tool become "auto".
  const toolChoice =
    request.toolChoice === "none"
      ? { type: "none" as const }
      : { type: "auto" as const }

  return {
    system: system.join("\n\n"),
    messages,
    tools: (request.tools ?? []).map((tool) => ({
      name: tool.name,
      description: tool.description,
      input_schema: tool.parameters,
    })),
    ...(request.tools?.length ? { tool_choice: toolChoice } : {}),
  }
}

function unfence(text: string): string {
  const m = text.trim().match(/^```(?:json)?\s*([\s\S]*?)\s*```$/)
  return m ? m[1] : text
}

/** One Claude reply as AG-UI events plus the consolidated AG Studio response. */
export function fromClaudeMessage(
  reply: ClaudeReply,
  json = false
): { events: AgAiEvent[]; response: AgLlmResponse } {
  const events: AgAiEvent[] = []
  const output: AgAiOutputItem[] = []
  const text = reply.content
    .filter((b): b is { type: "text"; text: string } => b.type === "text")
    .map((b) => b.text)
    .join("")

  if (text) {
    const messageId = `${reply.id}-text`
    const finalText = json ? unfence(text) : text
    events.push(
      { type: "TEXT_MESSAGE_START", messageId, role: "assistant" } as AgAiEvent,
      {
        type: "TEXT_MESSAGE_CONTENT",
        messageId,
        delta: finalText,
      } as AgAiEvent,
      { type: "TEXT_MESSAGE_END", messageId } as AgAiEvent
    )
    output.push({
      id: messageId,
      kind: "output",
      type: "message",
      role: "assistant",
      status: "completed",
      content: [{ type: "text", text: finalText, annotations: [] }],
    })
  }

  for (const block of reply.content) {
    if (block.type !== "tool_use") continue
    const use = block as { id: string; name: string; input: unknown }
    const args = JSON.stringify(use.input ?? {})
    events.push(
      {
        type: "TOOL_CALL_START",
        toolCallId: use.id,
        toolCallName: use.name,
      } as AgAiEvent,
      { type: "TOOL_CALL_ARGS", toolCallId: use.id, delta: args } as AgAiEvent,
      { type: "TOOL_CALL_END", toolCallId: use.id } as AgAiEvent
    )
    output.push({
      id: use.id,
      kind: "output",
      type: "function_call",
      callId: use.id,
      name: use.name,
      arguments: args,
      status: "completed",
    })
  }

  const incomplete =
    reply.stop_reason === "max_tokens" || reply.stop_reason === "refusal"
  return {
    events,
    response: {
      id: reply.id,
      createdAt: Date.now(),
      model: reply.model,
      output,
      status: incomplete ? "incomplete" : "completed",
      incompleteDetails: incomplete
        ? { reason: reply.stop_reason as never }
        : undefined,
      usage: reply.usage
        ? {
            inputTokens: reply.usage.input_tokens ?? 0,
            outputTokens: reply.usage.output_tokens ?? 0,
            totalTokens:
              (reply.usage.input_tokens ?? 0) +
              (reply.usage.output_tokens ?? 0),
          }
        : undefined,
    } as AgLlmResponse,
  }
}

export function createClaudeAdapter(endpoint = "/api/ai/claude"): AgLlmAdapter {
  return {
    executeTurn(request, options) {
      const json = request.responseFormat?.type === "json"
      let resolve!: (r: AgLlmResponse) => void
      let reject!: (e: Error) => void
      const complete = new Promise<AgLlmResponse>((res, rej) => {
        resolve = res
        reject = rej
      })
      void complete.catch(() => {})

      async function* run(): AsyncIterableIterator<AgAiEvent> {
        try {
          const res = await fetch(endpoint, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(toClaudeRequest(request)),
            signal: options?.signal,
          })
          if (!res.ok) {
            const body = (await res.json().catch(() => ({}))) as {
              error?: string
            }
            throw new Error(
              body.error ?? `Claude request failed (${res.status})`
            )
          }
          const { events, response } = fromClaudeMessage(
            (await res.json()) as ClaudeReply,
            json
          )
          yield* events
          resolve(response)
        } catch (error) {
          reject(error instanceof Error ? error : new Error(String(error)))
        }
      }

      const iterator = run()
      return { stream: { [Symbol.asyncIterator]: () => iterator }, complete }
    },
  }
}
