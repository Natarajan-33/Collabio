"""GeminiClient against the real Gemini API (needs GEMINI_API_KEY)."""

import math

import pytest
from pydantic import BaseModel

from app.adapters.gemini import GeminiClient
from app.config import Settings


@pytest.fixture(autouse=True)
def require_gemini_key(settings: Settings) -> None:
    if not settings.gemini_api_key:
        pytest.skip("GEMINI_API_KEY is not set")


def cosine(a: list[float], b: list[float]) -> float:
    dot = math.fsum(x * y for x, y in zip(a, b, strict=True))
    return dot / math.sqrt(math.fsum(x * x for x in a) * math.fsum(y * y for y in b))


@pytest.mark.live
async def test_embed_documents_returns_one_768_vector_per_doc(settings):
    vecs = await GeminiClient(settings).embed_documents([("A", "tech"), ("B", "beauty")])
    assert len(vecs) == 2 and all(len(v) == 768 for v in vecs)


@pytest.mark.live
async def test_documents_embed_separately_and_a_query_finds_the_closer_one(settings):
    client = GeminiClient(settings)
    tech, beauty = await client.embed_documents(
        [
            ("Maya", "Reviews smartphones, laptops and wireless earbuds"),
            ("Lena", "Skincare routines and makeup tutorials"),
        ]
    )
    query = await client.embed_query("creators who review gadgets")

    assert tech != beauty
    for vec in (tech, beauty, query):
        assert math.isclose(math.fsum(v * v for v in vec), 1.0, abs_tol=1e-3)
    assert cosine(query, tech) > cosine(query, beauty)


class Sum(BaseModel):
    total: int


@pytest.mark.live
async def test_generate_structured_returns_a_validated_model(settings):
    result = await GeminiClient(settings).generate_structured(
        system="You are a calculator. Answer with the requested JSON only.",
        prompt="What is 17 plus 25?",
        schema=Sum,
    )
    assert result == Sum(total=42)
