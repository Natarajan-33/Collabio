"""The brand's negotiation briefs: create, read, patch and preview.

A `BriefService` belongs to one brand and every operation is scoped to its briefs: another
brand's brief is `BriefNotFound`, never a permission error that would confirm it exists.

`missing` and `violations` are computed on every read, never stored. A creator's email,
phone and floors never appear in anything returned here.
"""

from datetime import UTC, date, datetime
from typing import Any
from uuid import UUID

from app.adapters.db import Database
from app.core import brief_rules
from app.core.delta import compute_delta, pick_anchor_package
from app.core.guardrails import call_allowed, channel_violation, default_channel
from app.core.reply_token import new_reply_token
from app.modules.briefs import repo
from app.modules.briefs.launch import LaunchCandidate, plan_launch
from app.modules.discovery.service import initials, package_summary
from app.modules.threads import repo as threads_repo
from app.schemas.briefs import (
    BriefCreatorPreview,
    BriefFields,
    BriefPatch,
    BriefPreview,
    DealBrief,
    LaunchRequest,
    LaunchResponse,
)
from app.schemas.packages import PackageTerms, RuleViolation

SUMMARY_MAX = 200


class BriefNotFound(Exception):
    """No such brief among this brand's briefs."""


class BriefLaunched(Exception):
    """The brief has been launched and can no longer be edited."""


class InvalidField(Exception):
    """A patched value breaks a field rule; `message` is fit to show the brand."""

    def __init__(self, field: str, message: str) -> None:
        super().__init__(f"{field}: {message}")
        self.field = field
        self.message = message


class UnknownCreators(Exception):
    """Some requested creators do not exist or have no published package."""

    def __init__(self, ids: list[UUID]) -> None:
        super().__init__(", ".join(str(i) for i in ids))
        self.ids = ids


class BriefIncomplete(Exception):
    """The brief still misses fields or breaks a rule, so it cannot launch."""

    def __init__(self, missing: list[str], violations: list[RuleViolation]) -> None:
        super().__init__(f"missing: {missing}; violations: {[v.field for v in violations]}")
        self.missing = missing
        self.violations = violations


class CreatorsNotRegistered(Exception):
    """Some creators have no account yet, so they cannot be contacted outside demo mode."""

    def __init__(self, ids: list[UUID]) -> None:
        super().__init__(", ".join(str(i) for i in ids))
        self.ids = ids


class NoCreators(Exception):
    """Nobody is left to contact: every creator opted out or no longer has a published package."""


async def find_brand_id(db: Database, profile_id: UUID) -> UUID | None:
    """The id of the signed-in user's brand, or None when onboarding never created one."""
    async with db.acquire() as conn:
        brand = await repo.brand_for_profile(conn, profile_id)
    return None if brand is None else brand["id"]


def _utc_today() -> date:
    return datetime.now(UTC).date()


def _fields(row: dict[str, Any]) -> BriefFields:
    return BriefFields(**{name: row[name] for name in BriefFields.model_fields})


def _deal_brief(row: dict[str, Any], today: date) -> DealBrief:
    fields = _fields(row)
    return DealBrief(
        **fields.model_dump(),
        id=row["id"],
        status=row["status"],
        creator_ids=row["creator_ids"],
        approved_at=row["approved_at"],
        batch_id=row["batch_id"],
        missing=brief_rules.missing_fields(fields),
        violations=brief_rules.violations(fields, today),
    )


class BriefService:
    """`today` defaults to the UTC date; routers pass it explicitly."""

    def __init__(self, db: Database, brand_id: UUID) -> None:
        self._db = db
        self._brand_id = brand_id

    async def create(self, creator_ids: list[UUID], today: date | None = None) -> DealBrief:
        """A draft brief for these creators (duplicates dropped, order kept), prefilled from
        the brand and its first product.

        Raises `UnknownCreators` for ids that are not creators with a published package.
        """
        wanted = list(dict.fromkeys(creator_ids))
        async with self._db.transaction() as conn:
            listed = await repo.listed_creator_ids(conn, wanted)
            unknown = [i for i in wanted if i not in listed]
            if unknown:
                raise UnknownCreators(unknown)
            brand = await repo.brand_by_id(conn, self._brand_id)
            product = await repo.first_product(conn, self._brand_id)
            summary = product["summary"] if product else None
            brief_id = await repo.insert_brief(
                conn,
                brand_id=self._brand_id,
                product_id=product["id"] if product else None,
                brand_name=brand["company_name"],
                product_name=product["name"] if product else None,
                product_summary=summary[:SUMMARY_MAX] if summary else None,
                contact_email=brand["contact_email"],
                creator_ids=wanted,
            )
            row = await repo.get_brief(conn, self._brand_id, brief_id)
        assert row is not None
        return _deal_brief(row, today or _utc_today())

    async def get(self, brief_id: UUID, today: date | None = None) -> DealBrief:
        async with self._db.acquire() as conn:
            row = await repo.get_brief(conn, self._brand_id, brief_id)
        if row is None:
            raise BriefNotFound
        return _deal_brief(row, today or _utc_today())

    async def patch(self, brief_id: UUID, patch: BriefPatch, today: date) -> DealBrief:
        """Apply the fields the client sent (an explicit null clears one).

        Raises `BriefLaunched` after launch and `InvalidField` for the first value that
        breaks a field rule, saving nothing. Rules between fields (an ask above the budget
        ceiling) are saved and reported as violations. The status becomes `ready` when
        nothing is missing and no rule is broken, `draft` otherwise.
        """
        async with self._db.transaction() as conn:
            row = await repo.get_brief(conn, self._brand_id, brief_id, lock=True)
            if row is None:
                raise BriefNotFound
            if row["status"] == "launched":
                raise BriefLaunched

            values: dict[str, Any] = {}
            for name in (*BriefFields.model_fields, "intake_conversation_id"):
                if name not in patch.model_fields_set:
                    continue
                value = getattr(patch, name)
                if name == "flexibility" and value is None:
                    value = []
                if name == "hires_target" and value is None:
                    value = 1  # the column is not null: clearing it means the default
                message = brief_rules.field_error(name, value, today)
                if message:
                    raise InvalidField(name, message)
                values[name] = value

            row = row | values
            ready = brief_rules.is_launchable(_fields(row), today)
            row["status"] = values["status"] = "ready" if ready else "draft"
            await repo.update_brief(conn, brief_id, values)
        return _deal_brief(row, today)

    async def preview(self, brief_id: UUID, today: date | None = None) -> BriefPreview:
        """Per creator: the package the brief is compared against, the delta (once the
        deliverables, ask and go-live date are set), and the default channel."""
        today = today or _utc_today()
        async with self._db.acquire() as conn:
            brief = await repo.get_brief(conn, self._brand_id, brief_id)
            if brief is None:
                raise BriefNotFound
            rows = await repo.preview_rows(conn, brief["creator_ids"])

        count = brief["deliverables_count"]
        ask = brief["ask_price_cents"]
        go_live_by = brief["go_live_by"]
        creators = []
        for row in rows:
            packages = [(p["id"], PackageTerms.model_validate(p)) for p in row["packages"]]
            if not packages:  # unpublished since the brief was made
                continue
            package_id, terms = pick_anchor_package(
                packages, fmt=brief["deliverables_format"], videos=count
            )
            delta = None
            if count is not None and ask is not None and go_live_by is not None:
                delta = compute_delta(
                    package_id,
                    terms,
                    ask_videos=count,
                    ask_price_cents=ask,
                    go_live_by=go_live_by,
                    today=today,
                )
            phone, opt_in = row["phone"], row["phone_opt_in"]
            channel = default_channel(terms.preferred_channel, phone, opt_in)
            creators.append(
                BriefCreatorPreview(
                    creator_id=row["id"],
                    name=row["name"],
                    handle=row["handle"],
                    initials=initials(row["name"]),
                    package=package_summary(package_id, terms),
                    delta=delta,
                    default_channel=channel,
                    call_allowed=call_allowed(phone, opt_in),
                    excluded_reason=channel_violation(
                        channel,
                        phone=phone,
                        phone_opt_in=opt_in,
                        contact_opt_out=row["contact_opt_out"],
                    ),
                )
            )
        return BriefPreview(creators=creators)

    async def launch(
        self,
        brief_id: UUID,
        req: LaunchRequest,
        *,
        today: date,
        embedding: list[float] | None,
        hold: bool = False,
        registered_only: bool = False,
    ) -> LaunchResponse:
        """Turn a complete brief into a batch with one queued thread per creator.

        The brief row is locked for the whole transaction, so two launches of one brief
        cannot interleave (the loser sees it launched; `unique (brief_id)` on batches backs
        that up). `embedding` is the brief's search embedding, None when Gemini failed.
        Raises `BriefNotFound`, `BriefLaunched`, `BriefIncomplete`, `CreatorsNotRegistered`
        (only with `registered_only`), `ChannelNotAllowed` and `NoCreators`. The brief's
        `hires_target` is copied to the batch. `hold=True` is for tests only: it parks every new thread at
        `next_action_at = 'infinity'` so a running worker never claims it.
        """
        async with self._db.transaction() as conn:
            row = await repo.get_brief(conn, self._brand_id, brief_id, lock=True)
            if row is None:
                raise BriefNotFound
            if row["status"] == "launched":
                raise BriefLaunched
            fields = _fields(row)
            if not brief_rules.is_launchable(fields, today):
                raise BriefIncomplete(
                    brief_rules.missing_fields(fields), brief_rules.violations(fields, today)
                )

            if registered_only:
                unregistered = await repo.unregistered_creator_ids(conn, row["creator_ids"])
                if unregistered:
                    raise CreatorsNotRegistered(unregistered)

            candidates = []
            for creator in await repo.preview_rows(conn, row["creator_ids"]):
                packages = [(p["id"], PackageTerms.model_validate(p)) for p in creator["packages"]]
                if not packages:  # unpublished since the brief was made
                    continue
                package_id, terms = pick_anchor_package(
                    packages, fmt=fields.deliverables_format, videos=fields.deliverables_count
                )
                candidates.append(
                    LaunchCandidate(
                        creator_id=creator["id"],
                        package_id=package_id,
                        preferred_channel=terms.preferred_channel,
                        phone=creator["phone"],
                        phone_opt_in=creator["phone_opt_in"],
                        contact_opt_out=creator["contact_opt_out"],
                    )
                )
            planned, excluded = plan_launch(candidates, req.channels)
            if not planned:
                raise NoCreators

            batch_id = await repo.insert_batch(
                conn,
                brief_id=brief_id,
                brand_id=self._brand_id,
                follow_up_policy=req.follow_up_policy,
                embedding=embedding,
                hires_target=row["hires_target"],
            )
            for plan in planned:
                thread_id = await repo.insert_thread(
                    conn,
                    batch_id=batch_id,
                    brand_id=self._brand_id,
                    creator_id=plan.creator_id,
                    package_id=plan.package_id,
                    channel_plan=plan.channel_plan,
                    reply_token=new_reply_token(),
                    hold=hold,
                )
                ref = threads_repo.ThreadRef(
                    id=thread_id,
                    batch_id=batch_id,
                    brand_id=self._brand_id,
                    creator_id=plan.creator_id,
                )
                await threads_repo.record_event(conn, ref, type="queued", actor="brand")
            await repo.mark_launched(conn, brief_id)
        return LaunchResponse(batch_id=batch_id, thread_count=len(planned), excluded=excluded)
