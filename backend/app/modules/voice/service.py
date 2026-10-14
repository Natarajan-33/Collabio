"""Voice intent router: one transcript, one screen, one typed intent.

Gemini reads the transcript under the rules in `prompts`; this service then enforces what
the model cannot be trusted with: only intents the screen allows, creators resolved to
real ids, and a package draft merged into the one already open. Anything it cannot use
becomes `unclear` with suggestions, so a bad model reply never reaches the screen.
"""

import logging
from datetime import UTC, date, datetime
from uuid import UUID

from app.adapters.gemini import GeminiInvalidOutput, GeminiPort, GeminiUnavailable
from app.core.package_rules import merge_package_draft
from app.core.refs import resolve_creator_refs, resolve_offer_ref
from app.modules.voice.prompts import ROUTER_SYSTEM, router_prompt
from app.schemas.negotiation import TermsDraft
from app.schemas.packages import PackageDraft
from app.schemas.voice import (
    ALLOWED_INTENTS,
    OpenThreadArgs,
    RoutedIntent,
    SelectArgs,
    VoiceCommandRequest,
    VoiceIntent,
    VoiceScreen,
)

logger = logging.getLogger(__name__)

MAX_SUGGESTIONS = 3
# Shown when the model is unsure but offers nothing better, or its reply is unusable.
DEFAULT_SUGGESTIONS: dict[VoiceScreen, list[str]] = {
    "discover": [
        "Tech creators doing short videos under two thousand dollars",
        "Select the top ten",
        "Open review",
    ],
    "review": [
        "Select the top five",
        "Clear selection",
        "Beauty creators under one thousand dollars",
    ],
    "packages": [
        "Three short videos for twelve hundred dollars",
        "Add a thumbnail pack for fifty dollars",
        "Lead time is five days",
    ],
    "brief": ["Go to the board", "Go to discover"],
    "board": ["Open Priya's thread", "Sort by price", "Sort by best value"],
    "offers": ["Open the Lumen offer", "Go to my deals"],
    "offer_desk": ["Counter at twelve hundred dollars", "Accept this offer", "Decline this offer"],
    "any": ["Go to discover", "Go to my packages"],
}


class VoiceUnavailable(Exception):
    """The model could not be reached, so the command could not be routed."""


class VoiceService:
    def __init__(self, gemini: GeminiPort) -> None:
        self._gemini = gemini

    async def route(self, req: VoiceCommandRequest, today: date | None = None) -> VoiceIntent:
        """The intent for `req.transcript` on `req.screen`. `today` (default: the UTC date) is
        what the model resolves "in three weeks" against.

        A transcript of only whitespace is `unclear` without asking the model. A reply the model got wrong (not valid for the schema, off-screen, missing what
        its kind needs) is `unclear`. Raises `VoiceUnavailable` when the model cannot be
        reached. Anything else, such as pydantic rejecting our own request schema, is a
        bug and propagates rather than hiding behind `unclear`.
        """
        if not req.transcript.strip():
            return VoiceIntent(kind="unclear", heard="", suggestions=[])
        today = today or datetime.now(UTC).date()
        try:
            routed = await self._gemini.generate_structured(
                system=ROUTER_SYSTEM, prompt=router_prompt(req, today), schema=RoutedIntent
            )
        except GeminiInvalidOutput as exc:
            logger.warning("voice router reply unusable: %s", exc)
            return _unclear(req, heard=req.transcript)
        except GeminiUnavailable as exc:
            raise VoiceUnavailable from exc
        return _to_intent(req, routed)


def _unclear(
    req: VoiceCommandRequest, *, heard: str, suggestions: list[str] | None = None
) -> VoiceIntent:
    return VoiceIntent(
        kind="unclear",
        heard=heard,
        suggestions=(suggestions or DEFAULT_SUGGESTIONS[req.screen])[:MAX_SUGGESTIONS],
    )


def _to_intent(req: VoiceCommandRequest, routed: RoutedIntent) -> VoiceIntent:
    """The model's reading as an intent the screen can act on, or `unclear`."""
    heard = routed.heard.strip() or req.transcript
    kind = routed.kind
    unclear = _unclear(req, heard=heard, suggestions=routed.suggestions)
    if kind == "unclear" or kind not in ALLOWED_INTENTS[req.screen]:
        return unclear

    match kind:
        case "search" if routed.search is not None:
            return VoiceIntent(kind=kind, heard=heard, search=routed.search)
        case "select" if routed.select is not None:
            ids = resolve_creator_refs(routed.select.creator_names, req.context.visible_creators)
            if ids or routed.select.top_n is not None:
                select = SelectArgs(creator_ids=ids, top_n=routed.select.top_n)
                return VoiceIntent(kind=kind, heard=heard, select=select)
        case "clear_selection" | "open_review":
            return VoiceIntent(kind=kind, heard=heard)
        case "package_draft" if routed.package_draft is not None:
            current = req.context.package_draft or PackageDraft()
            merged = merge_package_draft(current, routed.package_draft)
            return VoiceIntent(kind=kind, heard=heard, package_draft=merged)
        case "open_thread" if routed.open_thread_name:
            ids = resolve_creator_refs([routed.open_thread_name], req.context.visible_creators)
            if ids:
                open_thread = OpenThreadArgs(creator_id=ids[0])
                return VoiceIntent(kind=kind, heard=heard, open_thread=open_thread)
        case "open_offer" if routed.brand_name:
            thread_id = resolve_offer_ref(routed.brand_name, req.context.visible_offers)
            if thread_id is not None:
                return VoiceIntent(kind=kind, heard=heard, thread_id=thread_id)
        case "counter" if routed.terms is not None:
            creator_id = None
            if req.screen == "board":
                creator_id = _board_creator(routed, req)
                if creator_id is None:
                    return unclear
            terms = _merge_terms(req.context.current_terms, routed.terms)
            return VoiceIntent(kind=kind, heard=heard, terms=terms, creator_id=creator_id)
        case "accept":
            return VoiceIntent(kind=kind, heard=heard)
        case "decline":
            creator_id = None
            if req.screen == "board":
                creator_id = _board_creator(routed, req)
                if creator_id is None:
                    return unclear
            return VoiceIntent(
                kind=kind, heard=heard, creator_id=creator_id, reason=_clean(routed.reason)
            )
        case "award":
            creator_id = _board_creator(routed, req)
            if creator_id is not None:
                return VoiceIntent(kind=kind, heard=heard, creator_id=creator_id)
        case "sort" if routed.sort is not None:
            return VoiceIntent(kind=kind, heard=heard, sort=routed.sort)
        case "navigate" if routed.navigate is not None:
            return VoiceIntent(kind=kind, heard=heard, navigate=routed.navigate)
    return unclear  # the kind's payload is missing, or names matched no visible creator


def _clean(text: str | None) -> str | None:
    """A spoken reason without surrounding whitespace; blank is no reason."""
    return (text or "").strip() or None


def _board_creator(routed: RoutedIntent, req: VoiceCommandRequest) -> UUID | None:
    """The visible creator a board deal intent names, or None when none is named or matched."""
    if not routed.creator_name:
        return None
    ids = resolve_creator_refs([routed.creator_name], req.context.visible_creators)
    return ids[0] if ids else None


def _merge_terms(current: TermsDraft | None, said: TermsDraft) -> TermsDraft:
    """The terms on screen with what was just said laid over them: spoken fields win, spoken
    conditions are added to the current ones (case-insensitive duplicates dropped, first
    spelling kept)."""
    if current is None:
        return said
    conditions: dict[str, str] = {}
    for condition in [*current.conditions, *said.conditions]:
        conditions.setdefault(condition.strip().casefold(), condition.strip())
    return TermsDraft(
        videos=said.videos if said.videos is not None else current.videos,
        price_cents=said.price_cents if said.price_cents is not None else current.price_cents,
        go_live_by=said.go_live_by if said.go_live_by is not None else current.go_live_by,
        conditions=list(conditions.values()),
        note=said.note if said.note is not None else current.note,
    )
