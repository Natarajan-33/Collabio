"""Prompt for turning a creator's spoken package description into package fields."""

from app.modules.voice.prompts import MONEY_AND_VOCAB_RULES, PACKAGE_FIELD_GUIDANCE
from app.schemas.packages import DraftFromSpeechRequest

DRAFT_SYSTEM = f"""\
You turn what a creator said about one of their content packages into package fields for a \
creator-marketplace app. The transcript is speech-to-text, so expect filler words, missing \
punctuation and small misspellings.

{PACKAGE_FIELD_GUIDANCE}

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
