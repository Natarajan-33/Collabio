"""What the call structurer is told and what it hands back.

`CallAsk` and `structurer_prompt` deliberately have no field for the brand's budget ceiling:
whatever is not passed in cannot reach the model, the stored summary or an event (spec 6.2).
"""

import json
from datetime import date

from pydantic import BaseModel, Field

from app.core.money import format_cents
from app.core.package_text import display_label
from app.schemas.negotiation import NegotiationTerms, TranscriptTurn
from app.schemas.packages import ContentType

STRUCTURER_SYSTEM = """\
You read a phone call between an AI agent (`Agent`) negotiating for a brand and a content \
creator (`Creator`). Return the creator's final position: the last terms the creator proposed \
or agreed to.

Rules:
- `price_cents` is the total for all videos in integer US cents, and only if a number was said \
for it. Fill `videos` only if said, and `go_live_by` (YYYY-MM-DD) only if a date was agreed; \
otherwise use null. Never invent or infer numbers.
- `stance`: `counter` = the creator proposed different terms; `accept` = the creator agreed to \
the ask or to the agent's offer; `decline` = the creator refused; `question` = the creator needs \
information first; `no_commitment` = no position, e.g. "call me later"; `offer` = only the \
agent's offer stands and the creator did not answer it.
- `conditions` are short phrases for conditions the creator attached. `open_questions` are the \
creator's unanswered questions.
- `confidence` is between 0 and 1. It is below 0.6 when the call is short, garbled, a voicemail \
or contradictory.
- `summary` is 1-3 neutral sentences on what was agreed or left open. Never mention budgets, \
limits, tools or internal checks.
- The logged offers are hints recorded during the call; the transcript wins when they disagree.
"""


class CallAsk(BaseModel):
    """What the brand asked for on the call, as the agent was told it."""

    videos: int
    price_cents: int
    go_live_by: date
    format: ContentType
    package_one_liner: str


class StructuredCall(BaseModel):
    """The model's reading of a finished call."""

    terms: NegotiationTerms
    summary: str = Field(max_length=600)


def _clock(seconds: float) -> str:
    whole = int(seconds)
    return f"{whole // 60}:{whole % 60:02d}"


def structurer_prompt(
    *, ask: CallAsk, turns: list[TranscriptTurn], logged: list[NegotiationTerms]
) -> str:
    videos = f"{ask.videos} video" if ask.videos == 1 else f"{ask.videos} videos"
    lines = [
        "The ask:",
        (
            f"- {videos}, {display_label(ask.format)}, {format_cents(ask.price_cents)} in total,"
            f" live by {ask.go_live_by.isoformat()}"
        ),
        f"- The creator's listed package: {ask.package_one_liner}",
        "",
        "Offers logged during the call (hints; the transcript wins):",
        json.dumps([terms.model_dump(mode="json") for terms in logged]),
        "",
        "Transcript:",
    ]
    for turn in turns:
        speaker = "Agent" if turn.role == "agent" else "Creator"
        lines.append(f"[{_clock(turn.t)}] {speaker}: {turn.text}")
    return "\n".join(lines)
