import Anthropic from "@anthropic-ai/sdk"
import { type NextRequest, NextResponse } from "next/server"

import { isNewUserTurn, sanitizeClaudeBody } from "@/lib/ai/claude-adapter"
import { createSupabaseServer } from "@/lib/supabase/server"

/** The dashboard agent's model; pinned here so the browser cannot choose another. */
const MODEL = "claude-sonnet-5-5"
const MAX_TOKENS = 4096

let client: Anthropic | null = null

/**
 * `POST /api/ai/claude`: one Claude turn for the AG Studio "Ask Collabio" agent. The key stays
 * on the server; the signed-in brand's daily demo cap is charged through the backend first.
 */
export async function POST(request: NextRequest) {
  const apiKey = process.env.ANTHROPIC_API_KEY
  if (!apiKey) {
    return NextResponse.json(
      { error: "The AI assistant is not configured." },
      { status: 503 }
    )
  }

  const supabase = await createSupabaseServer()
  const { data } = await supabase.auth.getSession()
  const token = data.session?.access_token
  if (!token)
    return NextResponse.json({ error: "Sign in first." }, { status: 401 })

  const text = await request.text()
  if (text.length > 2_000_000)
    return NextResponse.json({ error: "Request too large." }, { status: 413 })
  let parsed: unknown
  try {
    parsed = JSON.parse(text)
  } catch {
    return NextResponse.json({ error: "Bad request." }, { status: 400 })
  }
  const clean = sanitizeClaudeBody(parsed)
  if (!clean.ok)
    return NextResponse.json({ error: `Bad request (${clean.reason}).` }, { status: 400 })
  const body = clean.body
  const usage = await fetch(
    `${process.env.NEXT_PUBLIC_API_URL}/api/v1/money/agent-usage?new_turn=${isNewUserTurn(body)}&tokens_k=${Math.min(clean.tokensK, 2000)}`,
    {
      method: "POST",
      headers: { Authorization: `Bearer ${token}` },
    }
  )
  if (usage.status === 429) {
    return NextResponse.json(
      { error: "You've reached today's demo limit for the assistant." },
      { status: 429 }
    )
  }
  if (!usage.ok) {
    return NextResponse.json(
      { error: "Only brands can use the assistant." },
      { status: 403 }
    )
  }

  client ??= new Anthropic({ apiKey })
  try {
    const message = await client.messages.create({
      model: MODEL,
      max_tokens: MAX_TOKENS,
      system: body.system,
      messages: body.messages as Anthropic.MessageParam[],
      ...(body.tools.length
        ? {
            tools: body.tools as Anthropic.Tool[],
            tool_choice: body.tool_choice as Anthropic.ToolChoice,
          }
        : {}),
      // Thinking off between tool calls: AG Studio has no place to replay thinking blocks.
      thinking: { type: "between_tools" } as never,
      output_config: { effort: "medium" },
    } as Anthropic.MessageCreateParamsNonStreaming)
    return NextResponse.json(message)
  } catch (error) {
    if (error instanceof Anthropic.RateLimitError) {
      return NextResponse.json(
        { error: "Claude is busy. Try again shortly." },
        { status: 429 }
      )
    }
    if (error instanceof Anthropic.APIError) {
      return NextResponse.json({ error: error.message }, { status: 502 })
    }
    throw error
  }
}
