"""The committed seed data: creators.json is valid and well spread, embeddings.json covers it."""

import json
from collections import Counter
from pathlib import Path
from typing import get_args

from app.core.package_rules import validate_package
from app.core.package_text import creator_embedding_document, text_hash
from app.schemas.packages import Niche, PackageTerms
from scripts.seed import plus_address
from scripts.seed_data import published_terms

SEED_DIR = Path(__file__).resolve().parents[2] / "supabase" / "seed"
DATA = json.loads((SEED_DIR / "creators.json").read_text(encoding="utf-8"))
CREATORS = DATA["creators"]
NICHES = get_args(Niche)
EXPECTED_NICHE_COUNTS = {
    "consumer_tech": 14,
    "beauty": 6,
    "fitness": 6,
    "food": 6,
    "gaming": 6,
    "b2b_saas": 2,
}
PACKAGE_EXTRA_KEYS = {"status", "floor_price_cents"}


def _terms(package: dict) -> PackageTerms:
    return PackageTerms(**{k: v for k, v in package.items() if k not in PACKAGE_EXTRA_KEYS})


def test_forty_creators_across_six_niches():
    assert len(CREATORS) == 40
    assert {n for c in CREATORS for n in c["niches"]} == set(NICHES)


def test_niche_split_matches_the_plan():
    assert Counter(n for c in CREATORS for n in c["niches"]) == EXPECTED_NICHE_COUNTS


def test_enough_demo_matches():
    hits = [
        c
        for c in CREATORS
        if "consumer_tech" in c["niches"]
        and any(
            p["content_type"] == "short_video"
            and p["base_price_cents"] <= 200000
            and p["status"] == "published"
            for p in c["packages"]
        )
    ]
    assert len(hits) >= 12


def test_every_package_passes_rules_and_has_floor_below_base():
    for creator in CREATORS:
        assert 1 <= len(creator["packages"]) <= 3, creator["handle"]
        for package in creator["packages"]:
            where = f"{creator['handle']}/{package['name']}"
            assert validate_package(_terms(package), creator["niches"]) == [], where
            assert package["status"] in ("draft", "published"), where
            assert 40_000 <= package["base_price_cents"] <= 600_000, where
            floor = package["floor_price_cents"]
            assert 0.70 * package["base_price_cents"] <= floor <= 0.90 * package["base_price_cents"]
            assert floor < package["base_price_cents"], where


def test_every_creator_has_a_published_package():
    for creator in CREATORS:
        assert any(p["status"] == "published" for p in creator["packages"]), creator["handle"]


def test_profile_numbers_and_regions_are_realistic():
    for creator in CREATORS:
        assert 8_000 <= creator["followers"] <= 1_200_000, creator["handle"]
        assert 1.5 <= creator["engagement_rate"] <= 9.0, creator["handle"]
        assert creator["region"] in {"US", "IN", "UK", "CA", "AU"}, creator["handle"]
        assert creator["languages"], creator["handle"]
        assert creator["platforms"], creator["handle"]


def test_handles_unique_and_valid():
    handles = [c["handle"] for c in CREATORS]
    assert len(set(handles)) == len(handles)
    assert all(h == h.lower() and 2 <= len(h) <= 30 for h in handles)


def test_contacts_are_fictional():
    for creator in CREATORS:
        assert creator["email"].endswith("@example.com"), creator["handle"]
        assert creator["phone"] is None, creator["handle"]  # Arjun's comes from DEMO_HELPER_PHONE


def test_only_arjun_opts_in_to_phone():
    assert [c["handle"] for c in CREATORS if c["phone_opt_in"]] == ["arjuntech"]


def test_demo_creators_present():
    by = {c["handle"]: c for c in CREATORS}
    assert by["arjuntech"]["phone_opt_in"] is True
    assert by["arjuntech"]["packages"][0]["preferred_channel"] == "phone_ok"
    assert by["priyareviews"]["packages"][0]["preferred_channel"] == "email_first"


def test_demo_packages_match_the_script():
    by = {c["handle"]: c for c in CREATORS}
    arjun, priya = by["arjuntech"], by["priyareviews"]
    assert arjun["name"] == "Arjun Mehta" and priya["name"] == "Priya Raman"
    for creator, name, addon_cents, lead_days in (
        (arjun, "Launch Duo", 40_000, 14),
        (priya, "Review Pair", 45_000, 21),
    ):
        package = creator["packages"][0]
        assert package["name"] == name
        assert package["status"] == "published"
        assert package["content_type"] == "short_video"
        assert (package["volume_count"], package["volume_basis"]) == (2, "per_contract")
        assert package["base_price_cents"] == 100_000
        assert package["addons"] == [
            {"name": "Extra video", "price_cents": addon_cents, "unit": "video"}
        ]
        assert package["lead_time_days"] == lead_days


def test_plus_address():
    assert plus_address("a.b@x.com", "arjun") == "a.b+arjun@x.com"


def test_cache_covers_every_creator():
    cache = json.loads((SEED_DIR / "embeddings.json").read_text(encoding="utf-8"))
    for creator in CREATORS:
        title, text = creator_embedding_document(
            creator["name"], creator["bio"], creator["niches"], published_terms(creator)
        )
        vector = cache[text_hash(title, text)]
        assert len(vector) == 768, creator["handle"]
        assert all(isinstance(x, float) for x in vector)
