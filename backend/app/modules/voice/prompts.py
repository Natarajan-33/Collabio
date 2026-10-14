"""Prompts for the voice intent router.

`MONEY_AND_VOCAB_RULES` and `PACKAGE_FIELD_GUIDANCE` are shared: the two ways a package is
dictated (the router's `package_draft` intent, and `/me/packages/draft-from-speech`) read
speech into marketplace terms by the same rules, so they are stated once.
"""

from datetime import date
from typing import get_args

from app.schemas.packages import ContentType, Niche, PreferredChannel, Region, VolumeBasis
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
- preferred_channel: {_keys(PreferredChannel)}. "email first", "email me first" -> email_first; \
"email only", "no calls" -> email_only; "phone is fine", "call me" -> phone_ok.
- region: {_keys(Region)}. Always the code, never a place name. "the US", "USA", "the States", \
"America" -> US; "India", "Indian" -> IN; "the UK", "Britain", "England", "British" -> UK; \
"Canada", "Canadian" -> CA; "Australia", "Aussie" -> AU. For any other place leave region out; \
never invent a code.

Money: every amount is an integer number of US cents. $1 = 100 cents. Convert spoken amounts:
"two grand" or "two thousand dollars" = $2,000 = 200000; "1.5k" or "fifteen hundred" = $1,500 = \
150000; "twelve hundred" = $1,200 = 120000; "five hundred bucks" = 50000; "nine hundred" = $900 = \
90000; "three fifty" or "three hundred fifty" = $350 = 35000; "$49.99" = 4999.
Never return dollars, never return decimals, never guess an amount that was not said."""

PACKAGE_FIELD_GUIDANCE = """\
Package fields (a creator dictating one content package). Fill ONLY what was said in this \
transcript; leave every other field null (or an empty list). Never guess a value, never infer a \
niche or channel that was not mentioned, and do not repeat fields already in the current draft \
unless the creator changed them.
- name: only when the creator names the package ("call it Launch Duo"); never make one up.
- content_type, niche, volume_basis, preferred_channel: from the vocabularies below.
- volume_count: how many videos the package includes per volume_basis ("three videos a week" \
-> 3 per_week; "a pair of videos for the campaign" -> 2 per_contract; "two per contract" -> 2 \
per_contract).
- base_price_cents: the price of the package as described, not of an add-on.
- included: things that come with the package at no extra price ("one revision round", \
"script approval", "30-day usage rights").
- freebies: free bonuses ("a free vertical cutdown for Stories").
- addons: optional priced additions. One more video at a price ("an extra video is four \
hundred", "extra video three fifty") is always an add-on {name: "Extra video", unit: "video"} \
with that price, never an extra; any other priced item is unit "item".
- extras: priced things that are not deliverables ("raw footage for three hundred", "a thumbnail \
pack for fifty bucks"), each with name and price_cents.
- slots_per_month: how many of these packages the creator can take per month.
- lead_time_days: days from agreement to delivery ("two weeks" -> 14).
- currency: leave null."""

ROUTER_SYSTEM = f"""\
You turn one spoken command into one intent for a creator-marketplace app. The transcript is \
speech-to-text, so expect filler words, missing punctuation and small name misspellings.

The user's screen limits what they can do. Allowed intents per screen:
{chr(10).join(f"- {screen}: {', '.join(sorted(kinds))}" for screen, kinds in ALLOWED_INTENTS.items())}
Voice never sends, accepts, declines or awards anything: it only pre-fills what the user then \
confirms on screen. Any screen may also answer unclear. Pick only an intent allowed on the current \
screen.

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
- package_draft: the creator is dictating a package. Fill package_draft by the package field \
rules below.
- open_thread: on the board, "open/show X's thread/card" opens one creator's thread. Set \
open_thread_name to the creator's name exactly as the user said it (match against the visible \
creators if one is close).
- sort: on the board, reorder the threads. Set sort to one of best_value, price, status, recent: \
"sort by price", "cheapest" -> price; "best value", "best deal" -> best_value; "by status" -> \
status; "newest", "latest" -> recent.
- open_offer: on the creator's Offers list, "open the Lumen offer" opens one offer. Set brand_name \
to the brand's name exactly as the user said it (match against the visible offers if one is \
close).
- counter: the user wants to counter. Return `counter` with the terms heard in `terms`; the user \
confirms on screen. Fill only what was said (videos, price_cents, go_live_by, conditions, note); \
leave the rest null, because the app keeps the current terms for anything not said. On the offer \
desk the counter is for the open offer. On the board, set creator_name to the creator whose thread \
is meant, exactly as the user said it. Dates are ISO dates (YYYY-MM-DD) worked out from today's \
date, which the request states: "in three weeks" is today plus 21 days; "two more weeks" is the \
current go-live date plus 14 days, or today plus 14 when there is none.
- accept: on the offer desk only, the creator accepts the brand's current offer. Return `accept` \
with no other fields; the user confirms on screen.
- decline: on the offer desk the creator declines the open offer; on the board the brand declines \
one creator's thread (set creator_name). Put any reason given in `reason`, otherwise leave it \
null. The user confirms on screen.
- award: on the board, "award Priya" starts the award for one creator. Set creator_name to the \
creator as the user said it. The user confirms the milestones on screen.
- navigate: go to another page. navigate is one of the routes {", ".join(get_args(NavigateRoute))}. \
"Go to the board" navigates to /brand/batches; "my offers" -> /creator/offers; "my deals" -> \
/creator/deals for a creator, /brand/deals for a brand. On the brief screen only navigate \
applies (the conversation agent handles the brief itself), so anything else there is unclear.
- unclear: you are not sure what was meant, or the command does not fit the screen. Set \
suggestions to 2 or 3 short example commands that would work on this screen.

heard: the transcript with filler words ("um", "uh", "like", "you know") and false starts \
removed, otherwise word for word. Always set it.

{PACKAGE_FIELD_GUIDANCE}

{MONEY_AND_VOCAB_RULES}"""

_NONE = "none"


def router_prompt(req: VoiceCommandRequest, today: date) -> str:
    """The per-command part of the request: today's date (so "in three weeks" becomes a date),
    transcript, screen, what is in view, the open draft and the terms on the table."""
    ctx = req.context
    creators = "; ".join(f"{c.name} (@{c.handle})" for c in ctx.visible_creators)
    offers = "; ".join(o.brand_name for o in ctx.visible_offers)
    draft = ctx.package_draft
    draft_json = draft.model_dump_json(exclude_defaults=True) if draft else _NONE
    terms = ctx.current_terms
    terms_json = terms.model_dump_json(exclude_defaults=True) if terms else _NONE
    return (
        f"Today (UTC): {today.isoformat()}\n"
        f"Screen: {req.screen} (allowed: {', '.join(sorted(ALLOWED_INTENTS[req.screen]))})\n"
        f"Visible creators: {creators or _NONE}\n"
        f"Visible offers: {offers or _NONE}\n"
        f"Current package draft: {draft_json}\n"
        f"Current terms: {terms_json}\n"
        f'Transcript: "{req.transcript}"'
    )
