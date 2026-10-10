"""Voice: the Scribe token, and the screen-scoped command a transcript is routed into.

`RoutedIntent` is what Gemini returns (creators named, not identified); `VoiceIntent` is
what the API returns (names resolved to ids, package draft merged into the open draft).
"""

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas.discovery import SearchRequest
from app.schemas.packages import PackageDraft

VoiceScreen = Literal["discover", "review", "packages", "any"]
# The pages a spoken "go to ..." may open; the model cannot name any other route.
NavigateRoute = Literal["/brand/discover", "/brand/discover/review", "/creator/packages"]
IntentKind = Literal[
    "search", "select", "clear_selection", "open_review", "package_draft", "navigate", "unclear"
]

# `unclear` is always allowed: it is how a router says "nothing here applies".
ALLOWED_INTENTS: dict[VoiceScreen, set[str]] = {
    "discover": {"search", "select", "clear_selection", "open_review", "navigate"},
    "review": {"search", "select", "clear_selection", "open_review", "navigate"},
    "packages": {"package_draft", "navigate"},
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


class VoiceContext(BaseModel):
    """What the screen shows: the creators in view and the package draft being dictated."""

    visible_creators: list[CreatorRef] = []
    package_draft: PackageDraft | None = None


class VoiceCommandRequest(BaseModel):
    screen: VoiceScreen
    transcript: str = Field(min_length=1, max_length=500)
    context: VoiceContext


class SelectArgs(BaseModel):
    """Which creators to select: those named (`creator_ids`) or the first `top_n` shown."""

    creator_ids: list[UUID] = []
    top_n: int | None = Field(None, ge=1, le=48)


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
    navigate: NavigateRoute | None = None
    suggestions: list[str] = []


class VoiceIntent(BaseModel):
    """What the screen should do. Only the field for `kind` is set; `unclear` carries
    `suggestions` of what to say instead."""

    kind: IntentKind
    heard: str
    search: SearchRequest | None = None
    select: SelectArgs | None = None
    package_draft: PackageDraft | None = None
    navigate: str | None = None
    suggestions: list[str] = []
