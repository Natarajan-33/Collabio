"""Embeds every seed creator and writes supabase/seed/embeddings.json.

    uv run python -m scripts.build_embedding_cache

The cache maps `text_hash(embedding document)` to its 768-d vector, so the seed never
calls Gemini: only documents whose hash is not cached yet are embedded. Entries for
documents no creator has any more are dropped. Run it again after editing creators.json.
"""

import asyncio
import json
import sys
from collections.abc import Callable

from app.adapters.gemini import GeminiClient, GeminiPort
from app.config import get_settings
from scripts.seed_data import (
    EMBEDDINGS_PATH,
    Creator,
    Embeddings,
    embedding_document,
    embedding_hash,
    load_creators,
    load_embeddings,
)

VECTOR_DECIMALS = 6


async def build_cache(
    make_gemini: Callable[[], GeminiPort], creators: list[Creator], cached: Embeddings
) -> tuple[Embeddings, int]:
    """The cache covering exactly `creators`, and how many vectors were newly embedded.

    `make_gemini` is called only when something is missing, so a complete cache needs
    no API key.
    """
    hashes = {c["handle"]: embedding_hash(c) for c in creators}
    missing = {hashes[c["handle"]]: c for c in creators if hashes[c["handle"]] not in cached}
    fresh: Embeddings = {}
    if missing:
        vectors = await make_gemini().embed_documents(
            [embedding_document(c) for c in missing.values()]
        )
        fresh = {h: [round(x, VECTOR_DECIMALS) for x in v] for h, v in zip(missing, vectors)}
    return {h: cached[h] if h in cached else fresh[h] for h in hashes.values()}, len(fresh)


async def main() -> int:
    settings = get_settings()
    creators, cached = load_creators(), load_embeddings()
    if any(embedding_hash(c) not in cached for c in creators) and not settings.gemini_api_key:
        print("GEMINI_API_KEY is not set in backend/.env; cannot embed new creators.")
        return 1
    cache, embedded = await build_cache(lambda: GeminiClient(settings), creators, cached)
    EMBEDDINGS_PATH.write_text(json.dumps(cache, separators=(",", ":")) + "\n", encoding="utf-8")
    print(f"embedded {embedded} new, {len(cache) - embedded} cached")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
