"""Plain-English bonus terms → validated BonusTerms via Claude structured output."""

from app.agents.terms_parser import parse_bonus_terms
from app.core.settlement import BonusTerms, Cpm, Tier
from tests.fakes import FakeClaude, claude_text

BOTH = {
    "question": "",
    "has_cpm": True,
    "cpm_rate_per_1k_dollars": 2,
    "cpm_starts_after_views": 200000,
    "cpm_cap_dollars": 500,
    "tiers": [{"views": 1000000, "bonus_dollars": 300}],
}


async def test_parser_converts_dollars_to_cents():
    claude = FakeClaude([claude_text(BOTH)])
    terms = await parse_bonus_terms(claude, "claude-haiku-5-5", "$2 per 1K after 200K ...")
    assert terms == BonusTerms(Cpm(200, 200_000, 50_000), (Tier(1_000_000, 30_000),))
    request = claude.requests[0]
    assert request["model"] == "claude-haiku-5-5"
    assert request["output_config"]["format"]["type"] == "json_schema"
    assert "tool_choice" not in request


async def test_parser_without_cpm():
    payload = {**BOTH, "has_cpm": False, "tiers": [{"views": 500000, "bonus_dollars": 100.5}]}
    terms = await parse_bonus_terms(FakeClaude([claude_text(payload)]), "m", "x")
    assert terms == BonusTerms(None, (Tier(500_000, 10_050),))


async def test_parser_returns_question_when_model_asks():
    payload = {**BOTH, "question": "Is the cap per video or per deal?"}
    out = await parse_bonus_terms(FakeClaude([claude_text(payload)]), "m", "x")
    assert out == "Is the cap per video or per deal?"


async def test_parser_returns_question_on_invalid_terms():
    payload = {
        **BOTH,
        "tiers": [{"views": 900000, "bonus_dollars": 1}, {"views": 100000, "bonus_dollars": 1}],
    }
    out = await parse_bonus_terms(FakeClaude([claude_text(payload)]), "m", "x")
    assert isinstance(out, str) and out
