"""The prompts that turn speech into marketplace terms (no model involved).

The router and package dictation must read speech the same way, so what they share is
tested as shared: one constant, present in both.
"""

import re
from typing import get_args

import pytest

from app.modules.packages.prompts import DRAFT_SYSTEM
from app.modules.voice.prompts import MONEY_AND_VOCAB_RULES, PACKAGE_FIELD_GUIDANCE, ROUTER_SYSTEM
from app.schemas.packages import Region


def test_region_codes_are_stated_so_the_model_cannot_return_a_country_name():
    assert get_args(Region) == ("US", "IN", "UK", "CA", "AU")
    for code in get_args(Region):
        assert code in MONEY_AND_VOCAB_RULES


@pytest.mark.parametrize(
    ("spoken", "code"),
    [
        ("India", "IN"),
        ("the States", "US"),
        ("Britain", "UK"),
        ("Canada", "CA"),
        ("Australia", "AU"),
    ],
)
def test_spoken_places_map_to_their_codes(spoken, code):
    # The place, then the code it maps to, without another mapping in between.
    assert re.search(rf"{spoken}[^>]*-> {code}\b", MONEY_AND_VOCAB_RULES)


@pytest.mark.parametrize("prompt", [ROUTER_SYSTEM, DRAFT_SYSTEM], ids=["router", "dictation"])
def test_both_package_dictation_paths_share_the_field_guidance(prompt):
    assert PACKAGE_FIELD_GUIDANCE in prompt
    assert MONEY_AND_VOCAB_RULES in prompt


def test_field_guidance_carries_the_dictation_rules():
    for rule in (
        "Extra video",  # a priced extra video is an add-on counted per video
        'unit: "video"',
        "extras",  # priced non-deliverables are not add-ons
        "included",
        "freebies",
        "-> 14",  # "two weeks" -> 14 days
        "only when the creator names the package",
    ):
        assert rule in PACKAGE_FIELD_GUIDANCE, rule
