import pytest

from scripts.build_embedding_cache import build_cache
from scripts.seed_data import embedding_hash, load_creators
from tests.fakes import FakeGemini

CREATORS = load_creators()[:3]


async def test_embeds_only_missing_hashes_and_rounds_to_six_places():
    gemini = FakeGemini()
    first, third = embedding_hash(CREATORS[0]), embedding_hash(CREATORS[2])
    cached = {first: [0.5] * 768}

    cache, embedded = await build_cache(lambda: gemini, CREATORS, cached)

    assert embedded == 2 and gemini.embed_calls == 1
    assert cache[first] == [0.5] * 768  # untouched
    assert all(len(v) == 768 for v in cache.values())
    assert all(round(x, 6) == x for x in cache[third])


async def test_complete_cache_never_builds_a_client_and_stale_entries_are_dropped():
    cached = {embedding_hash(c): [0.0] * 768 for c in CREATORS}
    cached["0" * 64] = [1.0] * 768

    def no_client():
        raise AssertionError("a complete cache must not need Gemini")

    cache, embedded = await build_cache(no_client, CREATORS, cached)

    assert embedded == 0
    assert set(cache) == {embedding_hash(c) for c in CREATORS}


@pytest.mark.parametrize("creator", CREATORS)
def test_hash_ignores_draft_packages(creator):
    with_draft = {
        **creator,
        "packages": [
            *creator["packages"],
            {**creator["packages"][0], "status": "draft", "name": "X"},
        ],
    }
    assert embedding_hash(with_draft) == embedding_hash(creator)
