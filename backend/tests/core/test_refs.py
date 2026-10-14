"""Spoken creator names -> ids of the creators on screen."""

from uuid import UUID, uuid4

from app.core.refs import resolve_creator_refs, resolve_offer_ref
from app.schemas.voice import CreatorRef, OfferRef

A, B, C = uuid4(), uuid4(), uuid4()
VIS = [
    CreatorRef(id=A, name="Maya Chen", handle="mayatech"),
    CreatorRef(id=B, name="Arjun Mehta", handle="arjuntech"),
]


def test_resolve_by_first_name():
    assert resolve_creator_refs(["maya"], VIS) == [A]


def test_resolve_by_full_name_ignores_case_and_spacing():
    assert resolve_creator_refs(["  ARJUN   mehta "], VIS) == [B]


def test_resolve_by_handle():
    assert resolve_creator_refs(["@arjuntech"], VIS) == [B]


def test_resolve_by_handle_without_at():
    assert resolve_creator_refs(["MayaTech"], VIS) == [A]


def test_resolve_fuzzy():
    assert resolve_creator_refs(["Arjun Mehtaa"], VIS) == [B]


def test_unmatched_dropped():
    assert resolve_creator_refs(["Zed"], VIS) == []


def test_matched_names_survive_unmatched_ones_in_spoken_order():
    assert resolve_creator_refs(["Arjun", "Zed", "Maya"], VIS) == [B, A]


def test_the_same_creator_named_twice_is_listed_once():
    assert resolve_creator_refs(["maya", "@mayatech", "Maya Chen"], VIS) == [A]


def test_a_shared_first_name_selects_every_creator_who_has_it():
    visible = [*VIS, CreatorRef(id=C, name="Maya Patel", handle="mayap")]
    assert resolve_creator_refs(["maya"], visible) == [A, C]


def test_a_full_name_beats_a_shared_first_name():
    visible = [*VIS, CreatorRef(id=C, name="Maya Patel", handle="mayap")]
    assert resolve_creator_refs(["Maya Patel"], visible) == [C]


def test_fuzzy_match_is_one_creator_the_closest():
    assert resolve_creator_refs(["Arjan"], VIS) == [B]


def test_nothing_visible_or_nothing_said_resolves_to_nothing():
    assert resolve_creator_refs(["maya"], []) == []
    assert resolve_creator_refs([], VIS) == []
    assert resolve_creator_refs(["", "  ", "@"], VIS) == []


def test_ids_are_uuids():
    [resolved] = resolve_creator_refs(["maya"], VIS)
    assert isinstance(resolved, UUID)


def test_resolve_offer_by_brand_name_or_first_word():
    lumen, nova = (
        OfferRef(thread_id=A, brand_name="Lumen Audio"),
        OfferRef(thread_id=B, brand_name="Nova Skin"),
    )
    assert resolve_offer_ref("lumen", [lumen, nova]) == A
    assert resolve_offer_ref(" NOVA  skin ", [lumen, nova]) == B
    assert resolve_offer_ref("Lumen Audioo", [lumen, nova]) == A  # speech-to-text slip
    assert resolve_offer_ref("Acme", [lumen, nova]) is None
    assert resolve_offer_ref("  ", [lumen, nova]) is None


def test_resolve_offer_is_none_when_the_brand_has_two_offers():
    first, second = (
        OfferRef(thread_id=A, brand_name="Lumen Audio"),
        OfferRef(thread_id=B, brand_name="Lumen Audio"),
    )
    assert resolve_offer_ref("lumen", [first, second]) is None
