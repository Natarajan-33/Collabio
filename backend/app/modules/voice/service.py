"""Voice intent router: one transcript, one screen, one typed intent.

Gemini reads the transcript under the rules in `prompts`; this service then enforces what
the model cannot be trusted with: only intents the screen allows, creators resolved to
real ids, and a package draft merged into the one already open. Anything it cannot use
becomes `unclear` with suggestions, so a bad model reply never reaches the screen.
"""

import logging

from pydantic import ValidationError

from app.adapters.gemini import GeminiInvalidOutput, GeminiPort, GeminiUnavailable
from app.core.package_rules import merge_package_draft
from app.core.refs import resolve_creator_refs
from app.modules.voice.prompts import ROUTER_SYSTEM, router_prompt
from app.schemas.packages import PackageDraft
from app.schemas.voice import (
    ALLOWED_INTENTS,
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
    "any": ["Go to discover", "Go to my packages"],
}


class VoiceUnavailable(Exception):
    """The model could not be reached, so the command could not be routed."""


class VoiceService:
    def __init__(self, gemini: GeminiPort) -> None:
        self._gemini = gemini

    async def route(self, req: VoiceCommandRequest) -> VoiceIntent:
        """The intent for `req.transcript` on `req.screen`.

        A reply the model got wrong (invalid, off-screen, missing what its kind needs)
        is `unclear`. Raises `VoiceUnavailable` when the model cannot be reached.
        """
        try:
            routed = await self._gemini.generate_structured(
                system=ROUTER_SYSTEM, prompt=router_prompt(req), schema=RoutedIntent
            )
        except (ValidationError, GeminiInvalidOutput) as exc:
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
        case "navigate" if routed.navigate is not None:
            return VoiceIntent(kind=kind, heard=heard, navigate=routed.navigate)
    return unclear  # the kind's payload is missing, or names matched no visible creator
