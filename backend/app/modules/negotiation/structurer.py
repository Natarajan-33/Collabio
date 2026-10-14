"""Turn a finished call's transcript, or a creator's email reply, into terms with Gemini."""

import logging

from app.adapters.gemini import GeminiInvalidOutput, GeminiPort, GeminiUnavailable
from app.modules.negotiation.prompts import (
    REPLY_SYSTEM,
    STRUCTURER_SYSTEM,
    CallAsk,
    ReplyContext,
    StructuredCall,
    StructuredReply,
    reply_prompt,
    structurer_prompt,
)
from app.schemas.negotiation import NegotiationTerms, TranscriptTurn

logger = logging.getLogger(__name__)


async def structure_call(
    gemini: GeminiPort | None,
    *,
    ask: CallAsk,
    turns: list[TranscriptTurn],
    logged: list[NegotiationTerms],
) -> StructuredCall | None:
    """The creator's final terms and a summary, or None when Gemini is missing, down or
    gives output that does not fit. The terms always carry `source = "call"`."""
    if gemini is None:
        return None
    try:
        result = await gemini.generate_structured(
            system=STRUCTURER_SYSTEM,
            prompt=structurer_prompt(ask=ask, turns=turns, logged=logged),
            schema=StructuredCall,
        )
    except (GeminiUnavailable, GeminiInvalidOutput) as exc:
        logger.warning("Structuring the call failed: %s", exc)
        return None
    return result.model_copy(update={"terms": result.terms.model_copy(update={"source": "call"})})


async def structure_reply(
    gemini: GeminiPort | None, *, ctx: ReplyContext, body: str
) -> StructuredReply | None:
    """The creator's position in an email reply and a summary, or None when Gemini is missing,
    down or gives output that does not fit. The terms always carry `source = "email"`."""
    if gemini is None:
        return None
    try:
        result = await gemini.generate_structured(
            system=REPLY_SYSTEM, prompt=reply_prompt(ctx, body), schema=StructuredReply
        )
    except (GeminiUnavailable, GeminiInvalidOutput) as exc:
        logger.warning("Structuring the email reply failed: %s", exc)
        return None
    return result.model_copy(update={"terms": result.terms.model_copy(update={"source": "email"})})
