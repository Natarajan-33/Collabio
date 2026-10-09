"""The FakeGemini test double keeps the GeminiPort contract that API tests rely on."""

import math

import pytest
from pydantic import BaseModel, PositiveInt

from app.adapters.gemini import GeminiInvalidOutput
from tests.fakes import FakeGemini


class Price(BaseModel):
    cents: PositiveInt


async def test_embeddings_are_deterministic_unit_vectors_768_wide():
    fake = FakeGemini()

    tech, beauty = await fake.embed_documents([("A", "tech"), ("B", "beauty")])
    [tech_again] = await fake.embed_documents([("A", "tech")])

    assert tech == tech_again
    assert tech != beauty
    assert len(tech) == 768
    assert math.isclose(math.fsum(v * v for v in tech), 1.0)


async def test_query_embedding_differs_from_document_with_the_same_text():
    fake = FakeGemini()

    [doc] = await fake.embed_documents([("", "tech")])
    query = await fake.embed_query("tech")

    assert len(query) == 768
    assert query != doc


async def test_embed_calls_counts_each_embedding_request():
    fake = FakeGemini()

    await fake.embed_documents([("A", "tech"), ("B", "beauty")])
    await fake.embed_query("tech creators")

    assert fake.embed_calls == 2


async def test_generate_structured_returns_queued_objects_in_order_and_records_calls():
    fake = FakeGemini()
    fake.queue_structured(Price(cents=100))
    fake.queue_structured({"cents": 200})

    first = await fake.generate_structured(system="sys", prompt="one", schema=Price)
    second = await fake.generate_structured(system="sys", prompt="two", schema=Price)

    assert (first, second) == (Price(cents=100), Price(cents=200))
    assert fake.calls == [("sys", "one", Price), ("sys", "two", Price)]


async def test_queued_dict_that_breaks_the_schema_raises_invalid_output():
    fake = FakeGemini()
    fake.queue_structured({"cents": -5})

    with pytest.raises(GeminiInvalidOutput):
        await fake.generate_structured(system="s", prompt="p", schema=Price)


async def test_generate_structured_with_nothing_queued_fails_the_test():
    with pytest.raises(AssertionError, match="nothing queued"):
        await FakeGemini().generate_structured(system="s", prompt="p", schema=Price)
