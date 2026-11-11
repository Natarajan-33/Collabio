"""Launch planning: which channel each creator of a brief is contacted on, and who is left out.

Pure; the service loads the candidates and writes the plan.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from uuid import UUID

from app.core.guardrails import channel_violation, default_channel
from app.schemas.briefs import ChannelPlan, LaunchExclusion
from app.schemas.packages import PreferredChannel


class ChannelNotAllowed(Exception):
    """The brand chose a channel this creator may not be contacted on."""

    def __init__(self, creator_id: UUID, message: str) -> None:
        super().__init__(f"{creator_id}: {message}")
        self.creator_id = creator_id
        self.message = message


@dataclass(frozen=True)
class LaunchCandidate:
    """A creator of the brief with the package it is compared against and the contact flags."""

    creator_id: UUID
    package_id: UUID
    preferred_channel: PreferredChannel
    phone: str | None
    phone_opt_in: bool
    contact_opt_out: bool


@dataclass(frozen=True)
class PlannedThread:
    creator_id: UUID
    package_id: UUID
    channel_plan: ChannelPlan


def plan_launch(
    candidates: Sequence[LaunchCandidate],
    channels: Mapping[UUID, ChannelPlan],
    *,
    email_only: bool = False,
) -> tuple[list[PlannedThread], list[LaunchExclusion]]:
    """One thread per creator who may be contacted, and the creators left out.

    Creators who opted out of contact are excluded even when a channel was chosen for them.
    A creator without a chosen channel gets `default_channel`. A chosen channel that breaks
    `channel_violation` raises `ChannelNotAllowed`.
    """
    planned: list[PlannedThread] = []
    excluded: list[LaunchExclusion] = []
    for c in candidates:
        if c.contact_opt_out:
            excluded.append(LaunchExclusion(creator_id=c.creator_id, reason="Opted out of contact"))
            continue
        plan = channels.get(c.creator_id) or default_channel(
            c.preferred_channel, c.phone, c.phone_opt_in
        )
        reason = channel_violation(
            plan, phone=c.phone, phone_opt_in=c.phone_opt_in, contact_opt_out=False
        )
        if reason:
            raise ChannelNotAllowed(c.creator_id, reason)
        planned.append(PlannedThread(c.creator_id, c.package_id, "email" if email_only else plan))
    return planned, excluded
