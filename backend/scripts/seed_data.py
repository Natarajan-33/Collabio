"""The committed seed files (creators.json, embeddings.json) and how a creator maps to a
cached embedding. No database and no network, so the seed and the cache builder share it."""

import json
from pathlib import Path
from typing import Any

from app.core.package_text import creator_embedding_document, text_hash
from app.schemas.packages import PackageTerms

SEED_DIR = Path(__file__).resolve().parent.parent / "supabase" / "seed"
CREATORS_PATH = SEED_DIR / "creators.json"
EMBEDDINGS_PATH = SEED_DIR / "embeddings.json"

# Keys of a package in creators.json that are not `PackageTerms` fields.
PACKAGE_ONLY_KEYS = frozenset({"status", "floor_price_cents"})

Creator = dict[str, Any]
Embeddings = dict[str, list[float]]


def load_creators() -> list[Creator]:
    return json.loads(CREATORS_PATH.read_text(encoding="utf-8"))["creators"]


def load_embeddings() -> Embeddings:
    """The cache `{text_hash: vector}`; empty when it has not been built yet."""
    if not EMBEDDINGS_PATH.exists():
        return {}
    return json.loads(EMBEDDINGS_PATH.read_text(encoding="utf-8"))


def package_terms(package: dict[str, Any]) -> PackageTerms:
    return PackageTerms(**{k: v for k, v in package.items() if k not in PACKAGE_ONLY_KEYS})


def published_terms(creator: Creator) -> list[PackageTerms]:
    """The creator's published packages: the only ones their embedding describes."""
    return [package_terms(p) for p in creator["packages"] if p["status"] == "published"]


def embedding_document(creator: Creator) -> tuple[str, str]:
    return creator_embedding_document(
        creator["name"], creator["bio"], creator["niches"], published_terms(creator)
    )


def embedding_hash(creator: Creator) -> str:
    return text_hash(*embedding_document(creator))
