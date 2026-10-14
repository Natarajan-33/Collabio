"""Resolve the creator and brand names a user spoke to the creators and offers on screen."""

from difflib import SequenceMatcher
from uuid import UUID

from app.schemas.voice import CreatorRef, OfferRef

FUZZY_THRESHOLD = 0.8


def _normalize(text: str) -> str:
    """`" @Arjun  Mehta "` -> `"arjun mehta"`: case, spacing and a leading @ do not matter."""
    return " ".join(text.casefold().removeprefix("@").split())


def _keys(creator: CreatorRef) -> tuple[str, str, str]:
    """What a user may call a creator: full name, first name, handle."""
    name = _normalize(creator.name)
    return name, name.split(" ")[0], _normalize(creator.handle)


def _match(spoken: str, visible: list[CreatorRef]) -> list[CreatorRef]:
    """The creators one spoken name refers to; empty when it matches none.

    A full name or handle wins outright. A first name may fit several creators and then
    selects all of them. Otherwise the closest creator wins, if it is close enough.
    """
    keyed = [(creator, _keys(creator)) for creator in visible]
    full_or_handle = [c for c, (name, _, handle) in keyed if spoken in (name, handle)]
    if full_or_handle:
        return full_or_handle
    first_name = [c for c, (_, first, _) in keyed if spoken == first]
    if first_name:
        return first_name

    best, best_ratio = None, 0.0
    for creator, keys in keyed:
        ratio = max(SequenceMatcher(None, spoken, key).ratio() for key in keys)
        if ratio > best_ratio:
            best, best_ratio = creator, ratio
    return [best] if best is not None and best_ratio >= FUZZY_THRESHOLD else []


def resolve_creator_refs(names: list[str], visible: list[CreatorRef]) -> list[UUID]:
    """Ids of the visible creators that `names` refer to, in the order spoken, without repeats.

    Matching is case-insensitive on full name, first name or handle (with or without `@`),
    falling back to a fuzzy match (similarity >= 0.8) to absorb speech-to-text slips.
    Names that match no visible creator are dropped.
    """
    ids: dict[UUID, None] = {}
    for name in names:
        spoken = _normalize(name)
        if spoken:
            for creator in _match(spoken, visible):
                ids[creator.id] = None
    return list(ids)


def resolve_offer_ref(name: str, offers: list[OfferRef]) -> UUID | None:
    """The thread of the one visible offer that the spoken brand name refers to, or None.

    Matches like creators do (full name or first word, then a fuzzy match). When the name
    fits several offers (two campaigns from one brand) it is ambiguous, so None: opening the
    wrong offer is worse than asking again.
    """
    spoken = _normalize(name)
    if not spoken:
        return None
    keyed = [(offer, _normalize(offer.brand_name)) for offer in offers]
    full = [offer for offer, key in keyed if spoken == key]
    first = [offer for offer, key in keyed if spoken == key.split(" ")[0]]
    for found in (full, first):
        if found:
            return found[0].thread_id if len(found) == 1 else None

    best, best_ratio, tied = None, 0.0, False
    for offer, key in keyed:
        ratio = max(
            SequenceMatcher(None, spoken, key).ratio(),
            SequenceMatcher(None, spoken, key.split(" ")[0]).ratio(),
        )
        if ratio > best_ratio:
            best, best_ratio, tied = offer, ratio, False
        elif ratio == best_ratio:
            tied = True
    if best is None or tied or best_ratio < FUZZY_THRESHOLD:
        return None
    return best.thread_id
