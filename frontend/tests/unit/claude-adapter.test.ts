import { describe, expect, it } from "vitest"

import { fromClaudeMessage, toClaudeRequest } from "@/lib/ai/claude-adapter"

describe("AG Studio ↔ Claude adapter", () => {
  it("maps a conversation with tool calls onto alternating Claude messages", () => {
    const body = toClaudeRequest({
      instructions: "You build dashboards.",
      responseFormat: { type: "text" },
      toolChoice: "required",
      tools: [
        {
          name: "add_widget",
          description: "Adds a widget",
          parameters: {
            type: "object",
            properties: { type: { type: "string" } },
          },
        },
      ],
      input: [
        {
          id: "s",
          kind: "input",
          type: "message",
          role: "system",
          status: "completed",
          content: [{ type: "text", text: "Field ids are table.field." }],
        },
        {
          id: "u",
          kind: "input",
          type: "message",
          role: "user",
          status: "completed",
          content: [{ type: "text", text: "Chart payouts by creator" }],
        },
        {
          id: "c",
          kind: "output",
          type: "function_call",
          callId: "call_1",
          name: "add_widget",
          arguments: '{"type":"bar"}',
          status: "completed",
        },
        {
          type: "function_call_output",
          callId: "call_1",
          output: '{"ok":true}',
          status: "completed",
        },
      ],
    } as never)

    expect(body.system).toBe(
      "You build dashboards.\n\nField ids are table.field."
    )
    expect(body.tool_choice).toEqual({ type: "auto" }) // forced choice is not supported
    expect(body.tools[0]).toMatchObject({
      name: "add_widget",
      input_schema: { type: "object" },
    })
    expect(body.messages).toEqual([
      {
        role: "user",
        content: [{ type: "text", text: "Chart payouts by creator" }],
      },
      {
        role: "assistant",
        content: [
          {
            type: "tool_use",
            id: "call_1",
            name: "add_widget",
            input: { type: "bar" },
          },
        ],
      },
      {
        role: "user",
        content: [
          {
            type: "tool_result",
            tool_use_id: "call_1",
            content: '{"ok":true}',
          },
        ],
      },
    ])
  })

  it("asks for JSON in the system prompt when a JSON format is requested", () => {
    const body = toClaudeRequest({
      input: [
        {
          id: "u",
          kind: "input",
          type: "message",
          role: "user",
          status: "completed",
          content: [{ type: "text", text: "hi" }],
        },
      ],
      responseFormat: {
        type: "json",
        name: "plan",
        schema: { type: "object" },
      },
    } as never)
    expect(body.system).toContain("Respond with only a JSON value")
    expect(body.system).toContain('"type":"object"')
  })

  it("replays a Claude message as AG-UI events and a final response", () => {
    const { events, response } = fromClaudeMessage({
      id: "msg_1",
      model: "claude-sonnet-5-5",
      stop_reason: "tool_use",
      usage: { input_tokens: 10, output_tokens: 5 },
      content: [
        { type: "thinking", thinking: "", signature: "x" },
        { type: "text", text: "Adding a chart." },
        {
          type: "tool_use",
          id: "toolu_1",
          name: "add_widget",
          input: { type: "bar" },
        },
      ],
    })
    expect(events.map((e) => e.type)).toEqual([
      "TEXT_MESSAGE_START",
      "TEXT_MESSAGE_CONTENT",
      "TEXT_MESSAGE_END",
      "TOOL_CALL_START",
      "TOOL_CALL_ARGS",
      "TOOL_CALL_END",
    ])
    expect(response.status).toBe("completed")
    expect(response.output).toHaveLength(2)
    expect(response.output[1]).toMatchObject({
      type: "function_call",
      callId: "toolu_1",
      name: "add_widget",
      arguments: '{"type":"bar"}',
    })
    expect(response.usage).toMatchObject({ inputTokens: 10, outputTokens: 5 })
  })

  it("strips a fenced JSON reply", () => {
    const { response } = fromClaudeMessage(
      {
        id: "m",
        model: "x",
        stop_reason: "end_turn",
        content: [{ type: "text", text: '```json\n{"a":1}\n```' }],
      },
      true
    )
    expect(response.output[0]).toMatchObject({
      content: [{ type: "text", text: '{"a":1}' }],
    })
  })
})

describe("isNewUserTurn", () => {
  it("is true only when the person (not a tool result) spoke last", async () => {
    const { isNewUserTurn } = await import("@/lib/ai/claude-adapter")
    const base = { system: "", tools: [] }
    const user = { role: "user" as const, content: [{ type: "text", text: "hi" }] }
    const call = {
      role: "assistant" as const,
      content: [{ type: "tool_use", id: "t1", name: "x", input: {} }],
    }
    const result = {
      role: "user" as const,
      content: [{ type: "tool_result", tool_use_id: "t1", content: "ok" }],
    }
    expect(isNewUserTurn({ ...base, messages: [user] })).toBe(true)
    expect(isNewUserTurn({ ...base, messages: [user, call, result] })).toBe(false)
    expect(isNewUserTurn({ ...base, messages: [] })).toBe(false)
  })
})
