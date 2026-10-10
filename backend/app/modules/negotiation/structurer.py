"""Turn a finished call's transcript into the creator's terms with Gemini."""

import logging

from app.adapters.gemini import GeminiInvalidOutput, GeminiPort, GeminiUnavailable
from app.modules.negotiation.prompts import (
    STRUCTURER_SYSTEM,
    CallAsk,
    StructuredCall,
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
