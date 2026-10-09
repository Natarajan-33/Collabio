"""Prompt for turning a creator's spoken package description into package fields."""

from app.modules.voice.prompts import MONEY_AND_VOCAB_RULES
from app.schemas.packages import DraftFromSpeechRequest

DRAFT_SYSTEM = f"""\
You turn what a creator said about one of their content packages into package fields for a \
creator-marketplace app. The transcript is speech-to-text, so expect filler words, missing \
punctuation and small misspellings.

Fill ONLY what was said in this transcript. Leave every other field null (or an empty list). \
Never guess a value, never infer a niche or channel that was not mentioned, and do not repeat \
fields already in the current draft unless the creator changed them.

Fields:
- name: only when the creator names the package ("call it Launch Duo").
- content_type, niche, volume_basis, preferred_channel: from the vocabularies below.
- volume_count: how many videos the package includes per volume_basis ("three videos a week" \
-> 3 per_week; "a pair of videos for the campaign" -> 2 per_contract).
- base_price_cents: the price of the package as described, not of an add-on.
- included: things that come with the package at no extra price ("one revision round", \
"script approval", "30-day usage rights").
- freebies: free bonuses ("a free vertical cutdown for Stories").
- addons: optional priced additions. One more video at a price ("an extra video is four \
hundred") is {{name: "Extra video", unit: "video"}}; any other priced item is unit "item".
- extras: priced things that are not deliverables ("raw footage for three hundred", "a thumbnail \
pack for fifty bucks"), each with name and price_cents.
- slots_per_month: how many of these packages the creator can take per month.
- lead_time_days: days from agreement to delivery ("two weeks" -> 14).
- currency: leave null.

heard: the transcript with filler words ("um", "uh", "like", "you know") and false starts \
removed, otherwise word for word. Always set it.

{MONEY_AND_VOCAB_RULES}"""

_NONE = "none"


def draft_prompt(req: DraftFromSpeechRequest) -> str:
    """The per-dictation part of the request: the open draft and what was just said."""
    draft_json = req.current.model_dump_json(exclude_defaults=True)
    return (
        f"Current package draft: {draft_json if draft_json != '{}' else _NONE}\n"
        f'Transcript: "{req.transcript}"'
    )
