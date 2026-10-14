"""Voice: the Scribe token, and the screen-scoped command a transcript is routed into.

`RoutedIntent` is what Gemini returns (creators named, not identified); `VoiceIntent` is
what the API returns (names resolved to ids, package draft merged into the open draft).
"""

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas.discovery import SearchRequest
from app.schemas.negotiation import TermsDraft
from app.schemas.packages import PackageDraft

VoiceScreen = Literal[
    "discover", "review", "packages", "brief", "board", "offers", "offer_desk", "any"
]
# The pages a spoken "go to ..." may open; the model cannot name any other route.
NavigateRoute = Literal[
    "/brand/discover",
    "/brand/discover/review",
    "/brand/batches",
    "/brand/deals",
    "/creator/packages",
    "/creator/offers",
    "/creator/deals",
]
IntentKind = Literal[
    "search",
    "select",
    "clear_selection",
    "open_review",
    "package_draft",
    "open_thread",
    "sort",
    "open_offer",
    "counter",
    "accept",
    "decline",
    "award",
    "navigate",
    "unclear",
]
# How the board orders its threads, spoken as "cheapest", "best value", "by status", "newest".
BoardSortKey = Literal["best_value", "price", "status", "recent"]

# `unclear` is always allowed: it is how a router says "nothing here applies".
ALLOWED_INTENTS: dict[VoiceScreen, set[str]] = {
    "discover": {"search", "select", "clear_selection", "open_review", "navigate"},
    "review": {"search", "select", "clear_selection", "open_review", "navigate"},
    "packages": {"package_draft", "navigate"},
    "brief": {"navigate"},  # the conversation agent handles the brief itself
    "board": {"open_thread", "sort", "counter", "award", "decline", "navigate"},
    "offers": {"open_offer", "navigate"},
    "offer_desk": {"counter", "accept", "decline", "navigate"},
    "any": {"navigate"},
}


class ScribeToken(BaseModel):
    """A single-use ElevenLabs realtime Scribe token for the browser; `expires_at` is ISO 8601."""

    token: str
    expires_at: str


class CreatorRef(BaseModel):
    """A creator on screen, so "select Maya" can be resolved to an id."""

    id: UUID
    name: str
    handle: str


class OfferRef(BaseModel):
    """An offer on the creator's list, so "open the Lumen offer" can be resolved to its thread."""

    thread_id: UUID
    brand_name: str


class VoiceContext(BaseModel):
    """What the screen shows: the creators or offers in view, the package draft being
    dictated and the terms on the table (the offer desk's, or the open board drawer's)."""

    visible_creators: list[CreatorRef] = []
    visible_offers: list[OfferRef] = []
    package_draft: PackageDraft | None = None
    current_terms: TermsDraft | None = None
    # On the board: whose thread `current_terms` belong to (the open drawer's creator).
    current_terms_creator_id: UUID | None = None


class VoiceCommandRequest(BaseModel):
    screen: VoiceScreen
    transcript: str = Field(min_length=1, max_length=500)
    context: VoiceContext


class SelectArgs(BaseModel):
    """Which creators to select: those named (`creator_ids`) or the first `top_n` shown."""

    creator_ids: list[UUID] = []
    top_n: int | None = Field(None, ge=1, le=48)


class OpenThreadArgs(BaseModel):
    """Whose thread to open on the board."""

    creator_id: UUID


class RoutedSelect(BaseModel):
    """`SelectArgs` as the model gives it: creators by the name the user said."""

    creator_names: list[str] = []
    top_n: int | None = Field(None, ge=1, le=48)


class RoutedIntent(BaseModel):
    """The model's reading of a transcript; the service turns it into a `VoiceIntent`."""

    kind: IntentKind
    heard: str
    search: SearchRequest | None = None
    select: RoutedSelect | None = None
    package_draft: PackageDraft | None = None
    open_thread_name: str | None = None
    sort: BoardSortKey | None = None
    navigate: NavigateRoute | None = None
    terms: TermsDraft | None = None
    creator_name: str | None = None
    brand_name: str | None = None
    reason: str | None = None
    suggestions: list[str] = []


class VoiceIntent(BaseModel):
    """What the screen should do. Only the field for `kind` is set; `unclear` carries
    `suggestions` of what to say instead."""

    kind: IntentKind
    heard: str
    search: SearchRequest | None = None
    select: SelectArgs | None = None
    package_draft: PackageDraft | None = None
    open_thread: OpenThreadArgs | None = None
    sort: BoardSortKey | None = None
    navigate: NavigateRoute | None = None
    terms: TermsDraft | None = None
    creator_id: UUID | None = None
    thread_id: UUID | None = None
    reason: str | None = None
    suggestions: list[str] = []
