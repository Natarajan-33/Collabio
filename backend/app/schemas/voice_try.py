"""Sample negotiation call for signed-in users (phone is not stored)."""

import re
from typing import Literal

from pydantic import BaseModel, Field, field_validator

TryCallScenario = Literal["standard", "single_video", "rush"]

_E164 = re.compile(r"^\+[1-9][0-9]{1,14}$")


class TryCallRequest(BaseModel):
    """Place a one-off demo call to `phone`; the number is used only to dial."""

    phone: str = Field(description="Mobile number in E.164 form, e.g. +14155550123")
    scenario: TryCallScenario = "standard"

    @field_validator("phone")
    @classmethod
    def phone_must_be_e164(cls, value: str) -> str:
        cleaned = value.strip().replace(" ", "").replace("-", "")
        if not _E164.match(cleaned):
            raise ValueError("Enter a valid mobile number with country code, e.g. +14155550123")
        return cleaned


class TryCallResponse(BaseModel):
    status: Literal["calling"] = "calling"
    message: str


class TryEmailRequest(BaseModel):
    """Send a sample negotiation outreach email; the address is not stored."""

    email: str = Field(description="Inbox to receive the sample email")
    scenario: TryCallScenario = "standard"

    @field_validator("email")
    @classmethod
    def email_must_look_valid(cls, value: str) -> str:
        cleaned = value.strip().lower()
        if "@" not in cleaned or cleaned.startswith("@") or cleaned.endswith("@"):
            raise ValueError("Enter a valid email address")
        return cleaned


class TryEmailResponse(BaseModel):
    status: Literal["sent"] = "sent"
    message: str
