"""Award a thread into a deal, and read deals.

A `DealsService` is not tied to a brand: each call names the brand or creator it acts for, and
a deal or thread that is not theirs is `DealNotFound` / `ThreadNotFound`, never a permission
error. `award` is one transaction (batch lock, freshness, checks, `awarded` event, deal,
milestones, outbox); the database's deferred milestone trigger is the last line of defence, the
checks here come first. The brief's ceiling is read here for `over_ceiling_cents` and goes no
further; contact emails appear only in `DealView`.
"""

from datetime import date
from uuid import UUID

import asyncpg

from app.adapters.db import Database
from app.core.guardrails import over_ceiling_cents
from app.core.milestones import split_even, validate_milestones
from app.core.terms import agreed_terms
from app.core.thread_state import brand_actions
from app.modules.board.actions import OPEN_STATUSES, ActionNotAllowed
from app.modules.board.service import ThreadNotFound
from app.modules.deals import repo
from app.modules.discovery.service import initials
from app.modules.notify import outbox
from app.modules.threads import repo as threads_repo
from app.schemas.board import CreatorChip
from app.schemas.deals import (
    AgreedTerms,
    AwardPreview,
    AwardRequest,
    DealListItem,
    DealParty,
    DealView,
    MilestoneView,
)
from app.schemas.negotiation import NegotiationTerms

TermsChanged = threads_repo.TermsChanged  # the router maps it to 409 `terms_changed`
StaleThread = threads_repo.StaleThread  # ... and this one to 409 `stale_status`


class DealNotFound(Exception):
    """No such deal among this brand's or creator's deals."""


class MilestonesInvalid(Exception):
    """The proposed milestones cannot pay out the agreed terms; `errors` says why."""

    def __init__(self, errors: list[str]) -> None:
        super().__init__("; ".join(errors))
        self.errors = errors


class OverCeiling(Exception):
    """The agreed price is above the brand's ceiling and the award was not confirmed."""

    def __init__(self, by_cents: int) -> None:
        super().__init__(f"{by_cents} cents over the ceiling")
        self.by_cents = by_cents


class OverTarget(Exception):
    """The batch already has its hires and the award was not confirmed."""

    def __init__(self, hired: int, target: int) -> None:
        super().__init__(f"{hired} of {target} hired")
        self.hired = hired
        self.target = target


def _agreed(ctx: dict) -> AgreedTerms:
    """The thread's latest terms as complete terms; `TermsIncomplete` when they are not."""
    raw = ctx["latest_terms"]
    return agreed_terms(
        None if raw is None else NegotiationTerms.model_validate(raw),
        brief_format=ctx["deliverables_format"],
        brief_go_live_by=ctx["go_live_by"],
    )


def _over_ceiling(ctx: dict, agreed: AgreedTerms) -> int | None:
    return over_ceiling_cents(
        price_cents=agreed.price_cents,
        videos=agreed.videos,
        brief_videos=ctx["deliverables_count"],
        ceiling_cents=ctx["budget_ceiling_cents"],
    )


def _deal_view(deal: dict, milestones: list[dict]) -> DealView:
    return DealView(
        id=deal["id"],
        thread_id=deal["thread_id"],
        batch_id=deal["batch_id"],
        status=deal["status"],
        product_name=deal["product_name"],
        terms=AgreedTerms(
            videos=deal["videos"],
            format=deal["format"],
            price_cents=deal["price_cents"],
            go_live_by=deal["go_live_by"],
            conditions=list(deal["conditions"]),
            addons=list(deal["addons"]),
        ),
        milestones=[MilestoneView(**m) for m in milestones],
        brand=DealParty(name=deal["brand_name"], email=deal["brand_email"]),
        creator=DealParty(name=deal["creator_name"], email=deal["creator_email"]),
        creator_handle=deal["creator_handle"],
        created_at=deal["created_at"],
    )


class DealsService:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def award_preview(self, brand_id: UUID, thread_id: UUID, today: date) -> AwardPreview:
        """What awarding the thread would book; writes nothing.

        Raises `ThreadNotFound`, `ActionNotAllowed` and `TermsIncomplete`.
        """
        async with self._db.acquire() as conn:
            ctx = await repo.award_context(conn, brand_id, thread_id)
            if ctx is None:
                raise ThreadNotFound
            if "award" not in brand_actions(ctx["status"]):
                raise ActionNotAllowed(ctx["status"])
            agreed = _agreed(ctx)
            target = await repo.hires_target(conn, ctx["batch_id"])
            hired = await repo.count_hired(conn, ctx["batch_id"])
            others = await repo.open_others(
                conn, brand_id, ctx["batch_id"], thread_id, sorted(OPEN_STATUSES)
            )
            terms_event_id = await threads_repo.latest_terms_event_id(conn, thread_id)
        return AwardPreview(
            agreed=agreed,
            milestones=split_even(agreed.price_cents, agreed.videos, agreed.go_live_by),
            over_ceiling_cents=_over_ceiling(ctx, agreed),
            hired=hired,
            hires_target=target,
            would_reach_target=hired + 1 == target,
            over_target=hired >= target,
            open_others=[
                CreatorChip(
                    id=o["creator_id"],
                    name=o["creator_name"],
                    handle=o["creator_handle"],
                    initials=initials(o["creator_name"]),
                )
                for o in others
            ],
            open_other_thread_ids=[o["id"] for o in others],
            terms_event_id=terms_event_id,
        )

    async def award(
        self, brand_id: UUID, thread_id: UUID, req: AwardRequest, today: date
    ) -> DealView:
        """Book the deal on the thread's latest terms with the given milestones.

        Raises `ThreadNotFound`, `TermsChanged`, `ActionNotAllowed`, `TermsIncomplete`,
        `MilestonesInvalid`, `OverCeiling` and `OverTarget`; none of them writes anything.
        """
        async with self._db.transaction() as conn:
            probe = await repo.award_context(conn, brand_id, thread_id)
            if probe is None:
                raise ThreadNotFound
            # Awards of one batch queue here, so the hire-target count below is exact.
            target = await repo.lock_batch(conn, probe["batch_id"])
            status = await threads_repo.assert_fresh(conn, thread_id, req.based_on_event_id)
            if "award" not in brand_actions(status):
                raise ActionNotAllowed(status)
            ctx = await repo.award_context(conn, brand_id, thread_id)  # as it is under the lock
            assert ctx is not None
            ref = await threads_repo.load_ref(conn, thread_id)
            assert ref is not None

            agreed = _agreed(ctx)
            errors = validate_milestones(agreed, req.milestones)
            if errors:
                raise MilestonesInvalid(errors)
            over = _over_ceiling(ctx, agreed)
            if over is not None and not req.confirm_over_ceiling:
                raise OverCeiling(over)
            hired = await repo.count_hired(conn, ctx["batch_id"])
            if hired >= target and not req.confirm_over_target:
                raise OverTarget(hired, target)

            terms = NegotiationTerms(
                videos=agreed.videos,
                format=agreed.format,
                price_cents=agreed.price_cents,
                go_live_by=agreed.go_live_by,
                conditions=agreed.conditions,
                addons=agreed.addons,
                stance="accept",
                source="in_app",
                confidence=1.0,
            )
            event_id = await threads_repo.apply_event_id(
                conn,
                ref,
                expected={status},
                target="awarded",
                type="awarded",
                actor="brand",
                terms=terms,
            )
            assert event_id is not None
            deal_id = await repo.insert_deal(
                conn,
                thread_id=thread_id,
                batch_id=ref.batch_id,
                brand_id=ref.brand_id,
                creator_id=ref.creator_id,
                package_id=ctx["package_id"],
                agreed=agreed,
                awarded_event_id=event_id,
            )
            await repo.insert_milestones(conn, deal_id, sorted(req.milestones, key=lambda m: m.seq))
            await outbox.enqueue(
                conn, kind="creator_awarded", thread_id=thread_id, event_id=event_id
            )
            return await self._view(conn, deal_id, brand_id=brand_id, creator_id=None)

    @staticmethod
    async def _view(
        conn: asyncpg.Connection, deal_id: UUID, *, brand_id: UUID | None, creator_id: UUID | None
    ) -> DealView:
        found = await repo.get_deal(conn, deal_id, brand_id=brand_id, creator_id=creator_id)
        if found is None:
            raise DealNotFound
        return _deal_view(*found)

    async def get(
        self, deal_id: UUID, *, brand_id: UUID | None, creator_id: UUID | None
    ) -> DealView:
        """A deal with both parties' contact emails, for the brand or creator that owns it."""
        async with self._db.acquire() as conn:
            return await self._view(conn, deal_id, brand_id=brand_id, creator_id=creator_id)

    async def list_for_brand(self, brand_id: UUID) -> list[DealListItem]:
        async with self._db.acquire() as conn:
            return [DealListItem(**r) for r in await repo.brand_deals(conn, brand_id)]

    async def list_for_creator(self, creator_id: UUID) -> list[DealListItem]:
        async with self._db.acquire() as conn:
            return [DealListItem(**r) for r in await repo.creator_deals(conn, creator_id)]
