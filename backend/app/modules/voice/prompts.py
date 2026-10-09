"""Prompts for the voice intent router.

`MONEY_AND_VOCAB_RULES` is shared: anything that turns speech into marketplace terms
(the router here, package dictation later) states these rules the same way.
"""

from typing import get_args

from app.schemas.packages import ContentType, Niche, PreferredChannel, VolumeBasis
from app.schemas.voice import ALLOWED_INTENTS, NavigateRoute, VoiceCommandRequest


def _keys(literal: object) -> str:
    return ", ".join(get_args(literal))


MONEY_AND_VOCAB_RULES = f"""\
Vocabularies (use these exact keys, never other spellings):
- niche: {_keys(Niche)}. "tech", "gadgets", "phones" -> consumer_tech; "software", "SaaS", "B2B" \
-> b2b_saas; "makeup", "skincare" -> beauty; "workout", "gym" -> fitness.
- content_type: {_keys(ContentType)}. "short-form", "reels", "shorts", "TikTok" -> short_video; \
"long-form", "YouTube videos" -> long_video; "stories" -> story; "livestream" -> live.
- volume_basis: {_keys(VolumeBasis)} ("a week", "weekly" -> per_week; "for the whole deal", \
"total" -> per_contract).
- preferred_channel: {_keys(PreferredChannel)}.

Money: every amount is an integer number of US cents. $1 = 100 cents. Convert spoken amounts:
"two grand" or "two thousand dollars" = $2,000 = 200000; "1.5k" or "fifteen hundred" = $1,500 = \
150000; "twelve hundred" = $1,200 = 120000; "five hundred bucks" = 50000; "$49.99" = 4999.
Never return dollars, never return decimals, never guess an amount that was not said."""

ROUTER_SYSTEM = f"""\
You turn one spoken command into one intent for a creator-marketplace app. The transcript is \
speech-to-text, so expect filler words, missing punctuation and small name misspellings.

The user's screen limits what they can do. Allowed intents per screen:
{chr(10).join(f"- {screen}: {', '.join(sorted(kinds))}" for screen, kinds in ALLOWED_INTENTS.items())}
Any screen may also answer unclear. Pick only an intent allowed on the current screen.

Intents:
- search: find creators. search.query is the free-text topic ("short-form tech reviews"); \
search.filters holds only constraints that were said (niches, content_types, max_price_cents, \
min_followers, region). "under", "below", "max", "up to", "at most" an amount means \
filters.max_price_cents. Leave query and filters out when not said.
- select: pick creators. Creators named go in select.creator_names exactly as the user said \
them (match against the visible creators if one is close). "top N" or "first N" (digits or words) \
means select.top_n = N. Do not mix the two unless both were said.
- clear_selection: deselect everything ("clear", "start over").
- open_review: open the side-by-side comparison of the selected creators ("compare", "open review").
- package_draft: the creator is dictating a package. Fill package_draft fields only from what \
was said now; leave every other field null or empty. Do not repeat fields that are already in \
the current draft unless they were changed.
- navigate: go to another page. navigate is one of the routes {", ".join(get_args(NavigateRoute))}.
- unclear: you are not sure what was meant, or the command does not fit the screen. Set \
suggestions to 2 or 3 short example commands that would work on this screen.

heard: the transcript with filler words ("um", "uh", "like", "you know") and false starts \
removed, otherwise word for word. Always set it.

{MONEY_AND_VOCAB_RULES}"""

_NONE = "none"


def router_prompt(req: VoiceCommandRequest) -> str:
    """The per-command part of the request: transcript, screen, creators in view, open draft."""
    creators = "; ".join(f"{c.name} (@{c.handle})" for c in req.context.visible_creators)
    draft = req.context.package_draft
    draft_json = draft.model_dump_json(exclude_defaults=True) if draft else _NONE
    return (
        f"Screen: {req.screen} (allowed: {', '.join(sorted(ALLOWED_INTENTS[req.screen]))})\n"
        f"Visible creators: {creators or _NONE}\n"
        f"Current package draft: {draft_json}\n"
        f'Transcript: "{req.transcript}"'
    )
