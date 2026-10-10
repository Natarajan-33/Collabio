"""The call structurer: the prompt it builds and how it degrades."""

from datetime import date

from app.adapters.gemini import GeminiUnavailable
from app.modules.negotiation.prompts import (
    STRUCTURER_SYSTEM,
    CallAsk,
    StructuredCall,
    structurer_prompt,
)
from app.modules.negotiation.structurer import structure_call
from app.schemas.negotiation import NegotiationTerms, TranscriptTurn

ASK = CallAsk(
    videos=3,
    price_cents=100000,
    go_live_by=date(2026, 11, 9),
    format="short_video",
    package_one_liner="3 videos/contract · $1,200",
)
TURNS = [
    TranscriptTurn(role="agent", text="Would three videos for $1,000 work?", t=3),
    TranscriptTurn(role="user", text="three for thirteen hundred", t=67),
]


def terms(**overrides) -> NegotiationTerms:
    base = {"videos": 3, "price_cents": 120000, "stance": "counter", "source": "email"}
    return NegotiationTerms(**(base | {"confidence": 0.9} | overrides))


def test_structurer_prompt_has_ask_and_turns():
    logged = [terms(source="call")]

    prompt = structurer_prompt(ask=ASK, turns=TURNS, logged=logged)

    assert "$1,000" in prompt
    assert "3 videos" in prompt
    assert "2026-11-09" in prompt
    assert "[0:03] Agent: Would three videos for $1,000 work?" in prompt
    assert "[1:07] Creator: three for thirteen hundred" in prompt
    assert '"price_cents": 120000' in prompt


def test_structurer_system_states_the_rules():
    for needle in ("Never invent", "no_commitment", "0.6", "transcript wins"):
        assert needle in STRUCTURER_SYSTEM


async def test_structure_call_invalid_output_returns_none(fake_gemini):
    fake_gemini.queue_structured({"terms": {"stance": "bogus"}})

    assert await structure_call(fake_gemini, ask=ASK, turns=TURNS, logged=[]) is None
    assert len(fake_gemini.calls) == 1


async def test_structure_call_unavailable_returns_none(fake_gemini):
    class Down:
        async def generate_structured(self, **kwargs):
            raise GeminiUnavailable("down")

    assert await structure_call(Down(), ask=ASK, turns=TURNS, logged=[]) is None


async def test_structure_call_without_gemini_returns_none():
    assert await structure_call(None, ask=ASK, turns=TURNS, logged=[]) is None


async def test_structure_call_forces_source_call(fake_gemini):
    fake_gemini.queue_structured(StructuredCall(terms=terms(source="email"), summary="Agreed."))

    result = await structure_call(fake_gemini, ask=ASK, turns=TURNS, logged=[])

    assert result is not None
    assert result.terms.source == "call"
    assert result.terms.price_cents == 120000
    assert result.summary == "Agreed."


async def test_structure_call_sends_system_prompt_and_schema(fake_gemini):
    fake_gemini.queue_structured(StructuredCall(terms=terms(), summary="Agreed."))

    await structure_call(fake_gemini, ask=ASK, turns=TURNS, logged=[])

    ((system, prompt, schema),) = fake_gemini.calls
    assert system == STRUCTURER_SYSTEM
    assert prompt == structurer_prompt(ask=ASK, turns=TURNS, logged=[])
    assert schema is StructuredCall
